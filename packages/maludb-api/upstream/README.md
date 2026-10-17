# maludb-python-simple

This serves as both a **working API server** (targeting maludb_core 0.96.0) and a **learning-friendly codebase** — every route handler contains its SQL inline, making the path from URL to query visible in one file.

## Quick Start

These steps take a **fresh Ubuntu 24.04 LTS** machine — nothing installed beyond the base OS — to a running API server. Ubuntu 24.04 already ships Python 3.12, which is the only interpreter version this project needs.

### 1. Install system packages

```bash
sudo apt update
sudo apt install -y git curl python3-venv python3-pip postgresql-17

# Pin PostgreSQL 18 so apt never offers to upgrade the cluster past 17.
# (17.x still receives its security patches; only the 18 major is blocked.)
sudo tee /etc/apt/preferences.d/no-postgresql-18 >/dev/null <<'EOF'
Package: postgresql-18 postgresql-client-18 postgresql-server-dev-18
Pin: release *
Pin-Priority: -1
EOF
```

> **Why `postgresql-17` and not `postgresql`?** The unversioned `postgresql` meta-package always depends on the newest major version available in the apt repo, so once PostgreSQL 18 ships it would offer to upgrade your cluster. Installing the versioned package — plus the pin above — keeps you on 17, which is what maludb_core targets.

### 2. Create the tenant PostgreSQL database (ONLY IF NOT DONE IN CORE INSTALL)

THIS PROCESS IS USUALLY PERFORMED WHEN THE MALUDB-CORE IS INSTALLED.  If unsure, check with your system adminidstrator.

The API is multi-tenant: every token maps to a PostgreSQL database that holds the actual knowledge graph. The maludb_core bootstrap creates its own `maludb` database for the extension itself — **that is not your tenant database, so don't point a token at it.** Instead create a separate application database (named `mydb` here) and install the `maludb_core` extension into it, along with a login role and schema both named `app`. If maludb_core was already installed with your own application database, user, and schema, you can skip these commands.

> **Stay on PostgreSQL 17.** maludb_core targets PG 17 — do not upgrade the cluster to 18. The pin added in step 1 prevents apt from offering the upgrade.

```bash
sudo -u postgres createdb mydb
sudo -u postgres psql -d mydb -c "CREATE EXTENSION maludb_core CASCADE"
sudo -u postgres psql -d mydb -tAc "SELECT maludb_core.maludb_core_version()"
sudo -u postgres psql -d mydb -c "CREATE USER app"
sudo -u postgres psql -d mydb -c "CREATE SCHEMA app AUTHORIZATION app"
sudo -u postgres psql -d mydb -c "SELECT * FROM maludb_core.enable_memory_schema('app')"
sudo -u postgres psql -d mydb -c "SET ROLE app; SET search_path TO app, maludb_core, public; SELECT * FROM maludb_subject"
sudo -u postgres psql -c "ALTER USER app PASSWORD '#change_on_install#'"
```

