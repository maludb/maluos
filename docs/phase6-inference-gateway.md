# Phase 6: the MaluOS inference gateway

Requirements for model access on a MaluOS host: one local gateway through
which every human and agent calls a model, with GPU admission control,
policy-driven routing from the local model to cloud fallbacks, per-caller
credentials held by the OS, and a ledger of every call. Status: draft for
review, 2026-10-17.

## 1. Purpose

A MaluOS VM typically runs one local model on one GPU through Ollama. The
GPU is the scarce resource: a handful of concurrent generations saturate
it, and swapping the resident model costs seconds. At the same time, some
tasks exceed what the local model can do, and some callers cannot wait.
Today each application talks to Ollama or to a cloud provider directly
with its own copy of an API key, no coordination, no accounting, and no
policy about which data may leave the host.

The gateway replaces that with a single door. It decides whether a request
runs locally or in the cloud and when, it holds and applies credentials so
callers never see them, and it records who used what, for how much, and why.

## 2. What already exists

maludb-core (0.106.0) provides pieces the gateway must build on rather than
duplicate:

| Existing | Where | Role in the gateway |
|---|---|---|
| Model request queue and responses | `malu$model_request`, `malu$model_response` | Queue of record and response ledger base |
| Provider and alias registry, per tenant | `malu$model_provider`, `malu$model_alias`, `maludb_register_model_*` | Catalogue of local and cloud models and the names callers use |
| Gateway daemon | `maludb_modeld` (bash poller: llama-cli for local, cloud not wired) | Superseded by the gateway daemon; its tables and contract are kept |
| Principals and scopes | `maludb_principal`, `maludb_principal_scope`, session settings | Caller identity and authorisation |
| Sensitivity on sources and documents | `sensitivity`, principal `max_sensitivity` | Data-egress gating for cloud routing |
| Secret store (V3 auth/secret store) | `malu$auth*` | Candidate backing store for secret metadata; see §8 |
| MC2DB listener | `maludb-mc2dbd` | MCP surface for agents; gateway tools are exposed here |
| First boot and maluctl | maluos-firstboot (Phase 4) | Provisioning of the gateway and its CLI |

## 3. Terms

- **Caller**: a Linux user or an agent process, mapped to a MaluDB principal
  (`user:edward`, `agent:research`).
- **Compartment**: the set of secrets owned by one principal.
- **Backend**: something that executes a request: local Ollama, Ollama
  cloud, Anthropic, OpenAI, others.
- **Tier**: a capability class a caller asks for instead of a model name
  (`fast`, `standard`, `strong`, `embed`); aliases map tiers to concrete
  models per backend.
- **Route**: the backend chosen for a request and the reason.
- **Class**: a scheduling priority (`interactive`, `agent`, `batch`).
- **Ledger**: the append-only record of calls, routes, usage and cost.

## 4. Goals and non-goals

Goals: every model call on the host goes through the gateway; the GPU is
scheduled, not fought over; cloud fallback is automatic within policy;
credentials never leave the gateway; every call is attributable and
accounted; the host degrades predictably when the GPU or the network is
down.

Non-goals for this phase: scheduling across several hosts; training or
fine-tuning; a web UI (the CLI and MCP tools are the interfaces); quality
judging by a second model (listed under later work); replacing Ollama's
own model management.

## 5. Architecture

```
callers (shell, agents, services, MCP clients)
   │  OpenAI-compatible and Ollama-compatible HTTP on a Unix socket
   │  (TCP + token for callers that cannot reach the socket)
   ▼
maluos-gateway (one daemon, own system user)
   ├── identity: peer credentials -> Linux user -> principal; tokens for TCP
   ├── policy: caller policy, tier, sensitivity ceiling, budgets
   ├── scheduler: per-host queue, classes, fairness, model-affinity batching
   ├── router: local -> Ollama cloud -> other cloud, by policy and live state
   ├── vault: compartments, grants, sealed secrets, credential application
   ├── adapters: ollama (local + cloud), anthropic, openai, generic-openai
   └── ledger: request, route, usage, cost, outcome -> tenant schema + memory
   ▼
backends: Ollama on this host (GPU), Ollama cloud, cloud providers
```

