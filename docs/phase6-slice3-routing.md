# Phase 6, slice 3: routing and cloud

Delivered 2026-10-18 in maluos-gateway 0.2.0. It implements FR-12 to FR-15
as applied to model calls, FR-27 to FR-33, FR-35, FR-37 to FR-39 and FR-44's
budget signals of docs/phase6-inference-gateway.md. Health cool-downs are
basic (a backend that fails at the connection level is skipped for 60 s);
alerts, delegation and export are slice 4.

## What changed

- **Backends beyond the host.** Kinds `anthropic` (Messages API), `openai`
  and `openai_compat` (Chat Completions and Embeddings), `ollama_cloud`
  (Ollama's native API with a bearer token). Each adapter translates the
  gateway's canonical request (Ollama-native chat: messages with
  images and tool calls, tools in OpenAI function form, options, format) to
  the provider and streams canonical chunks back, so every caller-facing
  API works unchanged on every backend, including streaming, tool calls,
  JSON mode and embeddings. Usage extraction per provider: tokens in, out
  and cached, and the provider's request id, all on the ledger row.
- **Credentials from the vault, per caller.** A cloud backend names a
  secret (`secret_ref`, e.g. `anthropic`); for each request the gateway asks
  the vault for that name *on behalf of the caller* (it is a vault broker),
  so the caller's own key is used when they have one, a shared key when
  they hold a `use` grant, and nothing otherwise. The vault logs every use
  with both the caller and the gateway. Keys never reach the caller and
  never appear in the gateway's logs or ledger.
- **The ladder.** A tier's aliases in position order are the rungs; each
  rung is evaluated and the ledger keeps the whole list with why each one
  was taken or skipped (`maluctl gateway routes`): disabled, unhealthy,
  policy, local_only, cloud_not_allowed, sensitivity, no_credential,
  not_enrolled, no_tools, no_vision, context_too_long, prefer_cloud,
  prefer_local, wait_exceeds_fallback. The first eligible rung runs; a
  policy may impose its own backend order (`ladder`).
- **Fallback triggers.** Expected local wait for the request's class above
  the class's `fallback_wait_s` (interactive 20 s, agent 120 s, batch never,
  per §9) sends the request to the first eligible cloud rung; a local model
  that lacks tools, vision or context the request needs is skipped; a local
  failure is retried once locally, then the next rung is tried; a failed
  cloud rung moves to the next. Attempts are counted
  (`X-MaluOS-Attempts`, `attempts` on the ledger row). Callers may say
  `X-MaluOS-Prefer: cloud|local` within policy, and `X-MaluOS-Local-Only`.
- **The sensitivity gate.** A request carries a sensitivity (header
  `X-MaluOS-Sensitivity`, default `internal`); a cloud rung is eligible only
  if it is at or below the caller's egress ceiling: the policy's
  `max_egress_sensitivity`, by default `internal` for humans and `public`
  for agents (so an agent cannot send ordinary internal data off the host
  until an operator says so). A caller cannot raise the ceiling; the hint
  can only describe the content.
- **Budgets and prices.** `maluos_price` holds list prices per million
  tokens; every call gets a cost estimate before admission (prompt size and
  requested output) and an actual cost after. A policy's `budget`
  (`usd_per_day`, `usd_per_month`, `warn_at`) is enforced at admission
  against the ledger's spend for the period: hard limit rejects with
  `budget_exceeded`, soft limit warns in the journal and on the ledger row.
- **Engine queue work** runs as principal `service:engine` (created at
  first boot), so operators can grant it cloud keys; by default it stays
  local.

## Setting up a cloud rung

```
sudo maluctl secret add system/anthropic --provider anthropic          # the shared key, from a prompt
sudo maluctl secret grant system/anthropic --to user:edward --level use
sudo maluctl gateway backend enable anthropic                          # seeded disabled; or backend add ... --kind anthropic --secret anthropic
sudo maluctl gateway catalog                                           # strong -> ollama-local/..., anthropic/claude-opus-4-1 ...
sudo maluctl gateway policy set --principal agent:research --egress internal --budget usd_per_day=5
maluctl gateway chat "hello" --model strong                            # local if ready, cloud when the queue is long
maluctl gateway routes                                                 # what was taken and why
maluctl gateway usage --by backend                                     # tokens and cost
```

A user who wants their own key stores it in their compartment
(`maluctl secret add anthropic --provider anthropic`); it is preferred over
the shared one automatically.

## Tests

- `tests/gateway-local-test.sh` now runs the vault beside the gateway and
  the mock's Anthropic, OpenAI and Ollama-cloud emulations (96 checks):
  own key versus granted shared key, the broker rows in the vault ledger,
  the agent default egress of `public`, `no_credential`, the sensitivity
  hint, local-first and prefer-cloud, local-only, fallback on expected wait
  with the skipped rung recorded, retry-then-fallback with attempts,
  Anthropic and OpenAI streaming, tool calls and cached tokens, embeddings
  on OpenAI, bearer keys on Ollama cloud, cost on the ledger, budgets (one
  call within, the next rejected), `cloud=no`, cloud models in listings, and
  that no key value appears in logs or the database.
- The image boot test adds a cloud rung through the vault-held key, the
  vault's broker row, the cost, the sensitivity gate, an ungranted user, and
  no key in the journal.

## Decisions and limits

- Prices are seeds and will be wrong by the time anyone reads them; they
  exist so budgets have something to count. Correct them with
  `maluctl gateway price set`.
- Budgets are per principal and per period from the ledger; per-key and
  per-provider budgets (grant `budget` in the vault) are recorded but not
  enforced yet.
- Capability-based skipping needs the operator to declare what a local
  model cannot do (`options.capabilities` on the backend); the gateway does
  not probe models for tool or vision support.
- Streaming fallback happens before the first byte reaches the caller; a
  backend that dies mid-stream yields an error chunk, not a retry.
- No quality judge: a local model that answers badly is still an answer
  (listed as later work in the requirements).
