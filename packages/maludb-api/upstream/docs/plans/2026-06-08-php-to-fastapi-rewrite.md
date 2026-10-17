# PHP LAMP to Python FastAPI Rewrite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the MaluDB LAMP API server (59 PHP endpoint files, ~800-line shared helper, MySQL+PostgreSQL dual-database) as a Python FastAPI application that preserves the API contract, SQL traceability, and readability-first design while replacing MySQL with SQLite for the local auth store.

**Architecture:** One FastAPI router module per resource domain (subjects, verbs, projects, etc.) with raw SQL via psycopg (v3) — no ORM. A SQLite database replaces MySQL for the local auth/routing store. Shared helpers (auth, DB, error handling, SQL logging) live in dedicated modules and are injected via FastAPI dependencies. Every route handler contains its SQL inline, preserving the "URL → file → SQL" traceability the PHP project prioritizes.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, psycopg[binary] (PostgreSQL v3 adapter), aiosqlite or sqlite3 (auth store), Pydantic v2 (validation), python-multipart (file uploads), httpx (outbound LLM calls). No SQLAlchemy. No ORM.

**Source Reference:** The PHP source is cloned at `/tmp/maludb-lamp-source/`. All endpoint behavior, error codes, SQL queries, and response shapes are derived from those files. The `requirements.md` in that repo is the authoritative API contract.

**MaluDB Version Target:** maludb_core 0.96.0

---

## Design Principles (Carried from PHP)

1. **SQL traceability.** Every SQL query is a literal string in the route handler. Given a URL, a developer finds the router file (mechanical: `/v1/subjects/{id}/verbs` → `routers/subjects.py`, function `list_subject_verbs`), then reads the SQL. No query builder, no ORM.

2. **One router per domain.** The PHP project uses one file per URL path. FastAPI's router system groups related endpoints into one file per domain (subjects, verbs, projects, etc.). Each file is self-contained — all models, queries, and handlers for that domain live together.

3. **Minimal dependencies.** Only what's needed: FastAPI, psycopg, uvicorn, pydantic, python-multipart, httpx. No framework-on-top-of-framework.

4. **Learning-friendly.** Type hints everywhere. Pydantic models document the request/response shape. Each router reads top-to-bottom. No inheritance, no generic CRUD base, no magic.

5. **Contract-compatible.** Same URLs, same JSON shapes, same error codes, same HTTP status codes as the PHP server. The Electron desktop client should work against either server.

---

## Project Structure

```
maludb-python-simple/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, exception handlers, router mounting
│   ├── config.py               # Settings from environment variables
│   ├── database.py             # PostgreSQL per-tenant connection + db_query/db_exec/db_one/db_tx_core
│   ├── auth_store.py           # SQLite auth store (replaces MySQL local-database)
│   ├── auth.py                 # FastAPI dependency: Bearer token → tenant DB creds
│   ├── errors.py               # json_error, error codes, exception→response mapping
│   ├── sql_log.py              # SQL tracing to sql.log + ?debug=1 buffer
│   ├── helpers/
│   │   ├── __init__.py
│   │   ├── statements.py       # svpor_create_statement, shape_statement, statement_cols
│   │   ├── attributes.py       # svpor_create_attribute, shape_attribute, attach_attributes
│   │   ├── documents.py        # document_link_subject, document_unlink_subject, document_neighbors
│   │   └── llm.py              # LLM chat/extract/embed, chunking, provider dispatch
│   └── routers/
│       ├── __init__.py
│       ├── subjects.py         # /v1/subjects, /v1/subjects/{id}, .../verbs, .../related-subjects
│       ├── verbs.py            # /v1/verbs, /v1/verbs/{id}, .../subjects
│       ├── projects.py         # /v1/projects, /v1/projects/{id}, .../archive, .../subjects, .../verbs
│       ├── pools.py            # /v1/pools, /v1/pools/{id}, .../archive
│       ├── skills.py           # /v1/skills, /v1/skills/{id}, .../duplicate
│       ├── notes.py            # /v1/notes, /v1/notes/{id}, .../close-issue, .../reopen-issue
│       ├── episodes.py         # /v1/episodes, /v1/episodes/{id}, .../statements
│       ├── statements.py       # /v1/statements, /v1/statements/{id}
│       ├── documents.py        # /v1/documents, /v1/documents/{id}, /v1/documents-backfill
│       ├── attributes.py       # /v1/attributes, /v1/attributes/{id}, templates, check
│       ├── objects.py          # /v1/objects/{kind}, /v1/objects/{kind}/{id}
│       ├── graph.py            # /v1/edges, /v1/graph/neighbors, /v1/graph/walk
│       ├── memory.py           # /v1/memory/config, /v1/memory/documents, .../search, .../ingest
│       ├── tokens.py           # /v1/tokens, /v1/tokens/{id}
│       ├── model_prompts.py    # /v1/model-prompts
│       └── types.py            # /v1/subject-types, /v1/verb-types, /v1/document-types, /v1/episode-types
├── config/
│   ├── auth_store.sql          # SQLite schema (replaces MySQL local-database.sql)
│   └── prompts/
│       └── chatgpt-4o.system.txt   # Copied from PHP source
├── tests/
│   ├── conftest.py             # Shared fixtures (TestClient, auth, DB)
│   ├── test_subjects.py
│   ├── test_verbs.py
│   ├── test_projects.py
│   ├── test_tokens.py
│   └── ...                     # One test file per router
├── pyproject.toml              # Dependencies, project metadata, tool config
├── CLAUDE.md
├── LICENSE
└── README.md
```

---

## Key Design Decisions

### 1. SQLite replaces MySQL for the auth store

The PHP project uses MySQL (`config/local-database.php`) for exactly two tables: `users` (token→Postgres creds mapping) and `model_prompts` (LLM config per model). SQLite is the natural Python replacement:
- Built into Python's stdlib (zero install)
- File-based (no separate server process)
- Perfect for this workload (low-concurrency local lookups)
- Same relational model, same SQL

The schema is identical except for MySQL-specific syntax (AUTO_INCREMENT → INTEGER PRIMARY KEY, MEDIUMTEXT → TEXT, etc.).

