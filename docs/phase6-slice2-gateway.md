# Phase 6, slice 2: the gateway with local Ollama

Delivered 2026-10-18 as package `maluos-gateway` (0.1.0). It implements
FR-1 to FR-4, FR-6 to FR-11, FR-20 to FR-26, FR-34, FR-36, FR-40, FR-49 to
FR-51 of docs/phase6-inference-gateway.md and the local half of FR-5 and
FR-33. Cloud backends, the routing ladder and the sensitivity gate are
slice 3; health cool-downs, alerts and delegation are slice 4.

## What it is

One daemon, `maluos-gateway`, socket-activated on `/run/maluos/gateway.sock`
(and on 127.0.0.1:11435 with bearer tokens when `tcp.enabled` is set),
running as the system user `maluos-gateway`. It serves both API families:

| Family | Endpoints |
|---|---|
| OpenAI | POST /v1/chat/completions (streaming SSE, tools, response_format, usage), POST /v1/embeddings, GET /v1/models, GET /v1/models/{id} |
| Ollama | POST /api/chat, /api/generate, /api/embed, /api/embeddings (streaming NDJSON passthrough), GET /api/tags, /api/ps, /api/version, POST /api/show, POST /api/pull (operators) |
| MaluOS | GET /v1/maluos/health, /status, /whoami, /routes; POST /v1/maluos/reload, /warm (operators) |

Existing clients change only their base URL. The gateway translates OpenAI
calls to Ollama's native API so token counts and durations are always
present, and streams responses through without buffering.