The daemon is `maluos-gateway`, a new package. maludb_modeld's poller role
(draining `malu$model_request`) becomes one input source to the scheduler,
so engine-originated requests (embeddings, extraction) and caller-originated
requests share the queue and the ledger.

## 6. Functional requirements

### 6.1 API surface

- FR-1 The gateway serves an OpenAI-compatible API (`/v1/chat/completions`,
  `/v1/embeddings`, `/v1/models`) and the Ollama API (`/api/chat`,
  `/api/generate`, `/api/embed`, `/api/tags`) so existing tools work with
  only a base URL change.
- FR-2 Callers may name a tier, an alias, or a concrete model. A concrete
  model name is a preference, not a guarantee, unless the caller sets
  `strict`.
- FR-3 Streaming responses are supported for chat and generate.
- FR-4 Requests may carry hints: class, maximum wait, local-only,
  sensitivity, budget cap, task reference (for the ledger and memory).
  Hints that widen policy are ignored; hints that narrow it are honoured.
- FR-5 The gateway exposes MCP tools on the MC2DB listener: `model_call`,
  `model_status` (queue depth, expected wait per tier), `secret_use`,
  `secret_list`, `usage_report`.
- FR-6 `maluctl gateway status|queue|routes|backends` show live state.

### 6.2 Identity and authorisation

- FR-7 On the Unix socket the caller's identity is the kernel-reported uid
  (peer credentials), mapped to the principal `user:<name>`. No token is
  needed for local callers. `sudo -u joseph` therefore acts as joseph.
- FR-8 Agents run as their own Linux users and are therefore principals in
  the same way; a service unit's `User=` is its identity.
- FR-9 The TCP listener (default 127.0.0.1 only) requires a bearer token
  bound to one principal; tokens are issued and revoked with `maluctl`.
- FR-10 Every request runs with the engine session bound to the caller's
  principal (`maludb_core.principal_ref`), so memory reads and writes done
  on the caller's behalf are scoped by the engine, not by the gateway.
