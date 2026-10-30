# The MaluOS inference node API, surface 1

The management contract between an inference node and whatever manages it:
the Sovereign LLM Manager, another MaluOS desk pairing by hand, a script.
Lifted out of the local LLM server design (maluos-local-llm-server,
docs/server-design.md §2, §4, §6, §7) on 2026-10-25 as decision 1 of
docs/phase13-shared-gpus.md: **one API, two implementations**. The MaluOS
gateway (maluos-gateway, this repository, slice G2) implements it on a
MaluOS host; the node service implements it on everything else (the Mac,
the DGX Spark). The manager manages both with one worker.

Status: surface 1, implemented by the gateway in G2 (0.4.0). The columns
"gateway" and "node service" say what each implementation serves today;
a blank cell is "not yet", never "never". G3 brings the node service up to
the same table.

## 1. Transport, identity, envelope

- Prefix `/node/v1`. HTTP, JSON bodies, UTF-8. TLS is the operator's
  choice (a reverse proxy, or the LAN); the API carries no TLS of its own.
- **Bearer tokens.** Every call but `/health` carries
  `Authorization: Bearer <key>`. Two kinds of key:
  - a **node key** opens the node API (this document) and nothing else;
    on the MaluOS gateway's own Unix socket an operator (root, or one of
    the estate's operators) opens it without a key;
  - an **inference key** opens the faces (§5) under its limits and may read
    its own jobs; the node API refuses it (403).
  On the MaluOS gateway both are rows of `maluos_token` with a `kind`,
  issued by `maluctl gateway key issue` or by `POST /keys`; a key is shown
  once and only its SHA-256 is kept. Keys are the only wall: there is no
  user, no session on the node API. Inside an estate (Phase 13 slice 3,
  docs/phase13-slice3-inference.md) a third credential opens the faces: a
  member's **estate inference key**, minted by the kernel at join or enrol
  and verified by the serving gateway against the peers the kernel
  publishes for it (their keys' SHA-256 and ceilings), never issued by
  hand; the caller is the principal `node:<ref>` here, served under the
  kernel's class and classification ceilings and never with this host's
  cloud credit.
- **Envelope.** Every answer carries `node_id` (a UUID made at first start,
  also in the `X-Node-Id` header), `node_name`, `api_version` (`1`) and
  `clock` (the node's UTC time, so the manager sees skew). Times are UTC
  ISO-8601 with milliseconds.
- **Sequence.** Every mutable row carries `seq`, a node-wide monotonic
  number stamped on insert and update, so a manager syncs with
  `?since_seq=` and misses nothing. On the gateway the run sequence is the
  ledger's `ledger_id`; the catalogue sequence is a counter bumped when the
  model set changes.
- **Errors.** `{"error": {"code": "...", "message": "...", "type": "..."}}`
  with the HTTP status: 400 bad request, 401 key, 403 not allowed, 404
  unknown, 409 state, 429 limits, 503 not available. Unknown fields in a
  body are refused 400, never ignored.

## 2. Status and health

| Route | Answer | gateway | node service |
|---|---|---|---|
| `GET /status` | the node: `name`, `version`, `started_at`, `backends[]` (name, kind, endpoint, healthy, version, loaded models), `machine` (hostname, os, cpu count, memory total/free, `gpus[]` as `maluctl gpu status --json` reports them, chassis), `lanes{}` (§3), `share` (the sharing switch: enabled, contribution, chassis, rule, exposed), `counters` since start (jobs admitted, rejected, cancelled, completed), `loaded[]`, `last_manager_seen_at` | yes | G3 |
| `GET /health` | `200 {"ok": true}` when at least one backend answers, else `503`; no key | yes | G3 |
| `GET /events?since_seq=` | SSE of node events (job state, model and lane changes); recoverable through `since_seq` on `/runs` | later | later |

## 3. Lanes and the queue

A **lane** is a capacity. On the node service there are two (`local`, the
GPU; `cloud`, the provider's). On the gateway every backend is a lane,
named by the backend (`ollama-local`, `anthropic`, `gpu-1`), with `kind`
(`local`, `remote`, `cloud`); the names `local`, `remote` and `cloud` are
accepted wherever a lane is named and mean every lane of that kind.

`lanes{}` in `/status`: per lane `kind`, `capacity`, `running`, `queued`,
`paused`, `resident` (the loaded model the scheduler prefers), `classes{}`
with `queued` and `expected_wait_ms` per class, `oldest_queued_ms`.

| Route | Does | gateway | node service |
|---|---|---|---|
| `GET /queue` | every queued and running job across lanes: `id`, `lane`, `model`, `requested_model`, `principal`, `key` (the key name when the call came by key), `class`, `kind` (chat, generate, embed), `mode` (sync, async), `face`, `state`, `queued_at`, `started_at`, `waited_ms`, `elapsed_ms`, `expected_wait_ms`; and `lanes{}` as in `/status`, so one call draws a queue page | yes | G3 |
| `POST /queue/{id}/priority {class}` | move a queued job to another class (the gateway's priority is the class's; `{priority: n}` names the class with that priority number) | yes | G3 |
| `POST /queue/{id}/move {lane, model}` | force a fallback now, or move a job back, while queued | later | later |
| `DELETE /queue/{id}` | cancel; a running job's backend call is aborted; the caller gets 409 `cancelled`; the ledger row says `cancelled` with the reason `operator` | yes | G3 |
| `POST /queue/pause {lane}` / `POST /queue/resume {lane}` | stop dispatching a lane (running jobs finish; queued ones wait, and sync callers keep waiting within their `max_wait`) | yes | G3 |

## 4. Runs, models, keys

### 4.1 Runs

`GET /runs?since_seq=&limit=&status=&model=&lane=&key=&principal=` — one
row per call, newest last, `limit` 200 by default and 1000 at most. The
row is the run record:

| Group | Fields |
|---|---|
| identity | `seq`, `id` (the call id, `mg-…`), `at`, `principal`, `key`, `face` (openai, anthropic, ollama, engine), `mode`, `kind`, `task`, `job` (for async) |
| model | `requested_model`, `tier`, `backend` (= lane), `model`, `class`, `route[]` (the ladder with what was skipped and why), `attempts` |
| times | `queue_wait_ms`, `service_ms`, `gpu_ms` |
| tokens | `tokens_in`, `tokens_out`, `tokens_cached`, `cost`, `currency` |
| outcome | `status` (ok, denied, error), `reason`, `error_class`, `provider_request_id` (on a remote lane: the serving node's call id) |
| origin | `origin_request` and `origin_node` when the call came from another node's gateway (§6) |

`GET /runs/{seq}` adds `detail` (endpoint, stream, warnings, load_ms, done
reason). The manager's sync is one loop: `since_seq` from the last row it
holds, until a page is short. Payloads (prompts, answers) are never served:
the gateway keeps none.

### 4.2 Models

`GET /models?since_seq=` → `{seq, models[]}`: tiers (with their ladders),
aliases, and every model present on a backend (`name`, `backend`, `kind`,
`loaded`, `size`, `capabilities` when declared). When `since_seq` is at or
past `seq` the list is empty. Model operations (`pull`, `warm`, `unload`,
the policies of §6.5 of the server design) stay on the gateway's own
surface (`/api/pull`, `/v1/maluos/warm`, `maluctl gateway`) in G2.

### 4.3 Keys

| Route | Does |
|---|---|
| `GET /keys` | every key: `id`, `name`, `kind` (node, inference), `principal`, `limits`, `created_at`, `expires_at`, `revoked_at`, `last_used_at` |
| `POST /keys {name, kind, class?, cloud_allowed?, tiers?, max_concurrent?, expires?}` | mint a key; the answer carries `key` **once** |
| `PATCH /keys/{id} {class?, cloud_allowed?, tiers?, max_concurrent?}` | change its limits |
| `DELETE /keys/{id}` | revoke; calls in flight finish |

On the gateway an inference key is three rows: a principal `key:<name>`
(kind service), a principal policy (default class, cloud allowed, allowed
tiers) and the token. Its calls are ledgered under `key:<name>` with
`detail.token` naming the key, so the owner reads them like any other
caller's. `max_concurrent` caps the key's jobs in flight at once (the
scheduler's per-principal limit).

The node service's `/usage`, `/settings`, `/node-key/rotate` and the
policy versions are not part of surface 1 on the gateway: usage is
computed by the manager from `/runs`, settings are gateway.yaml and the
catalogue, rotation is `key issue` + `key revoke`.

## 5. The faces, async jobs and node headers

The faces serve inference with an inference key (or, on a MaluOS host, the
caller's own identity over the socket):

- **OpenAI**: `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`.
- **Anthropic**: `/v1/messages` (G2 on the gateway): `system`, content
  blocks text / image / tool_use / tool_result, `tools`, `max_tokens`,
  `stop_sequences`, `temperature`, `top_p`, `metadata`; answers the
  message object and the event stream (`message_start`,
  `content_block_start`, `content_block_delta`, `content_block_stop`,
  `message_delta` with usage, `message_stop`), errors in Anthropic's shape.
  `thinking` is refused 400 by name.
- **Ollama**: `/api/chat`, `/api/generate`, `/api/embed`, `/api/tags`.

**Modes.** `sync` is the default: the connection waits. `async` is asked
with `X-Node-Mode: async` or the body object `node: {"mode": "async"}`
(the body object also takes `tags`); the answer is `202` with `job_id`,
`status` (`queued`), `status_url`, `result_url`, `expected_wait_ms`.

| Route | Does |
|---|---|
| `GET /v1/jobs/{id}` | `status` (queued, running, done, failed, cancelled), timings, and when done the `result` in the face's shape (an OpenAI job answers a chat completion, an Anthropic job a message, an Ollama job the final object) |
| `DELETE /v1/jobs/{id}` | cancel |
| `GET /v1/jobs?status=` | the caller's own jobs (an operator's: every job) |

A job's result is kept for `result_retention_hours` (72) and at most
1000 finished jobs in memory; the ledger keeps the metadata for ever.
Webhooks, `idempotency_key`, `max_wait` turning sync into async, and
`/jobs/{id}/events` replay are later.

**Node headers** on every face answer: `X-Node-Id`, `X-Node-Job-Id` (the
call id), `X-Node-Lane` (the backend), `X-Node-Served-Model`,
`X-Node-Queue-Wait-Ms`, plus the gateway's own `X-MaluOS-Route`,
`X-MaluOS-Request`, `X-MaluOS-Class`, `X-MaluOS-Attempts`.

## 6. Pairing by hand: a node as another gateway's backend

A desk's gateway adds a shared GPU host as a backend of kind `remote`.
Inside an estate this is no longer done by hand: the directory publishes
the backends each member may use and the gateway makes a rung of kind
`estate` for each (slice 3); pairing by hand remains for a host outside
the estate or off its overlay.

```
# on the GPU host (a server shares by its chassis rule; a desktop opts in)
sudo maluctl gateway share on
sudo maluctl gateway key issue --name ed-desk --class interactive --cloud-allowed no
sudo maluctl gateway expose --bind 0.0.0.0            # tcp on 11435; refuses without a key
# on the desk
sudo maluctl gateway backend add gpu-1 http://gpu-1.lan:11435 --key mg_… [--models qwen3:32b]
sudo maluctl gateway alias set strong --tier strong --backend gpu-1 --model qwen3:32b --position 3
```

The desk's callers change nothing: the call goes to the desk's own socket,
the scheduler picks the rung by policy, class and expected wait as it does
between local and cloud, and the remote rung is one more. Rules:

- The remote key is the host's, not the caller's: it is kept in the vault
  as `system/remote-<name>` for the gateway's own use, and every call the
  desk forwards is ledgered twice: on the desk under the caller
  (`backend` = the remote, `provider_request_id` = the host's call id) and
  on the host under `key:<name>` (`origin_request` = the desk's call id,
  `origin_node` = the desk's node id). The two ids join the rows.
- A LAN node is not the cloud: the policy field `remote_allowed` (default
  true) governs it separately from `cloud_allowed`; `X-MaluOS-Local-Only`
  keeps a call on the host; the sensitivity gate applies as for the cloud
  (data leaves the host). The serving host applies its own policy to the
  key's principal.
- No chains: a call that arrived from another gateway (it carries
  `X-MaluOS-Origin-Request`) is never forwarded to a remote rung.
- The sharing switch is enforced on the serving side: with `share off` a
  key's inference call over the network is refused 503 `not_shared`; the
  node API still answers so the manager sees the switch. `contribution:
  idle` is recorded and reported; the idle detection that pauses sharing
  while a laptop's owner is active arrives with G4.

## 7. What the API never does

Serve an inference on the node routes, read a key back, serve a payload,
accept a call from a manager it has not been given a node key by, or push
to a manager (the node knows no manager address; the estate's directory
of G4 replaces pairing inside the estate).
