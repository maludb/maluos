"""
Tenant PostgreSQL connection and query helpers.

Ports PHP's Database class and the db_query / db_exec / db_one / db_tx_core
wrappers from config/response.php.  Uses psycopg v3 (NOT psycopg2).

Every query helper logs through the per-request SqlTracer so that ?debug=1
responses and the persistent sql.log stay in sync.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row

from app import config
from app.sql_log import get_tracer

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# TenantDatabaseError — connection-level failure
# ---------------------------------------------------------------------------

class TenantDatabaseError(Exception):
    """Raised when the per-tenant Postgres connection fails.

    Carries a flag distinguishing rejected credentials (→ 502) from an
    unreachable server (→ 503).  Mirrors PHP's TenantDatabaseException.
    """

    def __init__(self, message: str, is_auth_failure: bool = False) -> None:
        super().__init__(message)
        self.is_auth_failure = is_auth_failure


# ---------------------------------------------------------------------------
# TenantConnection — per-request Postgres connection
# ---------------------------------------------------------------------------

class TenantConnection:
    """Wraps psycopg.connect() with the resolved tenant credentials.

    Created by require_auth() after the SQLite lookup; the middleware closes
    the connection when the response is done.
    """

    def __init__(
        self,
        dbname: str,
        user: str,
        password: str,
        host: str = config.PG_HOST,
        port: int = config.PG_PORT,
    ) -> None:
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port

    def connect(self) -> psycopg.Connection:
        """Open a psycopg connection with dict_row factory.

        Raises TenantDatabaseError on failure, classifying auth vs. unreachable.
        """
        try:
            conn = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                row_factory=dict_row,
                autocommit=True,
                connect_timeout=5,
            )
            # The per-tenant facade views (maludb_subject, maludb_verb, …) live in
            # the tenant's own schema, which is named after the connecting role.
            # The cluster/database default search_path does not include "$user", so
            # without this those relations don't resolve (→ UndefinedTable → 500).
            # SET LOCAL in db_tx_core() still layers maludb_core on top per-transaction.
            with conn.cursor() as cur:
                cur.execute('SET search_path TO "$user", maludb_core, public')
            return conn
        except psycopg.OperationalError as exc:
            msg = str(exc)
            is_auth = "authentication failed" in msg.lower() or "password" in msg.lower()
            raise TenantDatabaseError("Tenant database connection failed.", is_auth_failure=is_auth) from exc


# ---------------------------------------------------------------------------
# Query helpers — thin wrappers that log through the SqlTracer
# ---------------------------------------------------------------------------

def db_query(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> list[dict]:
    """Execute a SELECT and return all rows as dicts.  Mirrors PHP's db_query()."""
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    dur_ms = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, params, len(rows), dur_ms)
    return rows


def db_exec(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> int:
    """Execute a write statement and return the affected row count.  Mirrors PHP's db_exec()."""
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        n = cur.rowcount
    dur_ms = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, params, n, dur_ms)
    return n


def db_one(conn: psycopg.Connection, sql: str, params: list | tuple = ()) -> dict[str, Any] | None:
    """Execute a query and return the first row (or None).  Mirrors PHP's db_one()."""
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    dur_ms = (time.perf_counter() - t0) * 1000
    get_tracer().log(sql, params, 1 if row else 0, dur_ms)
    return row


def db_tx_core(conn: psycopg.Connection, fn: Callable[[psycopg.Connection], Any]) -> Any:
    """Run *fn* inside a transaction with the core facades on the search_path.

    The per-tenant facade views and functions (maludb_memory_model_config,
    maludb_upload_document, …) live in the tenant's own schema, which is named
    after the connecting role — so ``"$user"`` must lead the search_path or the
    unqualified facade calls fail with UndefinedFunction/UndefinedTable. The
    maludb_core schema follows so those facades resolve their own base objects.

    ``SET LOCAL`` keeps the change scoped to the transaction.  The callback
    receives the connection; db_query / db_one / db_exec can use the same
    connection inside it.  On any exception we roll back and re-raise (the
    global handler maps DB SQLSTATEs to 409/422/500).
    """
    # psycopg v3: use conn.transaction() context manager
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute('SET LOCAL search_path TO "$user", maludb_core, public')
        return fn(conn)


# ---------------------------------------------------------------------------
# Credential test — used by the token-issuing endpoint
# ---------------------------------------------------------------------------

def test_credentials(
    dbname: str,
    user: str,
    password: str,
    host: str = config.PG_HOST,
    port: int = config.PG_PORT,
) -> bool:
    """Verify Postgres credentials by attempting a connection.  Returns True on success."""
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False