> **maludb_core is a prerequisite, not part of this repo.** The data endpoints (and minting a token) require the **maludb_core 0.96.0** facade views and functions to already exist in the tenant database. Install them into the `mydb` database above by following the [MaluDB](https://maludb.com) project instructions before continuing past the health check. The server itself — and `/health` — starts without it.

### 3. Clone and install the API server

```bash
git clone https://github.com/maludb/maludb-python-api-server.git
cd maludb-python-api-server

# Create and activate a virtual environment (required on Ubuntu 24.04)
python3 -m venv .venv
source .venv/bin/activate

# Install the project with its dev dependencies
pip install -e ".[dev]"
```

> **`pip install` reports `Command 'pip' not found`?** You're not in the virtual environment. Ubuntu has no system-wide `pip` command — `apt install python3-pip` only provides `pip3`, never bare `pip`. The `pip` command exists *only* after `source .venv/bin/activate`, which also changes your shell prompt to start with `(.venv)`. Verify with `which pip` — it should point inside `.venv/bin/`.

### 4. Run the dev server

```bash
uvicorn app.main:app --reload --port 8000
```

> **`Command 'uvicorn' not found, but can be installed with: sudo apt install uvicorn`?** **Do not run that apt command** — `uvicorn` is a *project* dependency (it lives in `pyproject.toml`), not a system package. The command exists only after step 3's `pip install -e ".[dev]"` completes. Two things to verify:
> 1. **You're inside the repo.** The shell prompt should end in `maludb-python-api-server`, not `~`. `pip install -e .` needs the `pyproject.toml` that lives at the repo root — and the `.venv` should be created *inside* the repo, not in your home directory. `cd ~/maludb-python-api-server` first.
> 2. **You ran the install.** With the venv active (`source .venv/bin/activate`, prompt shows `(.venv)`), run `pip install -e ".[dev]"`, then confirm with `which uvicorn` — it should point inside `.venv/bin/`.

The SQLite auth store (`data/auth.db`) is created and migrated automatically on first use — there is no manual database bootstrap step.

### 5. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Once maludb_core is installed in your tenant database, continue to [step 6, Authentication](#6-authentication) to mint your first token.

### 6. Authentication

1. Mint a token by proving your Postgres login:
   ```bash
   curl -X POST http://localhost:8000/v1/tokens \
     -H 'Content-Type: application/json' \
     -d '{"pg_dbname":"mydb","pg_user":"app","pg_password":"#change_on_install#"}'
   ```

2. Use the returned token for all other requests:
   ```bash
   curl http://localhost:8000/v1/subjects \
     -H 'Authorization: Bearer malu_...'
   ```

### 7. Automate

The dev server from [step 4](#4-run-the-dev-server) stops the moment you close the
shell — and `--reload` is for development, not production. To keep the API running
across logouts and reboots, install it as a **systemd service**. The repo ships a
ready-made unit at [`deploy/maludb-api.service`](deploy/maludb-api.service).

1. **Review the unit** and adjust `User`, `Group`, `WorkingDirectory`, and the
   `ExecStart`/`EnvironmentFile` paths if your checkout doesn't live at
   `/home/maludb/maludb-python-api-server` or runs as another user. The shipped
   unit runs uvicorn with `--workers 2` (no `--reload`) bound to `0.0.0.0:8000`.

2. **Install and enable it** so it starts now and on every boot:
   ```bash
   sudo cp deploy/maludb-api.service /etc/systemd/system/maludb-api.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now maludb-api
   ```
   `enable --now` both starts the service immediately and registers it to launch
   automatically at boot.

3. **Confirm it's serving** (same health check as step 5, now backed by systemd):
   ```bash
   curl http://localhost:8000/health
   sudo systemctl status maludb-api
   ```

Manage the running service with `systemctl`:

```bash
sudo systemctl start maludb-api      # start it
sudo systemctl stop maludb-api       # stop it
sudo systemctl restart maludb-api    # full restart (briefly drops connections)
sudo systemctl reload maludb-api     # graceful: reload workers, keep the socket open
```

> **`reload` vs `restart`.** Because the unit runs with `--workers`, `reload`
> sends `SIGHUP` to the uvicorn master process, which gracefully restarts its
> workers — picking up new code (e.g. after a `git pull`) without dropping the
> listening socket or in-flight requests. Use `restart` instead when you change
> the unit file itself or its environment, since those are read only at startup.

Follow the logs with `journalctl -u maludb-api -f`. To take the service back out
of the boot sequence, run `sudo systemctl disable --now maludb-api`.

### 6. (Optional) Run on boot as a systemd service

The dev server in step 4 runs in your terminal, prints reload logs, and stops the moment you close the shell — fine for development, wrong for a server you want back after a reboot. To run the API as a managed background service that starts automatically on boot, install the bundled unit at [`deploy/maludb-api.service`](deploy/maludb-api.service):

```bash
# The unit assumes the repo lives at /home/maludb/maludb-python-api-server and runs
# as user `maludb`. Edit User/Group/WorkingDirectory/ExecStart if your setup differs.
sudo cp deploy/maludb-api.service /etc/systemd/system/maludb-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now maludb-api      # start now AND on every boot

systemctl status maludb-api                 # confirm it's active (running)
curl http://localhost:8000/health           # {"status":"ok"}
```

Notes:
- The unit runs `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2` — production settings (multiple workers, **no `--reload`**), not the dev server from step 4. If a reverse proxy is the only front door, tighten `--host` to `127.0.0.1` in the unit.
- Put any non-default `MALUDB_*` variables in `config/maludb.env`; the unit loads it via `EnvironmentFile=-` (the leading `-` means "ignore if the file is absent"). Keep that file out of git — it may hold secrets.
- Follow the logs with `journalctl -u maludb-api -f`. `systemctl restart maludb-api` after pulling new code.

The background workers (skill/document reindex, embeddings) ship their own systemd `*.service` + `*.timer` pairs in `deploy/` — see [Architecture](#architecture) and each unit's header comment for install steps.

## Requirements

- Python 3.12+
- PostgreSQL 17 (with maludb_core 0.96.0 installed)
- No other services required (SQLite replaces MySQL for auth)

## Configuration

All configuration is via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MALUDB_PG_HOST` | `localhost` | PostgreSQL host |
| `MALUDB_PG_PORT` | `5432` | PostgreSQL port |
| `MALUDB_AUTH_STORE` | `data/auth.db` | SQLite auth database path |
| `MALUDB_DEBUG` | (unset) | Set to `1` to enable `?debug=1` |
| `MALUDB_LOG_DIR` | `/var/log/maludb` | Log directory |
| `MALUDB_STORE_KEY` | (unset) | Seals the secrets in the auth store at rest — see below. Unset = stored plain, as before |

### Secrets at rest (API 0.3.1)

The auth store keeps three secrets in ordinary columns: each tenant's **Postgres password**
(`users.pg_password`), users' **provider API keys** (`user_provider_keys.api_key`) and a model
prompt's own key (`model_prompts.api_key`). With `MALUDB_STORE_KEY` set they are stored as
`enc:v1:<Fernet token>`; the API seals on write and opens on read, so nothing else changes.

**What it protects:** the file. A backup, a copied disk or a stray `scp` of `auth.db` no longer
yields every tenant's database password. **What it does not:** someone who controls the running
service or can read its environment — the key lives beside the process. Keep the key out of the
store's backups, or the backup carries both halves.

```bash
python -m app.seal_store --new-key     # print a key; put it in config/maludb.env as MALUDB_STORE_KEY=…
sudo systemctl restart maludb-api      # new writes are sealed from here on
python -m app.seal_store --check       # how many secrets are sealed / still plain
python -m app.seal_store               # seal the existing ones — one transaction, idempotent
```

Turning it on cannot lock anyone out: a store with plain rows keeps working under a key (plain
rows still read), and the seal command opens every value it wrote before it commits. The other
direction is deliberate: a sealed row **without** its key is an error — every request answers
`503 store_key_unavailable` naming the setting — never a silent fallback.

**Rotation:** `MALUDB_STORE_KEY=<new>,<old>` (the first seals, all open) → restart →
`python -m app.seal_store --reseal` → remove `<old>` → restart.

**Losing the key loses the secrets**: every token must be minted again and every provider key
re-entered. Store a copy of the key somewhere the auth store's backups are not.

## Architecture

- **16 router modules** in `app/routers/` covering 106 route-method combinations
- **Raw SQL** via psycopg v3 — no ORM, no query builder
- **SQLite** for auth routing (token → Postgres credentials)
- **PostgreSQL** for all tenant data via maludb_core facade views
- **FastAPI dependency injection** for per-request auth + DB connections

### Agent fleets (API 0.2.0 — no extension change)

For a host that runs many AI agents against one tenant. All four routers sit on facades the tenant
schema already has.

| Route | What it is for |
|---|---|
| `POST /v1/memory/remember` | Store text so it can be found again with **no LLM call**: `{text, subject \| subjects[], verb?, namespace?}`. The text itself is the embedded span. |
| `POST /v1/memory/recall` | Search **several namespaces** at once: `{query, namespaces[], subject?, verb?, limit?}`. With no subject or verb it proposes subjects from the query by name similarity and reports `subjects_tried`. |
| `POST /v1/memory/answer` | Retrieve from a namespace and compose a **cited, verified** answer (0.4.0): every quote is checked against the evidence it cites, an unverifiable answer is withheld, no evidence calls no model. See [docs/memory-answer.md](docs/memory-answer.md). |
| `/v1/chat/sessions…`, `GET /v1/chat/search` | Ordered transcripts: start, append (one or a batch, atomically), read, finalize, search. `principal` and `external_ref` find "this agent's sessions" and "the session for run 42". |
| `/v1/principals/{ref}/profile…` | A principal's small standing memory. Updates **supersede**, deletes leave a tombstone, `/history` shows every version. |
| `GET /v1/skills/resolve`, `/v1/skills/{id}/files[/{path}]` | Resolve a skill name pinned to a `bundle_hash` or `version`; list a bundle's files; fetch one. |

**Namespaces, principal refs and external refs are labels, not access control.** A tenant token reads
everything in its tenant; the host decides which namespaces a caller may name. Enforcement inside a
tenant needs principal scoping in the extension (planned for maludb_core 0.106.0), and a truly
compartment-free recall needs an extension function: `maludb_memory_search()` requires a subject or a
verb and a tenant role cannot enumerate its vector compartments.

End-to-end tests: `MALUDB_AUTH_STORE=… MALUDB_E2E_TOKEN=malu_… pytest tests/test_agent_fleet_e2e.py`
against a **scratch** tenant — they write and, memory being append-only, do not clean up.

**Deleting a memory (0.2.1).** `DELETE /v1/documents/{id}` removes the document, its source package
and its graph edges. Its **vector chunks stay in the engine**: they live in a core table no tenant
role can reach, no facade removes them (maludb_core ≤ 0.105.x), and the exact-scan search path
ignores tombstones. So `/v1/memory/search`, `/v1/memory/recall` and the MCP `search_memory` tool
**drop any hit whose document no longer exists** (over-fetching ×3 so the limit is still filled,
and renumbering `rank_no`). A deleted memory is never returned; its text is physically removed
only once the extension deletes chunks with their document.

### Principals and scopes (API 0.3.0 — maludb_core 0.106.0)

From 0.106.0 the engine enforces, inside a tenant, **who is asking**. A host that holds the tenant
token names the principal per request; the engine — not this server — decides what it may read and
write (see `docs/principal-scoping.md` in maludb-core).

| Header | Meaning |
|---|---|
| `X-MaluDB-Principal: agent:44` | bind this request to a principal. Absent = unrestricted, as before |
| `X-MaluDB-Scopes: agent:44, dept:3` | narrow (never widen) that principal's stored grants — comma list or JSON array |
| `X-MaluDB-Readonly: true` | refuse every scoped write |

The headers can only restrict what the token may do, and a request that names a principal against a
tenant whose engine would not enforce it is **refused (501)** rather than served unscoped. Refusals
by the engine arrive as **403** (`insufficient_privilege`); a row outside the principal's scopes is a
plain 404.

| Route | |
|---|---|
| `GET /v1/whoami` | what this request is allowed: principal, read/write scopes, sensitivity ceiling |
| `GET /v1/principals`, `PUT /v1/principals/{ref}` | register / update a principal (`kind`, `home_scope`, `max_sensitivity`, `enabled`) |
| `GET/PUT/DELETE /v1/principals/{ref}/scopes[/{scope}]` | scope grants (`read` / `write`) |
| `PUT /v1/scope` | move a document, memory, episode, chat session or pool into a scope |
| `DELETE /v1/documents/{id}` | now **forgets**: the document, its vector chunks, the edges carrying its words and its source. Before 0.106.0 the chunks stayed and a deleted memory remained recallable |
| `DELETE /v1/memory/chunks/{id}` | forget one chunk |
| `POST /v1/skills/ingest` | accepts `enabled` and `review_state: "proposed"` (+ `proposed_by`) — a proposal never resolves until approved |
| `POST /v1/skills/{id}/review` | `approved` / `rejected` / `proposed`; an author cannot review their own |
| `PUT/DELETE /v1/skills/{id}/principals/{ref}` | reserve a skill for named principals |
| `POST/GET /v1/skills/{id}/loads` | record / list loads (hash, principal, run) |
| `GET/POST/DELETE /v1/pools/{id}/presence` | who is in a pool, join + heartbeat + cursor, leave |
| `POST /v1/chat/sessions` | accepts `scope` |
| `POST /v1/memory/ingest` | the namespace is now applied (document scope + the events it mints) |

A document takes the scope of the namespace of its first edge, so `POST /v1/memory/remember` with a
`namespace` makes the document — not only its chunk — private to that scope.

### Agent skills (maludb_core 0.97.0)

`POST /v1/skills/ingest` registers a Claude Agent Skill bundle (SKILL.md +
scripts/references/assets) as an immutable skill version: canonical bundle-hash
dedupe, automatic parent detection, deterministic materiality screens (with an
optional LLM judge for body-only changes), discovery-tag extraction via the
configured model (`config/prompts/skill-extract.system.txt`; register it with
`POST /v1/model-prompts`) or a deterministic frontmatter fallback, divergent
fork lineage, and supersession of non-materially-different parents.
`GET /v1/skills/{id}/bundle` returns the full bundle (base64 content, per-file
hashes, executable bits) for client-side reconstruction; `GET /v1/skills`
gains `subject`/`verb` tag search through `maludb_skill_search`. Content
fields of a registered agent skill are immutable — PATCH answers 409.
The `malu` CLI front-end is `malu skill push / push-all / list / pull`.

### Note search (maludb_core 0.98.0)

`GET /v1/memory/notes` retrieves notes by the subjects/verbs of their
extracted edges — a thin wrapper over the `maludb_note_search` facade.
Structured search: `?subject_like=ubuntu&verb_like=installation` (fuzzy
verb: bidirectional containment, so `installation` finds `install`) or
`?subject_like=ubuntu&action=install` (exact canonical/alias verb match).
Free text: `?q=Install%20Ubuntu` — parsed deterministically against the
tenant verb catalog (`maludb_note_query_parse`); when no catalog verb
matches and the user has a `query_parse` model configured (the seeded
catalog task, prompt `config/prompts/query-parse.system.txt`), the server
falls back to an LLM parse constrained to the catalog. Defaults to
documents with `source_type='note'`; `all_sources=true` widens. The MCP
server exposes the same search as the `find_notes` tool. `POST
/v1/memory/ingest` now accepts optional `source_type` and `title` body
fields (the `maludb` CLI sends `source_type: "note"`); notes ingested
before that default to `source_type='document'` and only surface with
`all_sources=true`. The CLI front-end is `maludb get note`.

### Skill reindex (maludb_core 0.99.0)

`POST /v1/skills/reindex/run` runs one background reindex sweep for the
calling tenant: it claims the stalest skills via `maludb_skill_reindex_claim`
(never indexed, older than `?max_age=` — default `30 days`, or older than the
registry watermark), re-derives their discovery tags against the *current*
knowledge graph (the user's `skill_extract` model, or the deterministic
fallback), and applies a replace-`extracted` rewrite via
`maludb_skill_reindex_apply` — curator `manual` tags are preserved by the DB.
`?limit=` (default 32) caps the batch; one skill's failure is reported in
`errors` without aborting the sweep. Returns `501` until the 0.99.0 facades
are enabled (`enable_memory_schema`). This re-derivation is what links a skill
to subjects/verbs minted *after* it was first loaded, and what repairs a weak
initial extraction (find_skill's `+100`/`+80` facets).

Drive it on a schedule with the bundled systemd timer (the "background agent"):
`deploy/maludb-skill-reindex.{service,timer}` POST the endpoint periodically —
see the unit header for install. The sweep reindexes the configured token's
tenant; run one timer per tenant token for more. (DB-side protocol:
maludb_core `docs/skill-reindex.md`.)

### Document/note reindex (maludb_core 0.100.0)

`POST /v1/memory/reindex/run` runs one background reindex sweep over documents
and notes for the calling tenant — the SVPOR-graph analogue of skill reindex.
It claims the stalest documents via `maludb_memory_reindex_claim` (never
indexed, older than `?max_age=` — default `30 days`, or older than the registry
watermark; `?source_type=note` to scope), re-derives each one's SVPOR footprint
from its stored text with the user's `extract` model, and applies a
replace-footprint rewrite via `maludb_memory_reindex_apply` (delete the
`$source`-anchored statements, re-ingest idempotently; shared subjects/verbs
merge, entity-card embeddings refresh via the 0.95.0 dirty-queue triggers).
`?limit=` (default 32) caps the batch; a document whose extraction fails is in
`errors`, one with no `extract` model configured is in `skipped`, and neither
aborts the sweep. Returns `501` until the 0.100.0 facades are enabled. This is
what links an old document to subjects/verbs minted *after* it was ingested and
repairs a weak initial extraction (so `note_search` and graph traversal find it).
Unlike skills, document reindex **requires** an `extract` model — there is no
deterministic SVPOR fallback.

Drive it on a schedule with `deploy/maludb-memory-reindex.{service,timer}` (a
modest 6-hourly cadence, since it calls a model per document) — see the unit
header for install. (DB-side protocol: maludb_core `docs/document-reindex.md`.)

### Entity-card embeddings (maludb_core 0.95.0)

`POST /v1/memory/embeddings/run` drains the entity-card embedding queue — the
long-deferred consumer of maludb_core's 0.95.0 "semantic spine". Ingest and the
skill/document reindex sweeps mark subjects, verbs, and SVO statements *dirty*;
this worker claims them via `maludb_embedding_dirty_claim`, embeds each card's
text with the user's `embed` model, and stores the vector + refreshes semantic
neighbours via `maludb_embedding_complete` (the `bytea` is built in SQL from a
`real[]` so the wire format is the DB's own). `?kinds=subject,verb` scopes;
`?limit=` (default 64) caps the batch. It returns early when no real `embed`
model is configured (the deterministic fallback isn't worth persisting). This is
what powers the optional `similar_to` semantic jumps — for **documents and
skills alike** — so it complements both reindex workers.

Drive it on a schedule with `deploy/maludb-embedding-worker.{service,timer}` (a
brisker 15-minute cadence — cards are cheap and the claim auto-skips unchanged
ones, so empty runs are nearly free).

### Memory maintenance (lifecycle / consolidation / scoring)

A small family of endpoints exposes maludb_core's memory-lifecycle functions so an
external maintenance agent can organize memories through the API instead of SQL.
Each is a thin proxy over an executor-granted `maludb_core` function (no per-schema
facade needed) and returns `501` if the core build predates the function:

- `POST /v1/memory/consolidate` — merge memories into a new consolidated memory
  (`consolidate_memories`).
- `POST /v1/memory/lifecycle` — transition an object's lifecycle state
  (`apply_lifecycle_state`).
- `POST /v1/memory/staleness` — mark an object and its dependents stale
  (`propagate_staleness`).
- `POST /v1/memory/score` — set a MAUT subscore (`set_maut_score`).
- `POST /v1/memory/reinforcement` — append a reinforcement event
  (`record_reinforcement`).
- `GET /v1/memory/retention-candidates` — list objects eligible for retention
  review (`retention_candidates`).

All write actions run inside `db_tx_core`; destructive transitions remain the
caller's responsibility to gate (the agent does so via per-tenant policy + review).

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation.

## Testing

```bash
pytest                             # full suite (262 tests)
pytest tests/test_subjects.py -v   # one file
ruff check app/ tests/             # lint
```

## Origin

This is a faithful port of the PHP LAMP version. The API contract (URLs, JSON shapes, error codes, status codes) is identical — the MaluDB desktop client works against either server.

Key differences from the PHP version:
- **SQLite** replaces MySQL for the local auth store
- **FastAPI routers** replace one-file-per-endpoint PHP scripts
- **psycopg v3** replaces PDO for PostgreSQL access
- **httpx** replaces cURL for outbound LLM calls

## License

MIT