- FR-11 Policy per principal and per scope: allowed tiers and backends,
  cloud allowed or local only, default class, budgets, maximum sensitivity
  that may leave the host (never above the principal's own ceiling).

### 6.3 Secrets

- FR-12 Secrets live in compartments owned by principals. A human's
  compartment holds that person's own keys; shared keys live in a tenant
  or scope compartment.
- FR-13 Resolution order for a provider credential: the caller's own
  compartment, then compartments granted to the caller's principal or
  scopes, then none (local only). The order is logged with the decision.
- FR-14 Grant levels: `use` (the gateway may apply it; the caller never
  reads it) and `read` (the caller may retrieve the value, with the read
  logged). Agents get `use` unless an operator grants `read`.
- FR-15 Delegation: an agent acting for a user may use that user's keys only
  under an explicit delegation grant from the user, with its own budget and
  expiry. Default: not delegated.
- FR-16 Storage: values encrypted with systemd-creds, sealed to the TPM when
  present and to the host key otherwise. Metadata (name, kind, provider,
  owner, created, rotated, expires, grants) in the tenant schema; the
  ciphertext never enters the database.
- FR-17 Per-compartment lock state. A compartment may be configured as
  always-unlocked (service accounts, default for agents) or
  unlocked-at-login (humans, optional); requests against a locked
  compartment fail with a distinct error and are logged.
- FR-18 Rotation keeps the previous value valid for a configurable grace
  window; expiry is enforced; `maluctl secret` provides add, list, grant,
  revoke, rotate, delete, export (encrypted to an operator key) and import.
- FR-19 Secret values are never written to logs, the ledger, memory, crash
  dumps or the console; the gateway redacts known credential shapes from
  error messages before storing them.

### 6.4 Scheduling

- FR-20 One queue per host for the local backend, with classes
  `interactive`, `agent`, `batch` and strict priority between classes,
  fairness (weighted round-robin by principal) within a class, and a cap on
  concurrent local generations set from the backend's capacity.
- FR-21 Each request gets a cost estimate before admission: prompt tokens,
  requested output, model size; the scheduler uses it for expected-wait
  estimates and for budget checks.
- FR-22 Model affinity: the scheduler prefers to dispatch consecutive
  requests for the resident model and switches models only when the
  waiting work for another model exceeds a threshold or a higher class is
  waiting, to avoid thrashing the GPU.
- FR-23 Expected wait per class and tier is computed continuously from
  queue contents and recent service times and is the primary routing
  signal (§6.5) and is exposed via `model_status`.
- FR-24 Callers may cancel; disconnects cancel queued requests and abort
  running ones when the backend supports it.
- FR-25 Engine-originated work (embedding dirty queue, extraction, reindex)
  enters as class `batch` unless configured otherwise, so interactive users
  are never blocked by maintenance.
- FR-26 Queue limits per class and per principal; when exceeded the request
  is either routed to the cloud (if allowed) or rejected immediately with
  the expected wait in the error, never silently queued forever.

### 6.5 Routing

- FR-27 Routing is a policy evaluated per request from: the request's tier
  and requirements (context length, tools, structured output, vision), the
  caller's policy, the data sensitivity of the request, and live state
  (expected wait, backend health, budgets).
- FR-28 Default ladder: local Ollama, then Ollama cloud, then other cloud
  providers in configured order. Ladders are configurable per tier and per
  principal.
- FR-29 Fallback triggers: expected local wait above the class threshold;
  local model lacks a required capability or context length; local failure
  or timeout; explicit caller request within policy. Each trigger is a
  named reason recorded in the ledger.
- FR-30 Sensitivity gate: a request whose content or referenced memory is
  above the sensitivity level permitted to leave the host never routes to
  a cloud backend, whatever the wait. The gateway asks the engine for the
  effective ceiling; the caller cannot raise it.
- FR-31 Retries: a failed cloud call may retry on the next rung; a failed
  local call may retry locally once before falling back. Retries are
  visible in the ledger as one request with several attempts.
- FR-32 Health: backends are probed; an unhealthy backend is skipped for a
  cool-down and its state is shown by `maluctl gateway backends`.
- FR-33 Routing decisions are explainable: `maluctl gateway routes` and the
  ledger show, for any request, the ladder considered and why each rung
  was taken or skipped.

### 6.6 Ollama

- FR-34 Local Ollama is managed as a system service under the gateway's
  supervision: model pull and residency policy (which models to keep
  warm), keep-alive settings, concurrency, and GPU memory accounting from
  Ollama's own status.
- FR-35 Ollama cloud is a backend like any other, credentialled through the
  vault, with its models mapped by alias; the gateway distinguishes
  local-only and cloud-capable model names in `/api/tags`.
- FR-36 Model names are mapped, not passed through: aliases bind tier and
  model names to concrete backend models so a caller asking for `strong`
  or for a cloud model name gets a policy-conformant route.

### 6.7 Cloud providers

- FR-37 Adapters for Anthropic, OpenAI and any OpenAI-compatible endpoint,
  with per-provider usage extraction (tokens in, out, cached) and request
  ids.
- FR-38 Provider keys are applied by the gateway only; responses are passed
  through unchanged apart from headers that would leak the credential.
- FR-39 Budgets per principal, per key and per provider, in currency per
  period, enforced at admission with the request's estimate and
  reconciled with the actual usage; soft (warn) and hard (reject) limits.

### 6.8 Ledger and audit

- FR-40 Every request produces one ledger row with: time, caller principal,
  Linux user, process identity when known (unit or executable), class,
  tier, requested model, route taken with reason, attempts, backend and
  concrete model, queue wait, service time, GPU time when local, tokens
  in/out, cost estimate and actual, status and error class, provider
  request id, task reference. Secret reads and denials are rows too.
- FR-41 The ledger is append-only in the tenant schema; the gateway holds
  insert rights only. Retention and roll-up to daily aggregates are
  configurable.
- FR-42 A memory episode is written for each request that carries a task
  reference, linking the call to what the agent was doing, so the question
  "what was this spend for" is answerable from memory.
- FR-43 `maluctl secret usage` and `maluctl gateway usage` report by user,
  principal, key, provider, model, class, route and period; `usage_report`
  exposes the same to agents within their own scope.
- FR-44 Alerts: budget thresholds crossed, a retired key still being
  presented, a sudden change in a key's usage pattern, a backend unhealthy
  beyond a limit. Delivered to the journal and to memory; hooks for
  external delivery.

### 6.9 Degradation

- FR-45 GPU or local Ollama unavailable: cloud-allowed requests continue via
  the ladder; local-only requests queue up to their limit then fail with
  reason `local_unavailable`.
- FR-46 Network unavailable: local requests continue; cloud-only requests
  fail fast with reason `cloud_unreachable`.
- FR-47 Gateway restart: queued requests are lost unless they came from
  `malu$model_request` (which is durable); the gateway reports lost
  in-flight work in the ledger on restart.
- FR-48 Vault unavailable (TPM failure, compartment locked): requests that
  need the affected credential fail with a distinct reason; local routes
  are unaffected.

### 6.10 Provisioning and administration

- FR-49 First boot installs and starts the gateway, registers local Ollama
  as a backend, creates the system user and the tenant tables, and seeds
  default tiers and policies from /etc/maluos/gateway.yaml (cloud-init
  writable, like firstboot.yaml).
- FR-50 `maluctl gateway` manages backends, tiers, aliases, policies,
  classes and thresholds; `maluctl secret` manages compartments, secrets,
  grants and delegations; `maluctl principal` gains policy flags.
- FR-51 Configuration changes apply without restarting the gateway.
- FR-52 Upgrades keep the ledger and secrets; schema changes follow
  maludb-core's extension update conventions.

## 7. Data model additions (tenant schema, sketch)

```
maluos_compartment   (id, owner_principal_ref, name, lock_mode, locked, created_at)
maluos_secret        (id, compartment_id, name, kind, provider, cred_ref,   -- systemd-creds id, no value
                      created_at, rotated_at, expires_at, previous_cred_ref, grace_until)
maluos_secret_grant  (secret_id, grantee_kind {principal,scope}, grantee_ref,
                      level {use,read}, budget_json, expires_at, granted_by, granted_at, revoked_at)
maluos_delegation    (from_principal_ref, to_principal_ref, secret_id|null, budget_json, expires_at)
maluos_policy        (subject_kind {principal,scope,default}, subject_ref,
                      allowed_tiers[], allowed_backends[], cloud_allowed, default_class,
                      max_egress_sensitivity, ladder_json, budget_json)
maluos_backend       (name, kind {ollama_local,ollama_cloud,anthropic,openai,openai_compat},
                      endpoint, secret_name|null, capacity_json, health_json, enabled)
maluos_tier          (name, requirements_json)           -- maps via malu$model_alias to backend models
maluos_class         (name, priority, max_queue, max_wait_s, fallback_wait_s, weight)
maluos_ledger        (id, ts, principal_ref, linux_user, process_ref, class, tier, requested_model,
                      route_json, attempts, backend, model, queue_wait_ms, service_ms, gpu_ms,
                      tokens_in, tokens_out, tokens_cached, cost_est, cost_actual, currency,
                      status, error_class, provider_request_id, task_ref, episode_id|null)
```

Secret values are never in these tables. Rows in `maluos_ledger` are
insertable by the gateway role only; everyone else reads through views
scoped by principal.

## 8. Non-functional requirements

- Security: the gateway runs as its own system user under strict systemd
  hardening; no network listener beyond localhost by default; the vault's
  key material is readable by the gateway only; secrets are sealed to the
  TPM when available; peer-credential checks cannot be spoofed by
  environment variables; the gateway has no privileges on memory data
  beyond the ledger and the caller-bound session.
- Performance: added latency for a local call under 10 ms at the median;
  scheduler decisions in constant time per queued request; streaming
  passthrough without buffering whole responses.
- Availability: the gateway restarts on failure in under 2 s; configuration
  reload without dropping in-flight requests.
- Observability: Prometheus metrics (queue depth and wait per class and
  tier, routes by reason, backend health, tokens and cost by route), the
  journal for events, the ledger for facts.
- Compatibility: works with Ollama's current API and the OpenAI API as
  used by common SDKs; base-URL override is the only client change.
- Upgrade: data model changes are versioned with the maluos-gateway
  package; the ledger is never rewritten.

## 9. Defaults proposed for review

These are the three decisions raised before writing; each is a setting,
so changing them later costs nothing.

| Decision | Proposed default |
|---|---|
| Priority classes | `interactive` (humans at a terminal, tools in a session), `agent` (autonomous agents), `batch` (engine maintenance, bulk jobs). Strict priority between classes, weighted fairness within. |
| Fallback thresholds (expected local wait) | interactive 20 s, agent 120 s, batch never (waits). Per-tier override allowed. |
| Agents using a user's cloud key | Only under an explicit delegation from that user, with its own budget and expiry; never by default. Shared tenant keys are the normal path for agents. |

Other defaults: TCP listener disabled unless configured; humans'
compartments always-unlocked on first install with a documented switch to
unlocked-at-login; ledger retention 400 days with daily roll-ups;
max egress sensitivity `internal` for shared keys, `public` for agents
without an explicit policy.

## 10. Delivery slices

1. **Vault and ledger**: compartments, secrets, grants, `maluctl secret`,
   ledger table and views, peer-credential identity. Also covers the
   Phase 4 token and database credentials.
2. **Gateway with local Ollama**: the daemon, both APIs, scheduler with
   classes and affinity, `model_status`, `maluctl gateway`, Ollama
   residency policy. No cloud yet; `malu$model_request` drained through it,
   retiring the poller.
3. **Routing and cloud**: ladders, fallback reasons, sensitivity gate,
   Ollama cloud, Anthropic and OpenAI adapters, budgets, usage extraction.
4. **Degradation, alerts and delegation**: health and cool-downs, restart
   accounting, alerts, user-to-agent delegation, export and import.
5. **Later**: quality-based fallback with a judge model, multi-host
   scheduling, speculative local-plus-cloud execution.

## 11. Acceptance tests (added to the image boot test as slices land)

- Two Linux users with different Anthropic keys: each call is made with the
  caller's key; the ledger attributes both; neither user can read the
  other's key; `sudo -u` switches identity.
- An agent without a grant gets a local route only; with a `use` grant it
  falls back to the cloud when the local queue exceeds the agent threshold;
  the ledger shows the reason.
- A request carrying restricted memory content never leaves the host under
  any queue length.
- Twenty concurrent batch requests do not delay an interactive request
  beyond its class threshold.
- GPU disabled: cloud-allowed callers continue, local-only callers get
  `local_unavailable` within the configured wait.
- Budget exhausted: hard limit rejects with a reason; soft limit warns in
  the journal and memory.
- No secret value appears in the journal, the ledger, memory or any error
  returned to a caller.

## 12. Risks

- The gateway is the most sensitive and the most central process on the
  host: a bug blocks all model access, a compromise exposes all keys.
  Mitigation: small code surface, strict hardening, the vault as a separate
  process boundary if the implementation language makes that cheap.
- Token and cost extraction is per-provider and changes with provider APIs.
  Mitigation: adapters isolated, unknown usage recorded as unknown rather
  than guessed.
- Expected-wait estimates drive routing; bad estimates send work to the
  cloud unnecessarily or hold it locally too long. Mitigation: estimates
  from measured service times per model, thresholds exposed, decisions
  explainable and tunable.
- TPM-sealed secrets die with the machine. Mitigation: encrypted export to
  an operator key as part of slice 4, and documentation that a compartment
  without an export has no recovery.