### 2. psycopg v3 with sync connections (not asyncpg)

- psycopg v3 is the modern PostgreSQL adapter for Python, supports both sync and async
- Sync mode keeps route handlers simple and readable (no await chains)
- FastAPI automatically runs sync route handlers in a threadpool — no performance penalty
- Raw SQL with `%s` placeholders (psycopg's native parameterization) — mirrors PHP's `?` placeholders
- `psycopg.rows.dict_row` gives dict results like PHP's `FETCH_ASSOC`

### 3. Per-request Postgres connection (multi-tenant)

The PHP project configures Database with different creds per request (after token resolution). In Python:
- Auth dependency resolves the token → SQLite lookup → Postgres creds
- A `get_db` dependency creates a psycopg connection with those creds
- Connection is scoped to the request via FastAPI's dependency injection
- `db_tx_core` sets `search_path TO public, maludb_core` inside a transaction (same as PHP)

### 4. Error handling mirrors PHP exactly

- Custom `APIError` exception class with `code`, `message`, `status`
- Global exception handler maps psycopg `sqlstate` codes to HTTP status (23505→409, P0001→422, etc.)
- Same JSON shape: `{"error": {"code": "...", "message": "..."}}`
- Same error codes: `auth_missing`, `auth_invalid`, `not_found`, `conflict`, `validation_failed`, etc.

### 5. No Pydantic models for database rows

Pydantic is used for **request body validation only** (POST/PATCH/PUT bodies). Response dicts are built directly from database rows (with type casting), matching the PHP pattern where response shape is controlled by the SQL SELECT + manual casting. This keeps the SQL → response mapping visible in each handler.

### 6. SQL logging preserves the PHP tracing contract

- Every query logged to `sql.log` with timestamp, endpoint, method, URI, params, rows, duration
- `?debug=1` (when `MALUDB_DEBUG=1`) attaches `meta.debug` block to responses
- Per-request trace buffer collected via contextvars (thread-safe equivalent of PHP globals)

---

## Phase Plan

### Task 1: Project Foundation — pyproject.toml, config, app skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`

**Step 1: Write pyproject.toml**

```toml
[project]
name = "maludb-api"
version = "0.1.0"
description = "MaluDB API server — Python FastAPI edition (maludb_core 0.96.0)"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "psycopg[binary]>=3.2",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpx>=0.30",
    "ruff>=0.5",
]

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Write app/config.py**

Settings loaded from environment variables, matching PHP's approach (env-driven, no config files with secrets):

```python
import os
from pathlib import Path

PG_HOST: str = os.getenv("MALUDB_PG_HOST", "localhost")
PG_PORT: int = int(os.getenv("MALUDB_PG_PORT", "5432"))

AUTH_STORE_PATH: str = os.getenv("MALUDB_AUTH_STORE", str(Path(__file__).resolve().parent.parent / "data" / "auth.db"))

DEBUG_ENABLED: bool = os.getenv("MALUDB_DEBUG", "") == "1"

LOG_DIR: str = os.getenv("MALUDB_LOG_DIR", "/var/log/maludb")

LLM_TOKEN: str | None = os.getenv("MALUDB_LLM_TOKEN") or None
EMBED_DIM: int = int(os.getenv("MALUDB_EMBED_DIM", "1536"))
```

**Step 3: Write app/main.py (skeleton)**

```python
from fastapi import FastAPI

app = FastAPI(title="MaluDB API", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok"}
```

**Step 4: Verify the skeleton runs**

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
```
Expected: `{"status":"ok"}`

**Step 5: Commit**

```bash
git add pyproject.toml app/
git commit -m "feat: project skeleton with FastAPI, config, and health endpoint"
```

---

### Task 2: Error Handling — APIError, exception handlers, json_error

**Files:**
- Create: `app/errors.py`
- Modify: `app/main.py` (register exception handlers)

**Step 1: Write the failing test**

```python
# tests/test_errors.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_404_returns_standard_error_shape():
    r = client.get("/v1/nonexistent")
    assert r.status_code == 404

def test_method_not_allowed_shape():
    # Once we have a real endpoint, test 405 — placeholder for now
    pass
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_errors.py -v
```

**Step 3: Implement app/errors.py**

Port the PHP `json_error()` function and the global `handle_uncaught()` exception handler:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

class APIError(Exception):
    def __init__(self, code: str, message: str, status: int):
        self.code = code
        self.message = message
        self.status = status

def json_error(code: str, message: str, status: int):
    raise APIError(code, message, status)

async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
```

Add psycopg exception mapping (mirrors PHP SQLSTATE → HTTP status):

```python
import psycopg

SQLSTATE_MAP = {
    "23505": (409, "conflict"),           # unique_violation
    "42501": (403, "insufficient_privilege"),
    "23502": (422, "validation_failed"),  # not_null_violation
    "23503": (422, "validation_failed"),  # foreign_key_violation
    "23514": (422, "validation_failed"),  # check_violation
    "22000": (422, "validation_failed"),  # data_exception
    "22023": (422, "validation_failed"),  # invalid_parameter_value
    "22P02": (422, "validation_failed"),  # invalid_text_representation
    "P0001": (422, "validation_failed"),  # raise_exception (trigger)
}

async def psycopg_error_handler(request: Request, exc: psycopg.errors.DatabaseError) -> JSONResponse:
    sqlstate = exc.sqlstate or ""
    if sqlstate in SQLSTATE_MAP:
        status, code = SQLSTATE_MAP[sqlstate]
        message = _pg_error_message(exc)
    else:
        status, code, message = 500, "internal_error", "An unexpected error occurred."
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

def _pg_error_message(exc: Exception) -> str:
    msg = str(exc)
    if "ERROR:" in msg:
        return msg.split("ERROR:", 1)[1].split("\n", 1)[0].strip()
    return msg
```

Register handlers in `app/main.py`.

**Step 4: Run tests**

```bash
pytest tests/test_errors.py -v
```

**Step 5: Commit**

```bash
git add app/errors.py tests/test_errors.py
git commit -m "feat: error handling with APIError, SQLSTATE mapping, standard JSON error shape"
```

---

### Task 3: SQL Logging — sql_log, debug buffer, contextvars

**Files:**
- Create: `app/sql_log.py`

**Step 1: Write the failing test**

```python
# tests/test_sql_log.py
from app.sql_log import SqlTracer

def test_tracer_collects_queries():
    tracer = SqlTracer()
    tracer.log("SELECT 1", [], rows=1, dur_ms=0.5)
    assert len(tracer.queries) == 1
    assert tracer.queries[0]["sql"] == "SELECT 1"
    assert tracer.queries[0]["rows"] == 1
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_sql_log.py -v
```

**Step 3: Implement app/sql_log.py**

Port PHP's `sql_log()`, `iso_now_ms()`, and per-request `$GLOBALS['__sql_trace']` using Python contextvars:

```python
import contextvars
import time
from datetime import datetime, timezone
from pathlib import Path

from app import config

_request_tracer: contextvars.ContextVar["SqlTracer | None"] = contextvars.ContextVar("sql_tracer", default=None)

class SqlTracer:
    def __init__(self):
        self.queries: list[dict] = []
        self.endpoint: str = ""
        self.method: str = ""
        self.uri: str = ""
        self.user_id: int | str = "anon"

    def log(self, sql: str, params: list, *, rows: int, dur_ms: float):
        entry = {"sql": sql.strip(), "params": params, "rows": rows, "dur_ms": round(dur_ms, 1)}
        self.queries.append(entry)
        _write_log_line(self, entry)

def get_tracer() -> SqlTracer:
    t = _request_tracer.get()
    if t is None:
        t = SqlTracer()
        _request_tracer.set(t)
    return t

def set_tracer(tracer: SqlTracer):
    _request_tracer.set(tracer)

def _iso_now_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"

def _write_log_line(tracer: SqlTracer, entry: dict):
    # Append to sql.log, matching PHP format
    log_dir = Path(config.LOG_DIR)
    if not log_dir.is_dir():
        log_dir = Path(__file__).resolve().parent.parent / "var" / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
    line = (
        f"{_iso_now_ms()}  {tracer.endpoint}  {tracer.method}  {tracer.uri}  user={tracer.user_id}\n"
        f"  SQL: {entry['sql']}\n"
        f"  PARAMS: {entry['params']}\n"
        f"  ROWS: {entry['rows']}\n"
        f"  DUR:  {entry['dur_ms']:.1f} ms\n\n"
    )
    try:
        (log_dir / "sql.log").open("a").write(line)
    except OSError:
        pass
```

**Step 4: Run tests**

```bash
pytest tests/test_sql_log.py -v
```

**Step 5: Commit**

```bash
git add app/sql_log.py tests/test_sql_log.py
git commit -m "feat: SQL tracing with per-request buffer and file logging"
```

---

### Task 4: SQLite Auth Store — replaces MySQL local-database

**Files:**
- Create: `config/auth_store.sql`
- Create: `app/auth_store.py`

**Step 1: Write the failing test**

```python
# tests/test_auth_store.py
import sqlite3
import tempfile
from pathlib import Path
from app.auth_store import AuthStore

def test_resolve_token_returns_creds():
    with tempfile.TemporaryDirectory() as d:
        store = AuthStore(str(Path(d) / "auth.db"))
        store.init_db()
        # Insert a test row
        store.conn.execute(
            "INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["abc123hash", "abc12345", 1, "executor", "testdb", "testuser", "testpass"],
        )
        store.conn.commit()
        row = store.resolve_token("abc123hash")
        assert row is not None
        assert row["pg_dbname"] == "testdb"
        assert row["user_id"] == 1

def test_resolve_token_returns_none_for_unknown():
    with tempfile.TemporaryDirectory() as d:
        store = AuthStore(str(Path(d) / "auth.db"))
        store.init_db()
        assert store.resolve_token("nonexistent") is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_auth_store.py -v
```

**Step 3: Write config/auth_store.sql**

Direct port of PHP's `config/local-database.sql`, adapted for SQLite:

```sql
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash      TEXT    NOT NULL UNIQUE,
    token_prefix    TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'executor',
    pg_dbname       TEXT    NOT NULL,
    pg_user         TEXT    NOT NULL,
    pg_password     TEXT    NOT NULL,
    expires_at      TEXT,           -- ISO-8601 UTC or NULL (no expiry)
    device_name     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS model_prompts (
    model_name       TEXT PRIMARY KEY,
    model_identifier TEXT,
    api_format       TEXT NOT NULL DEFAULT 'openai',
    system_prompt    TEXT,
    base_url         TEXT,
    api_key          TEXT,
    max_tokens       INTEGER DEFAULT 2048,
    generation_params TEXT,  -- JSON
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

**Step 4: Implement app/auth_store.py**

```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class AuthStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def init_db(self):
        schema = (Path(__file__).resolve().parent.parent / "config" / "auth_store.sql").read_text()
        self.conn.executescript(schema)

    def resolve_token(self, token_hash: str) -> dict | None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = self.conn.execute(
            "SELECT user_id, role, pg_dbname, pg_user, pg_password "
            "FROM users WHERE token_hash = ? AND (expires_at IS NULL OR expires_at > ?)",
            (token_hash, now),
        ).fetchone()
        return dict(row) if row else None

    def next_user_id(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(user_id), 0) + 1 AS next_id FROM users").fetchone()
        return row["next_id"]

    def model_prompt(self, model_name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT model_name, model_identifier, api_format, system_prompt, "
            "base_url, api_key, max_tokens, generation_params FROM model_prompts WHERE model_name = ?",
            (model_name,),
        ).fetchone()
        return dict(row) if row else None
```

**Step 5: Run tests and commit**

```bash
pytest tests/test_auth_store.py -v
git add config/auth_store.sql app/auth_store.py tests/test_auth_store.py
git commit -m "feat: SQLite auth store replacing MySQL local-database"
```

---

### Task 5: PostgreSQL Database Layer — db_query, db_exec, db_one, db_tx_core

**Files:**
- Create: `app/database.py`

**Step 1: Write the failing test**

```python
# tests/test_database.py
from app.database import TenantConnection

def test_tenant_connection_raises_on_bad_creds():
    # Testing with intentionally bad credentials
    tc = TenantConnection("nonexistent_db", "bad_user", "bad_pass", "localhost", 5432)
    try:
        tc.connect()
        assert False, "Should have raised"
    except Exception:
        pass  # Expected: connection failure
```

**Step 2: Implement app/database.py**

Port PHP's `Database` singleton, `db_query/db_exec/db_one`, and `db_tx_core`:

```python
import psycopg
from psycopg.rows import dict_row
from app.sql_log import get_tracer
import time

class TenantDatabaseError(Exception):
    def __init__(self, message: str, is_auth_failure: bool = False):
        super().__init__(message)
        self.is_auth_failure = is_auth_failure

class TenantConnection:
    def __init__(self, dbname: str, user: str, password: str, host: str, port: int):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.conn: psycopg.Connection | None = None

    def connect(self) -> psycopg.Connection:
        try:
            self.conn = psycopg.connect(
                dbname=self.dbname, user=self.user, password=self.password,
                host=self.host, port=self.port, row_factory=dict_row,
            )
            return self.conn
        except psycopg.OperationalError as e:
            msg = str(e)
            is_auth = "password authentication failed" in msg or "no pg_hba.conf entry" in msg
            raise TenantDatabaseError(msg, is_auth_failure=is_auth) from e

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

def db_query(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> list[dict]:
    t0 = time.perf_counter()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    dur = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, list(params), rows=len(rows), dur_ms=dur)
    return rows

def db_exec(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> int:
    t0 = time.perf_counter()
    cur = conn.execute(sql, params)
    n = cur.rowcount
    dur = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, list(params), rows=n, dur_ms=dur)
    return n

def db_one(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> dict | None:
    t0 = time.perf_counter()
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    dur = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, list(params), rows=1 if row else 0, dur_ms=dur)
    return row

def db_tx_core(conn: psycopg.Connection, fn):
    """Run fn(conn) in a transaction with search_path = public, maludb_core."""
    with conn.transaction():
        conn.execute("SET LOCAL search_path TO public, maludb_core")
        return fn(conn)

def test_credentials(dbname: str, user: str, password: str, host: str, port: int) -> bool:
    try:
        c = psycopg.connect(dbname=dbname, user=user, password=password, host=host, port=port)
        c.close()
        return True
    except Exception:
        return False
```

**Step 3: Run tests and commit**

```bash
pytest tests/test_database.py -v
git add app/database.py tests/test_database.py
git commit -m "feat: PostgreSQL database layer with db_query/db_exec/db_one/db_tx_core"
```

---

### Task 6: Auth Dependency — Bearer token → tenant connection

**Files:**
- Create: `app/auth.py`
- Modify: `app/main.py` (add request middleware for SQL tracer setup)

**Step 1: Write the failing test**

```python
# tests/test_auth.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_missing_auth_returns_401():
    r = client.get("/v1/subjects")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_missing"

def test_malformed_token_returns_401():
    r = client.get("/v1/subjects", headers={"Authorization": "Bearer badtoken"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_invalid"
```

**Step 2: Implement app/auth.py**

Port PHP's `require_auth()` as a FastAPI dependency:

```python
import hashlib
from typing import Annotated
from fastapi import Depends, Request
import psycopg
from app import config
from app.auth_store import AuthStore
from app.database import TenantConnection
from app.errors import json_error
from app.sql_log import get_tracer

_auth_store: AuthStore | None = None

def get_auth_store() -> AuthStore:
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore(config.AUTH_STORE_PATH)
        _auth_store.init_db()
    return _auth_store

class AuthContext:
    def __init__(self, user_id: int, role: str, conn: psycopg.Connection):
        self.user_id = user_id
        self.role = role
        self.conn = conn

def require_auth(request: Request) -> AuthContext:
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        json_error("auth_missing", "Authorization: Bearer token required.", 401)

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        json_error("auth_invalid", "Malformed Authorization header.", 401)

    token = parts[1]
    if not token.startswith("malu_"):
        json_error("auth_invalid", "Malformed API token.", 401)

    token_body = token[len("malu_"):]
    token_hash = hashlib.sha256(token_body.encode()).hexdigest()

    store = get_auth_store()
    row = store.resolve_token(token_hash)
    if row is None:
        json_error("auth_invalid", "Invalid or expired API token.", 401)

    tc = TenantConnection(row["pg_dbname"], row["pg_user"], row["pg_password"], config.PG_HOST, config.PG_PORT)
    conn = tc.connect()

    tracer = get_tracer()
    tracer.user_id = row["user_id"]

    return AuthContext(user_id=row["user_id"], role=row["role"], conn=conn)

Auth = Annotated[AuthContext, Depends(require_auth)]
```

**Step 3: Add middleware to main.py for tracer setup and connection cleanup**

The middleware initializes a fresh `SqlTracer` per request and ensures the Postgres connection is closed after the response:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from app.sql_log import SqlTracer, set_tracer

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        tracer = SqlTracer()
        tracer.endpoint = request.url.path.split("/")[-1]
        tracer.method = request.method
        tracer.uri = str(request.url)
        set_tracer(tracer)
        response = await call_next(request)
        return response
```

**Step 4: Run tests and commit**

```bash
pytest tests/test_auth.py -v
git add app/auth.py tests/test_auth.py
git commit -m "feat: Bearer token auth dependency with SQLite lookup and tenant Postgres connection"
```

---

### Task 7: Debug Middleware — ?debug=1 meta block

**Files:**
- Modify: `app/main.py` (add debug response middleware)

**Step 1: Write the failing test**

```python
# tests/test_debug.py
# Test that ?debug=1 adds meta.debug to responses (when MALUDB_DEBUG=1)
```

**Step 2: Implement debug response hook**

After the response is generated, if `?debug=1` and `DEBUG_ENABLED`, inject the `meta.debug` block into JSON responses. This mirrors PHP's `json_response()` behavior.

**Step 3: Run tests and commit**

```bash
pytest tests/test_debug.py -v
git commit -m "feat: debug mode (?debug=1) injects SQL trace into responses"
```

---

### Task 8: Tokens Router — /v1/tokens (self-service auth)

**Files:**
- Create: `app/routers/tokens.py`
- Create: `tests/test_tokens.py`

This is the bootstrap endpoint — it doesn't use `require_auth()`. Authorization is by Postgres login proof (same as PHP). Implement:

- `POST /v1/tokens` — mint a token (verify Postgres creds, generate `malu_<base64url(32)>`, store sha256 hash in SQLite, return plaintext ONCE)
- `GET /v1/tokens` — list tokens for a connection (metadata only)
- `DELETE /v1/tokens/{id}` — revoke a token

Port from: `/tmp/maludb-lamp-source/html/v1/tokens.php` and `tokens_id.php`

**Step 1: Write the failing test**

```python
# tests/test_tokens.py
def test_post_token_requires_pg_creds():
    r = client.post("/v1/tokens", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "missing_field"
```

**Step 2: Implement routers/tokens.py and mount in main.py**

**Step 3: Run tests and commit**

```bash
pytest tests/test_tokens.py -v
git commit -m "feat: /v1/tokens — token create, list, revoke (SQLite auth store)"
```

---

### Task 9: Subjects Router — /v1/subjects (core CRUD + sub-resources)

**Files:**
- Create: `app/routers/subjects.py`
- Create: `tests/test_subjects.py`

The first "real" endpoint domain. Implement all routes:

- `GET /v1/subjects` — list with `?q=`, `?limit=`, `?with=attributes`, embedded `linked_verbs`/`related_subjects` counts
- `POST /v1/subjects` — create (label, type, description, classifier_md)
- `GET /v1/subjects/{id}` — detail with embedded `verbs[]`, `related_subjects[]`, `documents[]`
- `PATCH /v1/subjects/{id}` — update fields
- `DELETE /v1/subjects/{id}` — remove
- `GET /v1/subjects/{id}/verbs` — linked verbs list
- `POST /v1/subjects/{id}/verbs` — link a verb
- `DELETE /v1/subjects/{id}/verbs/{verb_id}` — unlink
- `GET /v1/subjects/{id}/related-subjects` — related subjects list
- `POST /v1/subjects/{id}/related-subjects` — create relationship
- `DELETE /v1/subjects/{id}/related-subjects/{other_id}` — remove relationship
- `GET /v1/subject-relationships/{rel_id}` — row-level access
- `PATCH /v1/subject-relationships/{rel_id}` — update type/label/temporal bounds
- `DELETE /v1/subject-relationships/{rel_id}` — remove

Port from: `subjects.php`, `subjects_id.php`, `subjects_id_verbs.php`, `subjects_id_verbs_id.php`, `subjects_id_related-subjects.php`, `subjects_id_related-subjects_id.php`, `subject-relationships_id.php`

Each route handler contains its SQL inline. Example pattern:

```python
@router.get("/v1/subjects")
def list_subjects(auth: Auth, q: str | None = None, limit: int = 50, with_: str | None = Query(None, alias="with")):
    if limit > 200:
        limit = 200
    params: list = []
    where = ""
    if q:
        where = "WHERE s.canonical_name ILIKE %s OR s.description ILIKE %s"
        params = [f"%{q}%", f"%{q}%"]

    rows = db_query(auth.conn, f"""
        SELECT s.subject_id AS id, s.canonical_name AS label, s.subject_type AS type,
               s.description, s.classifier_md,
               (SELECT count(*) FROM maludb_subject_verb sv WHERE sv.subject_name = s.canonical_name) AS linked_verbs,
               (SELECT count(*) FROM maludb_subject_relationship r
                  WHERE r.from_subject_id = s.subject_id OR r.to_subject_id = s.subject_id) AS related_subjects
          FROM maludb_subject s {where}
         ORDER BY s.canonical_name LIMIT %s
    """, [*params, limit])

    for r in rows:
        r["id"] = int(r["id"])
        r["linked_verbs"] = int(r["linked_verbs"])
        r["related_subjects"] = int(r["related_subjects"])

    return {"subjects": rows}
```

**Step 1–5:** TDD cycle per endpoint group.

**Commit after each group (list+create, detail+patch+delete, sub-resources).**

---

### Task 10: Verbs Router — /v1/verbs

**Files:**
- Create: `app/routers/verbs.py`
- Create: `tests/test_verbs.py`

Implement:
- `GET /v1/verbs` — list with `linked_subjects` count
- `POST /v1/verbs` — create
- `GET /v1/verbs/{id}` — detail with `subjects[]`
- `PATCH /v1/verbs/{id}` — update
- `DELETE /v1/verbs/{id}` — remove
- `GET /v1/verbs/{id}/subjects` — linked subjects list

Port from: `verbs.php`, `verbs_id.php`, `verbs_id_subjects.php`

---

### Task 11: Type Lists Router — /v1/subject-types, /v1/verb-types, /v1/document-types, /v1/episode-types

**Files:**
- Create: `app/routers/types.py`
- Create: `tests/test_types.py`

Implement:
- `GET /v1/subject-types` — read-only
- `GET /v1/verb-types` — read-only
- `GET /v1/document-types`, `POST`, `PATCH /v1/document-types/{id}`, `DELETE`
- `GET /v1/episode-types`, `POST`, `PATCH /v1/episode-types/{id}`, `DELETE`

Port from: `subject-types.php`, `verb-types.php`, `document-types.php`, `document-types_id.php`, `episode-types.php`, `episode-types_id.php`

---

### Task 12: Projects Router — /v1/projects

**Files:**
- Create: `app/routers/projects.py`
- Create: `tests/test_projects.py`

Implement:
- `GET /v1/projects` — list
- `POST /v1/projects` — create (name, description, classifier_md)
- `GET /v1/projects/{id}` — detail with `subjects[]`, `verbs[]`, `documents[]`
- `PATCH /v1/projects/{id}` — update
- `DELETE /v1/projects/{id}` — remove
- `POST /v1/projects/{id}/archive` — archive (409 if already archived)
- `POST /v1/projects/{id}/unarchive` — unarchive (409 if not archived)
- `POST /v1/projects/{id}/subjects` — link subject (idempotent)
- `PUT /v1/projects/{id}/subjects` — replace full set
- `DELETE /v1/projects/{id}/subjects/{sid}` — unlink
- `POST /v1/projects/{id}/verbs` — link verb
- `PUT /v1/projects/{id}/verbs` — replace full set
- `DELETE /v1/projects/{id}/verbs/{vid}` — unlink

Port from: `projects.php`, `projects_id.php`, `projects_id_archive.php`, `projects_id_unarchive.php`, `projects_id_subjects.php`, `projects_id_subjects_id.php`, `projects_id_verbs.php`, `projects_id_verbs_id.php`

---

### Task 13: Pools Router — /v1/pools

**Files:**
- Create: `app/routers/pools.py`
- Create: `tests/test_pools.py`

Implement:
- `GET /v1/pools` — list (excludes tombstoned)
- `POST /v1/pools` — create
- `GET /v1/pools/{id}` — detail
- `PATCH /v1/pools/{id}` — update name/description
- `POST /v1/pools/{id}/archive` — archive (409 if already archived)
- No DELETE in v1

Port from: `pools.php`, `pools_id.php`, `pools_id_archive.php`

---

### Task 14: Skills Router — /v1/skills

**Files:**
- Create: `app/routers/skills.py`
- Create: `tests/test_skills.py`

Implement:
- `GET /v1/skills` — list with `?visibility=` filter
- `POST /v1/skills` — create
- `GET /v1/skills/{id}` — detail
- `PATCH /v1/skills/{id}` — update
- `DELETE /v1/skills/{id}` — remove
- `POST /v1/skills/{id}/duplicate` — fork via `maludb_skill_fork`

Port from: `skills.php`, `skills_id.php`, `skills_id_duplicate.php`

---

### Task 15: Notes Router — /v1/notes

**Files:**
- Create: `app/routers/notes.py`
- Create: `tests/test_notes.py`

Implement:
- `GET /v1/notes` — list with `?type=`, `?q=`, `?limit=`
- `POST /v1/notes` — create (title, body, type, project_id)
- `GET /v1/notes/{id}` — detail
- `PATCH /v1/notes/{id}` — update
- `DELETE /v1/notes/{id}` — remove
- `POST /v1/notes/{id}/close-issue` — close (409 if not issue/already closed)
- `POST /v1/notes/{id}/reopen-issue` — reopen (409 if not issue/not closed)

Port from: `notes.php`, `notes_id.php`, `notes_id_close-issue.php`, `notes_id_reopen-issue.php`

---

### Task 16: SVPO Statement Helpers

**Files:**
- Create: `app/helpers/statements.py`
- Create: `tests/test_helpers_statements.py`

Port the shared helpers from PHP `response.php`:
- `STATEMENT_COLS` — SELECT column list
- `shape_statement(row)` — cast ints/floats, decode JSON
- `svpor_create_statement(conn, body, force_object=None)` — parse, validate, resolve names, create via `maludb_svpor_statement_create()`

These run inside `db_tx_core()` (search_path set).

---

### Task 17: Episodes Router — /v1/episodes

**Files:**
- Create: `app/routers/episodes.py`
- Create: `tests/test_episodes.py`

Implement:
- `GET /v1/episodes` — list with `?q=`, `?kind=`, `?provenance=`, `?limit=`, `?with=attributes`
- `POST /v1/episodes` — create via `maludb_register_episode()` in `db_tx_core()`
- `GET /v1/episodes/{id}` — assembled event via `maludb_episode_get()`
- `PATCH /v1/episodes/{id}` — update provenance/title/summary/etc
- `DELETE /v1/episodes/{id}` — remove
- `GET /v1/episodes/{id}/statements` — event-scoped statements
- `POST /v1/episodes/{id}/statements` — add link to event (uses `svpor_create_statement`)

Port from: `episodes.php`, `episodes_id.php`, `episodes_id_statements.php`

---

### Task 18: Statements Router — /v1/statements

**Files:**
- Create: `app/routers/statements.py`
- Create: `tests/test_statements.py`

Implement:
- `GET /v1/statements` — list with filters (`provenance`, `object_kind`, `object_id`, `subject_kind`, `subject_id`, `verb_id`, `limit`)
- `POST /v1/statements` — create via `svpor_create_statement()`
- `GET /v1/statements/{id}` — detail
- `PATCH /v1/statements/{id}` — set provenance or close (valid_to)
- `DELETE /v1/statements/{id}` — remove via `maludb_svpor_statement_delete()`

Port from: `statements.php`, `statements_id.php`

---

### Task 19: Typed Attribute Helpers

**Files:**
- Create: `app/helpers/attributes.py`
- Create: `tests/test_helpers_attributes.py`

Port shared helpers:
- `ATTRIBUTE_COLS` — SELECT column list
- `shape_attribute(row)` — cast types, decode JSON
- `svpor_create_attribute(conn, body, force_target=None)` — parse, validate, upsert via `maludb_svpor_attribute_create()`
- `attach_attributes(conn, rows, view, pk_col)` — batch-fetch from `*_with_attributes` view

---

### Task 20: Attributes Router — /v1/attributes, /v1/attribute-templates, /v1/attribute-check

**Files:**
- Create: `app/routers/attributes.py`
- Create: `tests/test_attributes.py`

Implement:
- `GET /v1/attributes` — list with filters
- `POST /v1/attributes` — create/upsert
- `GET /v1/attributes/{id}` — detail
- `PATCH /v1/attributes/{id}` — set provenance
- `DELETE /v1/attributes/{id}` — remove
- `GET /v1/attribute-templates` — catalog with `?applies_to=`, `?type_value=`
- `POST /v1/attribute-templates` — create
- `GET /v1/attribute-templates/{id}` — detail
- `DELETE /v1/attribute-templates/{id}` — remove
- `GET /v1/attribute-check` — advisory completeness check

Port from: `attributes.php`, `attributes_id.php`, `attribute-templates.php`, `attribute-templates_id.php`, `attribute-check.php`

---

### Task 21: Document Graph Helpers

**Files:**
- Create: `app/helpers/documents.py`
- Create: `tests/test_helpers_documents.py`

Port shared helpers:
- `document_link_spec(tag_kind)` — map project/subject/stakeholder to [subject_type, verb]
- `document_link_subject(conn, document_id, tag_kind, name, provenance)` — resolve-or-create subject, create edge, upsert soft tag
- `document_unlink_subject(conn, document_id, tag_kind, name, provenance)` — delete edge, delete tag, repoint primary_project_id
- `document_neighbors(conn, subject_id)` — fetch linked documents

---

### Task 22: Documents Router — /v1/documents

**Files:**
- Create: `app/routers/documents.py`
- Create: `tests/test_documents.py`

Implement:
- `GET /v1/documents` — list with `?q=`, `?limit=`, `?with=attributes`
- `POST /v1/documents` — multipart file upload (file, filename, mime_type, description, document_type, projects, subjects)
- `GET /v1/documents/{id}` — metadata + tags[]
- `PATCH /v1/documents/{id}` — link/unlink projects & subjects
- `DELETE /v1/documents/{id}` — remove + graph edges
- `POST /v1/documents-backfill` — graph backfill

Port from: `documents.php`, `documents_id.php`, `documents-backfill.php`

Note: File upload uses FastAPI's `UploadFile` + `Form()` parameters. Binary bytes are stored via `psycopg` LOB binding.

---

### Task 23: Objects Router — /v1/objects/{kind}

**Files:**
- Create: `app/routers/objects.py`
- Create: `tests/test_objects.py`

Implement:
- `POST /v1/objects/{kind}` — atomic create (subject or episode_object) + attributes in one transaction
- `GET /v1/objects/{kind}/{id}` — object + attributes + statements/details

Port from: `objects.php`, `objects_id.php`

---

### Task 24: Graph Router — /v1/edges, /v1/graph/neighbors, /v1/graph/walk

**Files:**
- Create: `app/routers/graph.py`
- Create: `tests/test_graph.py`

Implement:
- `GET /v1/edges` — unified edge view with filters
- `GET /v1/graph/neighbors` — one-hop neighbors
- `GET /v1/graph/walk` — multi-hop BFS via `maludb_graph_walk()`

Port from: `edges.php`, `graph_neighbors.php`, `graph_walk.php`

---

### Task 25: LLM Helper Module

**Files:**
- Create: `app/helpers/llm.py`
- Create: `tests/test_helpers_llm.py`
- Copy: `config/prompts/chatgpt-4o.system.txt` from PHP source

Port the centralized LLM layer from PHP `config/llm.php`:
- `mem_embed(text, cfg)` — real HTTP or deterministic sha256 fallback
- `mem_embed_deterministic(text)` — repeatable hash-seeded unit vector
- `mem_chunk(text, max_chars, overlap)` — paragraph/sentence boundary chunking
- `llm_complete(cfg, system, user)` — provider-agnostic dispatch (OpenAI or Anthropic format)
- `llm_extract_json(text, cfg)` — run extraction prompt, return decoded JSON
- `mem_extract(chunk, cfg)` — extract SVPO candidate edges
- `mem_vector_literal(floats)` — format as `[0.1,-0.2,...]` for SQL
- `mem_resolve_token(conn, secret_ref)` — resolve DB secret or env fallback

Use `httpx` for outbound HTTP (replaces PHP cURL).

---

### Task 26: Memory Router — /v1/memory/config, /v1/memory/documents, /v1/memory/search, /v1/memory/ingest

**Files:**
- Create: `app/routers/memory.py`
- Create: `tests/test_memory.py`

Implement:
- `GET /v1/memory/config?namespace=` — read model config
- `POST /v1/memory/config` — full config setup (secret_set → register provider → alias → set_model_config)
- `PUT /v1/memory/config` — same as POST
- `POST /v1/memory/documents` — upload → chunk → extract → embed → ingest
- `POST /v1/memory/search` — embed query → `maludb_memory_search()`
- `POST /v1/memory/ingest` — text → LLM extraction → ingest (loads prompt from SQLite `model_prompts`)

Port from: `memory_config.php`, `memory_documents.php`, `memory_search.php`, `memory_ingest.php`

---

### Task 27: Model Prompts Router — /v1/model-prompts

**Files:**
- Create: `app/routers/model_prompts.py`
- Create: `tests/test_model_prompts.py`

Implement:
- `GET /v1/model-prompts` — list (api_key never returned, only `api_key_set` flag)
- `POST /v1/model-prompts` — upsert (authorized by Postgres login, not bearer token)

Port from: `model-prompts.php`

---

### Task 28: Mount All Routers + Final main.py

**Files:**
- Modify: `app/main.py` (mount all routers, add lifespan handler)

Wire everything together:

```python
from app.routers import subjects, verbs, types, projects, pools, skills, notes
from app.routers import episodes, statements, attributes, objects
from app.routers import documents, graph, memory, tokens, model_prompts

app.include_router(subjects.router)
app.include_router(verbs.router)
# ... all routers
```

Add lifespan handler for SQLite auth store initialization.

---

### Task 29: Integration Tests with curl Scripts

**Files:**
- Create: `tests/curl/` directory with .sh scripts mirroring PHP test suite

Port the PHP `tests/*.sh` curl scripts to work against the FastAPI server. These are the same curl commands from the PHP project (pointing at `http://localhost:8000` instead of `https://fastapi.maludb.org`). They serve as both integration tests and learning examples.

---

### Task 30: Update README.md and CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

Update documentation to reflect the completed project: installation, running, testing, architecture, and the mapping from the PHP original.

---

### Task 31: Final Review and Cleanup

- Verify all 59 PHP endpoints have corresponding FastAPI routes
- Run `ruff check` and `ruff format`
- Run full test suite
- Verify curl test scripts pass against a live maludb_core 0.96.0 database
- Commit and tag as v0.1.0

---

## Endpoint Mapping Reference

| PHP File | FastAPI Router | Route |
|----------|---------------|-------|
| `subjects.php` | `routers/subjects.py` | `GET/POST /v1/subjects` |
| `subjects_id.php` | `routers/subjects.py` | `GET/PATCH/DELETE /v1/subjects/{id}` |
| `subjects_id_verbs.php` | `routers/subjects.py` | `GET/POST /v1/subjects/{id}/verbs` |
| `subjects_id_verbs_id.php` | `routers/subjects.py` | `DELETE /v1/subjects/{id}/verbs/{verb_id}` |
| `subjects_id_related-subjects.php` | `routers/subjects.py` | `GET/POST /v1/subjects/{id}/related-subjects` |
| `subjects_id_related-subjects_id.php` | `routers/subjects.py` | `DELETE /v1/subjects/{id}/related-subjects/{other_id}` |
| `subject-relationships_id.php` | `routers/subjects.py` | `GET/PATCH/DELETE /v1/subject-relationships/{rel_id}` |
| `verbs.php` | `routers/verbs.py` | `GET/POST /v1/verbs` |
| `verbs_id.php` | `routers/verbs.py` | `GET/PATCH/DELETE /v1/verbs/{id}` |
| `verbs_id_subjects.php` | `routers/verbs.py` | `GET /v1/verbs/{id}/subjects` |
| `subject-types.php` | `routers/types.py` | `GET /v1/subject-types` |
| `verb-types.php` | `routers/types.py` | `GET /v1/verb-types` |
| `document-types.php` | `routers/types.py` | `GET/POST /v1/document-types` |
| `document-types_id.php` | `routers/types.py` | `PATCH/DELETE /v1/document-types/{id}` |
| `episode-types.php` | `routers/types.py` | `GET/POST /v1/episode-types` |
| `episode-types_id.php` | `routers/types.py` | `PATCH/DELETE /v1/episode-types/{id}` |
| `projects.php` | `routers/projects.py` | `GET/POST /v1/projects` |
| `projects_id.php` | `routers/projects.py` | `GET/PATCH/DELETE /v1/projects/{id}` |
| `projects_id_archive.php` | `routers/projects.py` | `POST /v1/projects/{id}/archive` |
| `projects_id_unarchive.php` | `routers/projects.py` | `POST /v1/projects/{id}/unarchive` |
| `projects_id_subjects.php` | `routers/projects.py` | `POST/PUT /v1/projects/{id}/subjects` |
| `projects_id_subjects_id.php` | `routers/projects.py` | `DELETE /v1/projects/{id}/subjects/{sid}` |
| `projects_id_verbs.php` | `routers/projects.py` | `POST/PUT /v1/projects/{id}/verbs` |
| `projects_id_verbs_id.php` | `routers/projects.py` | `DELETE /v1/projects/{id}/verbs/{vid}` |
| `pools.php` | `routers/pools.py` | `GET/POST /v1/pools` |
| `pools_id.php` | `routers/pools.py` | `GET/PATCH /v1/pools/{id}` |
| `pools_id_archive.php` | `routers/pools.py` | `POST /v1/pools/{id}/archive` |
| `skills.php` | `routers/skills.py` | `GET/POST /v1/skills` |
| `skills_id.php` | `routers/skills.py` | `GET/PATCH/DELETE /v1/skills/{id}` |
| `skills_id_duplicate.php` | `routers/skills.py` | `POST /v1/skills/{id}/duplicate` |
| `notes.php` | `routers/notes.py` | `GET/POST /v1/notes` |
| `notes_id.php` | `routers/notes.py` | `GET/PATCH/DELETE /v1/notes/{id}` |
| `notes_id_close-issue.php` | `routers/notes.py` | `POST /v1/notes/{id}/close-issue` |
| `notes_id_reopen-issue.php` | `routers/notes.py` | `POST /v1/notes/{id}/reopen-issue` |
| `episodes.php` | `routers/episodes.py` | `GET/POST /v1/episodes` |
| `episodes_id.php` | `routers/episodes.py` | `GET/PATCH/DELETE /v1/episodes/{id}` |
| `episodes_id_statements.php` | `routers/episodes.py` | `GET/POST /v1/episodes/{id}/statements` |
| `statements.php` | `routers/statements.py` | `GET/POST /v1/statements` |
| `statements_id.php` | `routers/statements.py` | `GET/PATCH/DELETE /v1/statements/{id}` |
| `documents.php` | `routers/documents.py` | `GET/POST /v1/documents` |
| `documents_id.php` | `routers/documents.py` | `GET/PATCH/DELETE /v1/documents/{id}` |
| `documents-backfill.php` | `routers/documents.py` | `POST /v1/documents-backfill` |
| `attributes.php` | `routers/attributes.py` | `GET/POST /v1/attributes` |
| `attributes_id.php` | `routers/attributes.py` | `GET/PATCH/DELETE /v1/attributes/{id}` |
| `attribute-templates.php` | `routers/attributes.py` | `GET/POST /v1/attribute-templates` |
| `attribute-templates_id.php` | `routers/attributes.py` | `GET/DELETE /v1/attribute-templates/{id}` |
| `attribute-check.php` | `routers/attributes.py` | `GET /v1/attribute-check` |
| `objects.php` | `routers/objects.py` | `POST /v1/objects/{kind}` |
| `objects_id.php` | `routers/objects.py` | `GET /v1/objects/{kind}/{id}` |
| `edges.php` | `routers/graph.py` | `GET /v1/edges` |
| `graph_neighbors.php` | `routers/graph.py` | `GET /v1/graph/neighbors` |
| `graph_walk.php` | `routers/graph.py` | `GET /v1/graph/walk` |
| `memory_config.php` | `routers/memory.py` | `GET/POST/PUT /v1/memory/config` |
| `memory_documents.php` | `routers/memory.py` | `POST /v1/memory/documents` |
| `memory_search.php` | `routers/memory.py` | `POST /v1/memory/search` |
| `memory_ingest.php` | `routers/memory.py` | `POST /v1/memory/ingest` |
| `tokens.php` | `routers/tokens.py` | `GET/POST /v1/tokens` |
| `tokens_id.php` | `routers/tokens.py` | `DELETE /v1/tokens/{id}` |
| `model-prompts.php` | `routers/model_prompts.py` | `GET/POST /v1/model-prompts` |
