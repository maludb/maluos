"""
Authentication dependency — Bearer token → tenant Postgres connection.

Ports PHP's require_auth() from config/response.php as a FastAPI dependency
(generator form so the Postgres connection is closed in the finally block).

Usage in route handlers::

    @router.get("/v1/example")
    def example(auth: Auth):
        rows = db_query(auth.conn, "SELECT ...")
        return rows
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated

import psycopg
from fastapi import Depends, Request

from app import config
from app.auth_store import AuthStore
from app.database import TenantConnection
from app.errors import json_error
from app.principal import apply_principal
from app.sql_log import get_tracer

# ---------------------------------------------------------------------------
# AuthStore singleton
# ---------------------------------------------------------------------------

_auth_store: AuthStore | None = None


def get_auth_store() -> AuthStore:
    """Return (and lazily create) the process-wide AuthStore singleton."""
    global _auth_store  # noqa: PLW0603
    if _auth_store is None:
        _auth_store = AuthStore(config.AUTH_STORE_PATH)
        _auth_store.init_db()
    return _auth_store


# ---------------------------------------------------------------------------
# AuthContext — what a route handler receives from require_auth
# ---------------------------------------------------------------------------

@dataclass
class AuthContext:
    """Per-request auth context holding the user identity and Postgres connection."""
    user_id: int
    role: str
    conn: psycopg.Connection


# ---------------------------------------------------------------------------
# FastAPI dependency (generator — cleans up the connection on exit)
# ---------------------------------------------------------------------------

def authenticate_bearer(auth_header: str | None) -> AuthContext:
    """Resolve an ``Authorization`` header value to an AuthContext.

    Mirrors PHP's require_auth():
      1. Extract ``Authorization: Bearer <token>``
      2. Validate ``malu_`` prefix
      3. sha256 hash the token body (after the prefix)
      4. SQLite lookup via AuthStore.resolve_token
      5. TenantConnection.connect() with resolved creds
      6. Set tracer.user_id

    Raises APIError(401) on any auth failure.  The caller owns the returned
    context's Postgres connection and must close it when done.  Used by the
    require_auth dependency and the MCP endpoint.
    """
    # 1. Extract Authorization header
    if not auth_header:
        json_error("auth_missing", "Authorization: Bearer token required.", 401)

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        json_error("auth_missing", "Authorization: Bearer token required.", 401)

    token = parts[1]

    # 2. Validate malu_ prefix
    if not token.startswith("malu_"):
        json_error("auth_invalid", "Malformed API token.", 401)

    # 3. sha256 hash the token body
    token_body = token[len("malu_"):]
    token_hash = hashlib.sha256(token_body.encode()).hexdigest()

    # 4. SQLite lookup
    store = get_auth_store()
    row = store.resolve_token(token_hash)
    if row is None:
        json_error("auth_invalid", "Invalid or expired API token.", 401)

    # 5. Connect to tenant Postgres
    tc = TenantConnection(
        dbname=row["pg_dbname"],
        user=row["pg_user"],
        password=row["pg_password"],
    )
    conn = tc.connect()

    # 6. Set tracer user_id
    tracer = get_tracer()
    tracer.user_id = row["user_id"]

    return AuthContext(user_id=row["user_id"], role=row["role"], conn=conn)


async def require_auth(request: Request):  # noqa: ANN201 — generator dependency
    """FastAPI dependency: authenticate, yield the context, close the connection."""
    ctx = authenticate_bearer(request.headers.get("authorization"))
    try:
        # 0.106.0: bind the connection to the principal the host names, if any (app/principal.py).
        apply_principal(ctx.conn, request.headers)
        yield ctx
    finally:
        try:
            ctx.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Type alias for route parameter injection
# ---------------------------------------------------------------------------

Auth = Annotated[AuthContext, Depends(require_auth)]