| Piece | Where |
|---|---|
| Daemon | /usr/lib/maluos/maluos_gateway/ (server, scheduler, ollama adapter, db, config), maluos-gateway.service + .socket |
| CLI | `maluctl gateway ...` (plugin /usr/lib/maluos/maluctl.d/gateway.py) |
| Catalogue | tenant schema: maluos_backend, maluos_tier, maluos_alias, maluos_class, maluos_policy, maluos_token, maluos_gateway_status (share/schema.sql) |
| Ledger | maluos_ledger rows with event `model.call` (from maluos-vault's schema) |
| MCP tool | `maluos.model_status` on the MC2DB listener (server `maluos`), reading maluos_gateway_status |
| Ollama | /usr/lib/maluos/maluos-ollama-install: pinned release (v0.40.6, sha256-checked), user `ollama`, localhost-only unit from /usr/share/maluos-gateway/ollama.service, /etc/maluos/ollama.env |
| Mock backend | `python3 -m maluos_gateway.mock_ollama` (the native API with deterministic replies) for the harness and the boot test |
| Configuration | /etc/maluos/gateway.yaml (socket, tcp, identities, ollama, engine_queue); catalogue in the database |
| First boot | component 45-maluos-gateway |

## The model

- **Identity.** On the socket the caller is its Linux uid (peer credentials)
  → principal `user:<login>` (or `identities:` in gateway.yaml); root is an
  operator. On TCP a bearer token issued by `maluctl gateway token issue
  --principal REF` names the principal. Unenrolled Linux users may call;
  their ledger rows still carry the user and the process (`comm@unit`).
- **Names.** A caller asks for a **tier** (`fast`, `standard`, `strong`,
  `embed`), an **alias**, or a concrete **model** present on a local
  backend. A tier is a ladder of aliases in position order across backends;
  the first enabled, healthy rung is taken and the rest of the ladder is
  recorded on the ledger row (`route`) and shown by `maluctl gateway
  routes`. The reply names the concrete model; the response headers
  `X-MaluOS-Route`, `X-MaluOS-Class` and `X-MaluOS-Request` say what happened.
- **Policy.** `maluos_policy` rows for `default`, a `scope` or a `principal`
  are merged in that order: allowed tiers, allowed backends, default class,
  cloud allowed (slice 3), max egress sensitivity (slice 3). Hints that
  narrow are honoured (`X-MaluOS-Class`, `X-MaluOS-Max-Wait`,
  `X-MaluOS-Task`, or a `maluos: {...}` object in the body); hints cannot
  widen a policy.
- **Classes.** `interactive` (priority 0), `agent` (1), `batch` (2), strict
  priority between classes; round-robin by principal within a class. The
  class comes from the hint, then the policy, then the principal's kind
  (agents default to `agent`), then the highest class. Engine queue work is
  `batch`.
- **Scheduler, per backend.** `max_concurrent` slots (1 by default: one
  generation on the GPU at a time). Model affinity: while the resident
  model has work, other models wait until their oldest request has waited
  `affinity.max_wait_s` (20 s) or `affinity.max_backlog` (4) requests pile
  up. Expected wait per class is computed from measured service and load
  times per model (exponential averages) and the work ahead; it is in
  `/v1/maluos/status`, in `maluos_gateway_status` for the MCP tool, and in
  every rejection. Rejections, with the expected wait in the body: class
  queue full (`queue_full`), per-principal limit (`principal_queue_full`,
  20), expected wait above the caller's `max_wait` hint or the class's
  `max_wait_s` (`wait_exceeds`). A client that disconnects is removed from
  the queue or has its backend call aborted, and the ledger says so.
- **Ollama.** The local backend is `ollama-local` at
  http://127.0.0.1:11434. `keep_alive` is applied to every call;
  `keep_warm` models are loaded when the GPU is idle; `maluctl gateway
  ollama pull|warm|status` manage models through the gateway (operators).
  The image does not carry Ollama: `sudo maluctl gateway ollama install`
  downloads the pinned release, or set `ollama.install: true` (and
  `ollama.pull: [...]`) in gateway.yaml before first boot. GPU access is
  Ollama's own; check `journalctl -u ollama` for the devices it found.
- **Engine queue.** Rows in `malu$model_request` (submitted with
  `submit_request`) are claimed with `FOR UPDATE SKIP LOCKED`, routed by
  alias name (then model identifier), run as class `batch`, and answered in
  `malu$model_response` with tokens, latency and the gateway's route in
  `raw_provider_response`; cancellation and `timeout_ms` are honoured. The
  gateway replaces the maludb_modeld poller.
- **Ledger.** One `model.call` row per request: principal, user, process,
  class, tier, requested name, route, backend and model, queue wait,
  service and GPU time, tokens in and out, status with error class and
  reason, task reference. `maluctl gateway usage` aggregates by principal,
  model, class, backend, user or day; callers see their own rows.

## Using it

```
maluctl gateway status                      # backends, queue, expected waits, tiers
maluctl gateway chat "hello" --model fast   # quick test; --stream
OPENAI_BASE_URL=http://127.0.0.1:11435/v1 OPENAI_API_KEY=$(sudo maluctl gateway token issue --principal user:$USER)   # TCP clients
curl --unix-socket /run/maluos/gateway.sock http://g/v1/chat/completions -d '{"model":"strong","messages":[...]}'
sudo maluctl gateway ollama install && sudo maluctl gateway ollama pull llama3.1:8b
sudo maluctl gateway alias set standard --tier standard --backend ollama-local --model llama3.1:8b --position 0
sudo maluctl gateway class set agent --max-queue 100
sudo maluctl gateway policy set --principal agent:research --class agent --tiers fast,standard
maluctl gateway usage --since 7d --by model
```

Defaults for tiers (`fast` llama3.2:3b, `standard` llama3.1:8b, `strong`
qwen2.5:14b, `embed` nomic-embed-text, with second choices) are seeds for
the operator to replace with what the host can run.

## Tests

- `tests/gateway-local-test.sh`: 67 checks on the development host with the
  mock backend, no VM, no GPU: both API families including streaming,
  tools, JSON mode and embeddings; tier, alias and direct resolution with an
  unhealthy rung skipped; priority (interactive overtakes queued batch
  work), fairness between principals, the concurrency cap, expected wait,
  max-wait and queue-full rejections, cancel on disconnect; policy by tier;
  tokens on TCP (issue, use, revoke); catalogue reload; the engine queue
  (success and cancellation); the MCP status table; ledger rows and
  denials; the gateway role's limits; keep-warm.
- `tests/qcow2-boot-test.sh`: on the booted image, the real daemon with a
  mock backend started as a transient unit: identity, the seeded catalogue,
  chat and streaming over the socket, embeddings, a second user's call in
  the ledger, usage reporting, the engine queue, and the MCP tool through
  the listener.

## Decisions and limits

- Python with aiohttp: one process, asyncio, streaming both ways; the hot
  path is the backend's generation time, not the gateway. The median
  overhead on the mock is a few milliseconds.
- The scheduler's expected wait is an estimate from recent service times;
  a cold model or an unusual prompt makes it wrong until a few calls have
  been measured. Decisions are explainable (`routes`, the ledger) and the
  thresholds are settings.
- Fairness is round-robin by principal; class `weight` is reserved for
  weighted shares in a later slice.
- `model_call` as an MCP tool is not in this slice: a synchronous SQL
  function cannot wait on the gateway cleanly. Agents call the gateway over
  HTTP (any OpenAI or Ollama client) or submit through `submit_request`.
- No cloud yet: a request a local model cannot serve fails with a clear
  reason instead of falling back. Slice 3 adds the ladder beyond the host.
