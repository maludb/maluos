# MaluDB API — Setup & Operations Guide

This guide picks up **after the project is installed** and walks you, step by step, to a
running API server that mints tokens, performs LLM extraction, and is reachable from other
machines. Follow it top to bottom; every step has a command and the result you should see,
so you don't have to figure anything out as you go.

> **Already covered elsewhere:** installing the OS packages, the database, the maludb_core
> extension, and the Python project itself are in the project [README](../README.md) ("Quick
> Start") and the maludb-core Quickstart. This guide assumes those are done.

---

## Contents

1. [Prerequisites — what must already be true](#1-prerequisites)
2. [Configure environment variables](#2-configure-environment-variables)
3. [Start the server and verify it's alive](#3-start-the-server)
4. [Mint your first API token](#4-mint-your-first-api-token)
5. [Register an LLM extractor model (GPT-4o)](#5-register-an-llm-extractor-model)
6. [Ingest your first note and verify](#6-ingest-your-first-note)
7. [(Optional) Enable real embeddings + vector search](#7-optional-embeddings--vector-search)
8. [Expose the API to other machines](#8-expose-the-api-to-other-machines)
9. [Run it as a service (systemd)](#9-run-as-a-service-systemd)
10. [Verification checklist](#10-verification-checklist)
11. [Troubleshooting](#11-troubleshooting)
12. [Reference — endpoints & environment variables](#12-reference)
13. [Connect an MCP client (Claude Code / Claude Desktop)](#13-connect-an-mcp-client)

Throughout, **replace placeholders in `UPPER_CASE`** with your own values. The examples use the
project defaults (`maludb` / `app` / `#change_on_install#`); substitute yours if different.

---

## 1. Prerequisites

Before starting, confirm all of these. Each has a one-line check.

| Requirement | Check | Expected |
|---|---|---|
| Project installed in a venv | `which python && python -c "import app.main"` | path inside `.venv/`, no import error |
| PostgreSQL reachable | `pg_isready -h localhost -p 5432` | `accepting connections` |
| maludb_core installed in the tenant DB | `sudo -u postgres psql -d maludb -tAc "SELECT maludb_core.maludb_core_version()"` | `0.96.0` |
| Tenant role + schema enabled | `sudo -u postgres psql -d maludb -c "SELECT * FROM maludb_core.enable_memory_schema('app')"` | one row, `object_count` ~146 |
| Tenant role has a password | `psql "host=localhost dbname=maludb user=app password=#change_on_install#" -c "SELECT 1"` | `1` |

If the last check fails with an auth error, set the password:
```bash
sudo -u postgres psql -c "ALTER USER app PASSWORD '#change_on_install#'"
```

> **Why the role/schema matter:** maludb's convention is that each tenant connects as a
> Postgres **login role** whose name matches its **schema** (e.g. role `app` → schema `app`).
> The API puts that schema on the connection's `search_path` automatically (`"$user",
> maludb_core, public`), so the schema-local `maludb_*` views and functions resolve. You do
> not need to set `search_path` yourself.

---

## 2. Configure environment variables

All configuration is via environment variables — **the app does not read a `.env` file
automatically.** Either `export` them in the shell that launches the server, or (recommended for
anything long-running) put them in a file and load it from your service manager (see
[§9](#9-run-as-a-service-systemd)).

Create `config/maludb.env` (this path is just a convention; it's git-ignored under `data/` if
you prefer — keep secrets out of version control):

```bash
# --- PostgreSQL (tenant data) — host/port are deployment-wide ---
MALUDB_PG_HOST=localhost
MALUDB_PG_PORT=5432

# --- SQLite auth store (token → Postgres creds). Created automatically. ---
MALUDB_AUTH_STORE=/home/maludb/maludb-python-api-server/data/auth.db

# --- Logging. The default /var/log/maludb must be writable, else it falls back to var/log/. ---
MALUDB_LOG_DIR=/var/log/maludb

# --- Debug: set to 1 to allow ?debug=1 SQL traces in responses (dev only) ---
MALUDB_DEBUG=0

# --- Embeddings (optional; see §7). Without these, a deterministic dev embedding is used. ---
# MALUDB_EMBED_BASE_URL=https://api.openai.com/v1
# MALUDB_EMBED_TOKEN=sk-...
# MALUDB_EMBED_MODEL=text-embedding-3-small
MALUDB_EMBED_DIM=1536

# --- Outbound LLM/HTTP ---
MALUDB_HTTP_TIMEOUT=60
# MALUDB_LLM_TOKEN=    # fallback LLM key if not stored per-model (see §5)
```

To load it into your current shell for the dev steps below:
```bash
set -a; source config/maludb.env; set +a
```

> **Log directory permissions:** if `/var/log/maludb` doesn't exist or isn't writable by the
> service user, the app silently falls back to `<project>/var/log/`. To use the system path:
> ```bash
> sudo install -d -o "$USER" -g "$USER" /var/log/maludb
> ```

The full variable list is in the [reference table](#environment-variables).

---

## 3. Start the server

**Development** (auto-reload, localhost only):
```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Verify it's alive (no auth needed):
```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

The SQLite auth store (`data/auth.db`) is created and migrated automatically on first use —
there is no manual database bootstrap step.

> `/health` works even without maludb_core. The data endpoints and token minting require
> maludb_core in the tenant database (verified in §1).

---

## 4. Mint your first API token

Tokens are how clients authenticate. You mint one by **proving your Postgres login** — the
server connects with the credentials you supply and, if they work, issues a token.

```bash
curl -s -X POST http://localhost:8000/v1/tokens \
  -H 'Content-Type: application/json' \
  -d '{
    "pg_dbname": "maludb",
    "pg_user":   "app",
    "pg_password": "#change_on_install#",
    "device_name": "my-laptop",
    "role": "executor"
  }' | jq .
```

Response (`201`):
```json
{
  "token": "malu_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "id": 1,
  "user_id": 1,
  "role": "executor",
  "pg_dbname": "maludb",
  "pg_user": "app",
  "expires_at": null,
  "device_name": "my-laptop"
}
```

> ⚠️ **Copy the `token` now — it is shown exactly once.** Only its SHA-256 hash is stored; it
> cannot be recovered. If you lose it, mint a new one and revoke the old.

Optional fields: `expires_in_days` (positive integer; omit for non-expiring), `user_id`
(auto-assigned if omitted), `role` (defaults to `executor`).

Save the token for the next steps:
```bash
export TOKEN="malu_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

Confirm it authenticates:
```bash
curl -s http://localhost:8000/v1/subjects -H "Authorization: Bearer $TOKEN" | jq .
# {"subjects": []}   (empty graph is fine)
```

**Managing tokens** (all authorized by the same Postgres-login proof):
```bash
# List tokens for a connection (prefixes only, never the full token)
curl -s -X GET http://localhost:8000/v1/tokens \
  -H 'Content-Type: application/json' \
  -d '{"pg_dbname":"maludb","pg_user":"app","pg_password":"#change_on_install#"}' | jq .

# Revoke token id 1
curl -s -X DELETE http://localhost:8000/v1/tokens/1 \
  -H 'Content-Type: application/json' \
  -d '{"pg_dbname":"maludb","pg_user":"app","pg_password":"#change_on_install#"}' | jq .
```

---

## 5. Register an LLM extractor model

### The easy way: pick a seeded model (recommended)

The server seeds a catalog of default prompts for common models on first start
(`default_prompts` in `data/auth.db` — OpenAI, Anthropic, Google, xAI, DeepSeek, Ollama).
With just your bearer token, store your provider key and pick a model per task:

```bash
# What's available (per task: extract, skill_extract, embed)
curl -s http://localhost:8000/v1/llm/catalog -H "Authorization: Bearer $TOKEN" | jq .

# Store your provider API key (never returned by the API afterwards)
curl -s -X PUT http://localhost:8000/v1/llm/providers/openai \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"api_key":"sk-YOUR_OPENAI_KEY"}' | jq .

# Choose your extraction model (and optionally an embed model)
curl -s -X PUT http://localhost:8000/v1/llm/models/extract \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"model_name":"gpt-4o"}' | jq .
```

After that, `POST /v1/memory/ingest` without a `model` field uses your choice.
Keys and choices are per `user_id` (all your tokens share them). The
`maludb-terminal` CLI wraps these as `malu llm set-key` / `malu llm use`.

### The legacy way: register a model + prompt by hand

To register a fully custom model/prompt (or on older deployments), use
`/v1/model-prompts` with its system prompt and API key.
A ready-made GPT-4o extraction prompt ships in `config/prompts/chatgpt-4o.system.txt`.

> **Auth note:** `/v1/model-prompts` is authorized by the **Postgres login in the body**, *not*
> the bearer token (same as `/v1/tokens`).

```bash
jq -n \
  --arg sys "$(cat config/prompts/chatgpt-4o.system.txt)" \
  --arg key "sk-YOUR_OPENAI_KEY" \
  '{
     pg_dbname: "maludb", pg_user: "app", pg_password: "#change_on_install#",
     model_name: "chatgpt-4o",
     api_format: "openai",
     model_identifier: "gpt-4o",
     base_url: "https://api.openai.com/v1",
     api_key: $key,
     max_tokens: 2048,
     generation_params: { temperature: 0 },
     system_prompt: $sys
   }' \
| curl -s -X POST http://localhost:8000/v1/model-prompts \
    -H "Content-Type: application/json" --data @- | jq .
```

Expected: a `model_prompt` object with `"api_key_set": true`.

Field notes:
- `model_name` (`chatgpt-4o`) is the **lookup key** used at ingest time. It matches the ingest
  default, so you won't need to pass `model` later. (Use a different name only if you also pass
  `"model": "<that name>"` when ingesting.)
- `model_identifier` (`gpt-4o`) is what's actually sent to the provider.
- `base_url` ends in `/v1`; the code appends `/chat/completions` (OpenAI) or `/v1/messages`
  (Anthropic, when `api_format: "anthropic"`).
- The `{{ENTITY_TYPES}}` / `{{EVENT_KINDS}}` placeholders in the prompt are intentional — they're
  filled per request from your live subject-type catalog. Store the prompt as-is.

This persists in `data/auth.db`, so it's a **one-time** step (survives restarts). Verify:
```bash
curl -s -X GET http://localhost:8000/v1/model-prompts \
  -H 'Content-Type: application/json' \
  -d '{"pg_dbname":"maludb","pg_user":"app","pg_password":"#change_on_install#"}' \
  | jq '.model_prompts[] | {model_name, model_identifier, api_key_set}'
```

---

## 6. Ingest your first note

**Dry run first (no API call, no cost)** — confirms the prompt assembles and the type catalog
is wired up:
```bash
curl -s -X POST http://localhost:8000/v1/memory/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "I completed the Oracle 21c upgrade at 9 PM EST.", "preview": true}' \
  | jq '{api_format, counts}'
# counts.entity_types and counts.event_kinds should be > 0
```

**Real ingest** (calls the model, writes to the graph):
```bash
curl -s -X POST http://localhost:8000/v1/memory/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "I completed the Oracle 21c upgrade at 9 PM EST.",
    "model": "chatgpt-4o",
    "hints": [
      {"subject-type": "project", "subject-name": "Drajeo"},
      {"subject-type": "person",  "subject-name": "Ed"}
    ]
  }' | jq .
```

Expected `201` with a `result` block reporting `created` counts and an empty `skipped: []`.
Anything the facade rejected (e.g. an out-of-catalog subject type) appears in `skipped[]` with a
reason — **always check it.** New subjects/edges enter with provenance `suggested` (to be
reviewed/promoted), per the provided→suggested→accepted workflow.

Verify the data landed:
```bash
curl -s http://localhost:8000/v1/subjects -H "Authorization: Bearer $TOKEN" \
  | jq '.subjects[] | {id, label, type}'
```

`hints` are optional whole-note context (the project, the person doing the work, etc.).

---

## 7. (Optional) Embeddings & vector search

`/v1/memory/ingest` (above) does **LLM extraction** and does not require an embedding provider.
The separate `/v1/memory/documents` + `/v1/memory/search` path adds **vector search**.

- **Without** an embedding provider configured, the app generates a deterministic, repeatable
  dev embedding from the text — vector search works locally but isn't semantically meaningful.
- **With** a real provider, set these (env, or per-call in the request body):
  ```bash
  MALUDB_EMBED_BASE_URL=https://api.openai.com/v1
  MALUDB_EMBED_TOKEN=sk-...
  MALUDB_EMBED_MODEL=text-embedding-3-small
  MALUDB_EMBED_DIM=1536        # must match the model's output dimension
  ```
  The endpoint is OpenAI-shape: `POST {base_url}/embeddings`.

Ingest a document with embeddings and search it:
```bash
# Provide edges directly (no extraction model needed), embedded + ingested:
curl -s -X POST http://localhost:8000/v1/memory/documents \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Note","text":"Ada Lovelace wrote the first algorithm.",
       "edges":[{"subject_text":"Ada Lovelace","verb_text":"wrote","subject_type":"person"}]}' | jq .

# Vector search (a subject and/or verb pre-filter is required):
curl -s -X POST http://localhost:8000/v1/memory/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"who wrote an algorithm","subject":"Ada Lovelace","limit":5}' | jq .
```

---

## 8. Expose the API to other machines

By default the dev server listens on `127.0.0.1` (localhost only). To reach it from another
computer you must (a) bind a network interface, (b) open the firewall, and (c) use the server's
address from the client.

### A. Choose a binding model

| Goal | How | Security |
|---|---|---|
| Quick LAN testing | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | plain HTTP, exposed to whole LAN |
| Behind a TLS proxy (recommended) | keep `--host 127.0.0.1`; let Caddy/nginx face the network | HTTPS, origin stays local |

Find this host's address: `hostname -I` (e.g. `192.168.100.196`).

### B. Open the firewall (if `ufw` is active)
```bash
sudo ufw allow from 192.168.100.0/24 to any port 8000 proto tcp   # scope to your subnet
# or, more open:  sudo ufw allow 8000/tcp
```

### C. Call it from the client
```bash
curl -s http://192.168.100.196:8000/health          # reachability
curl -s http://192.168.100.196:8000/v1/subjects -H "Authorization: Bearer $TOKEN" | jq .
```

### D. Production: terminate TLS with a reverse proxy

**Plain HTTP sends the bearer token and note text in cleartext.** For anything beyond a trusted
LAN, put the API behind HTTPS. Keep uvicorn on `127.0.0.1:8000` and let the proxy face the world.

[Caddy](https://caddyserver.com) is the least effort (auto HTTPS for a real hostname).
`/etc/caddy/Caddyfile`:
```
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```
```bash
sudo systemctl reload caddy
# clients then use:  https://api.example.com/v1/...
```

Off-LAN with no public hostname? Use an SSH tunnel instead of opening the port:
```bash
ssh -L 8000:localhost:8000 USER@192.168.100.196   # then hit http://localhost:8000 on the client
```

---

## 9. Run as a service (systemd)

For a server that starts on boot and restarts on failure. Create
`/etc/systemd/system/maludb-api.service`:

```ini
[Unit]
Description=MaluDB API server
After=network.target postgresql.service
Wants=postgresql.service

[Service]
User=maludb
Group=maludb
WorkingDirectory=/home/maludb/maludb-python-api-server
EnvironmentFile=/home/maludb/maludb-python-api-server/config/maludb.env
ExecStart=/home/maludb/maludb-python-api-server/.venv/bin/uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now maludb-api
sudo systemctl status maludb-api          # should be active (running)
journalctl -u maludb-api -f               # follow logs
```

Notes:
- `EnvironmentFile` is how the env vars from §2 get loaded (no `.env` auto-load in the app).
- Drop `--reload` in production; use `--workers N` instead.
- Bind `127.0.0.1` and put Caddy in front (§8D). Use `--host 0.0.0.0` only for a bare LAN setup.

---

## 10. Verification checklist

Run these in order; each should succeed before moving on.

```bash
# 1. Server up
curl -s http://localhost:8000/health                       # {"status":"ok"}

# 2. maludb_core present (data endpoints work)
curl -s http://localhost:8000/v1/subjects -H "Authorization: Bearer $TOKEN"   # {"subjects":[...]}

# 3. Extractor registered with a key
curl -s -X GET http://localhost:8000/v1/model-prompts \
  -H 'Content-Type: application/json' \
  -d '{"pg_dbname":"maludb","pg_user":"app","pg_password":"#change_on_install#"}' \
  | jq '.model_prompts[] | {model_name, api_key_set}'      # api_key_set: true

# 4. Prompt assembles (no cost)
curl -s -X POST http://localhost:8000/v1/memory/ingest -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"text":"test","preview":true}' \
  | jq '.counts'                                            # entity_types/event_kinds > 0

# 5. End-to-end extraction
curl -s -X POST http://localhost:8000/v1/memory/ingest -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"Ada Lovelace wrote the first algorithm in 1843."}' \
  | jq '.result.created, .result.skipped'                  # created counts, skipped: []

# 6. (If exposing) reachable from the client machine
curl -s http://SERVER_IP:8000/health                       # {"status":"ok"}
```

---

## 11. Troubleshooting

Errors return a standard JSON shape: `{"error":{"code":"...","message":"...","sqlstate":"..."}}`.
The `message` and `sqlstate` tell you exactly what failed.

| Symptom | Cause | Fix |
|---|---|---|
| `401 auth_missing` / `auth_invalid` | Missing/typo'd/expired bearer token | Re-check the `Authorization: Bearer malu_…` header; mint a new token (§4) |
| `403 pg_auth_failed` (on `/v1/tokens` or `/v1/model-prompts`) | Postgres creds in the body are wrong | Verify with the §1 password check; fix `pg_password` |
| `502 tenant_db_auth_failed` | Token's stored Postgres password no longer valid | Re-mint the token, or fix the role's password |
| `503 tenant_db_unavailable` | Postgres down/unreachable | `pg_isready`; check `MALUDB_PG_HOST/PORT` |
| `500 schema_error` + `sqlstate 42P01/42883` (`… does not exist`) | maludb_core not installed in the tenant DB, or the schema isn't memory-enabled | Run the §1 maludb_core and `enable_memory_schema` checks |
| `422 model_not_configured` (on ingest) | No model prompt registered for that `model` | Do §5; ensure `model_name` matches the ingest `model` |
| `409 model_api_key_missing` | Model registered without an API key | Re-run §5 with a valid `api_key` |
| `502 upstream_error` | Provider call failed or returned non-JSON | Check the API key, `base_url`, network egress; try the `preview` to inspect the prompt |
| `201` but items in `result.skipped[]` | Model emitted an out-of-catalog subject type, missing key/name, or unresolved edge | Read the `reason`; tune the note/hints or register the type |
| SQL trace not in responses with `?debug=1` | Debug disabled | Set `MALUDB_DEBUG=1` and restart |

**Logs:** SQL is traced to `${MALUDB_LOG_DIR}/sql.log` (default `/var/log/maludb/sql.log`, else
`<project>/var/log/sql.log`). Application errors go to the server's stdout/journal.

**`search_path` note:** the API sets `search_path TO "$user", maludb_core, public` on every
connection, so schema-local objects resolve automatically. If you ever bypass the API and query
with `psql`, you must set it yourself:
`SET ROLE app; SET search_path TO app, maludb_core, public;`

---

## 12. Reference

### Endpoint cheat-sheet

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness |
| `POST /v1/tokens` | PG login (body) | Mint a token |
| `GET /v1/tokens` | PG login (body) | List token prefixes |
| `DELETE /v1/tokens/{id}` | PG login (body) | Revoke a token |
| `POST /v1/model-prompts` | PG login (body) | Register/update an LLM extractor (legacy) |
| `GET /v1/model-prompts` | PG login (body) | List configured models (legacy) |
| `GET /v1/llm/catalog` | Bearer token | Seeded model catalog (models × tasks) |
| `GET/PUT/DELETE /v1/llm/providers…` | Bearer token | Your LLM provider API keys |
| `GET/PUT/DELETE /v1/llm/models…` | Bearer token | Your task → model choices |
| `POST /v1/memory/ingest` | Bearer token | Text → LLM extraction → graph |
| `POST /v1/memory/documents` | Bearer token | Upload/chunk/embed/ingest (or supply `edges`) |
| `POST /v1/memory/search` | Bearer token | Embed query + vector search |
| `GET/POST/PATCH/DELETE /v1/subjects…` | Bearer token | Subjects & relationships |
| …and the rest of `/v1/*` | Bearer token | See `app/routers/` |

"PG login (body)" = supply `pg_dbname`/`pg_user`/`pg_password` in the JSON body; the server
verifies by connecting. "Bearer token" = `Authorization: Bearer malu_…`.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MALUDB_PG_HOST` | `localhost` | PostgreSQL host (all tenants) |
| `MALUDB_PG_PORT` | `5432` | PostgreSQL port |
| `MALUDB_AUTH_STORE` | `data/auth.db` | SQLite auth/routing DB path |
| `MALUDB_LOG_DIR` | `/var/log/maludb` | SQL + app log dir (falls back to `<project>/var/log/`) |
| `MALUDB_DEBUG` | (unset) | `1` enables `?debug=1` SQL traces in responses |
| `MALUDB_LLM_TOKEN` | (unset) | Fallback LLM key if not stored per-model |
| `MALUDB_EMBED_DIM` | `1536` | Embedding vector dimension (match your model) |
| `MALUDB_EMBED_BASE_URL` | (unset) | Embedding provider base URL (`…/v1`) |
| `MALUDB_EMBED_TOKEN` | (unset) | Embedding provider API key |
| `MALUDB_EMBED_MODEL` | (unset) | Embedding model id |
| `MALUDB_HTTP_TIMEOUT` | `60` | Outbound LLM/embedding HTTP timeout (seconds) |

### What persists vs. what's per-run

- **Persists** (in `data/auth.db`, survives restarts — one-time setup): minted tokens (§4),
  registered model prompts (§5).
- **Per-run** (re-applied on every start): environment variables (§2), the server process (§3/§9).

### Order of operations (the whole flow)

```
install project → §1 prerequisites → §2 env → §3 start → §4 token
   → §5 register model → §6 ingest → (§7 embeddings) → §8/§9 expose & service
```

---

## 13. Connect an MCP client

The server exposes a **Model Context Protocol** endpoint at `POST /mcp`
(stateless Streamable HTTP, spec 2025-06-18) so agents can use MaluDB as
long-term memory directly. It authenticates with the same Bearer tokens as the
REST API (§4) — tools run as the token's user, so your per-user model choices
(§5, `/v1/llm/*`) apply automatically.

Register in Claude Code:

```bash
claude mcp add --transport http maludb http://localhost:8000/mcp \
  --header "Authorization: Bearer $TOKEN"
```

**Tools** (read-only unless noted):
- `store_memory` *(write)* — note → LLM extraction → knowledge graph
- `search_memory` — semantic vector search (requires a subject/verb pre-filter;
  the error suggests matching subjects when omitted)
- `find_subjects` — list canonical entities (grounding for the other tools)
- `explore_subject` — graph neighbors / multi-hop walk around one entity
- `store_document` *(write)* — full document: chunk + extract + embed + ingest
- `get_document` — document metadata + tags by id
- `find_skills` / `get_skill` — discover stored agent skills; fetch metadata,
  SKILL.md, and the file listing (full bundles stay on the REST API)

`store_memory`/`store_document` need an extraction model (§5) and benefit from
real embeddings (§7).

Curl smoke test:

```bash
M="http://localhost:8000/mcp"; H1='Content-Type: application/json'; H2="Authorization: Bearer $TOKEN"
curl -s $M -H "$H1" -H "$H2" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' | jq .result.serverInfo
curl -si $M -H "$H1" -H "$H2" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' | head -1   # HTTP 202
curl -s $M -H "$H1" -H "$H2" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools | length'   # 8
curl -s $M -H "$H1" -H "$H2" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"find_subjects","arguments":{"limit":5}}}' | jq .
```
