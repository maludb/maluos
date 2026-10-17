"""
Token management endpoints — self-service token issuance, listing, and revocation.

Ports PHP's /v1/tokens (tokens.php) and /v1/tokens/{id} (tokens_id.php).

These endpoints do NOT use require_auth() — authorization is by Postgres login proof:
the caller supplies pg_dbname/pg_user/pg_password, and we verify them by connecting
to Postgres before performing any operation.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import get_auth_store
from app.database import test_credentials
from app.errors import json_error
from app.store_crypto import seal

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper — validate + verify the Postgres credential triple from the body
# ---------------------------------------------------------------------------


def _tokens_authorize(body: dict) -> tuple[str, str, str]:
    """Extract and verify pg_dbname/pg_user/pg_password from the request body.

    Returns (dbname, user, password) on success; raises APIError otherwise.
    Mirrors PHP's tokens_authorize().
    """
    db = (body.get("pg_dbname") or "").strip() if isinstance(body.get("pg_dbname"), str) else ""
    user = (body.get("pg_user") or "").strip() if isinstance(body.get("pg_user"), str) else ""
    # pg_password: allow empty-ish strings but key must be present
    password = str(body["pg_password"]) if "pg_password" in body else ""

    if not db or not user or not password:
        json_error("missing_field", "pg_dbname, pg_user and pg_password are required.", 400)

    if not test_credentials(db, user, password):
        json_error("pg_auth_failed", "Could not connect to Postgres with the supplied credentials.", 403)

    return db, user, password


# ---------------------------------------------------------------------------
# POST /v1/tokens — mint a new API token
# ---------------------------------------------------------------------------


@router.post("/v1/tokens")
async def create_token(request: Request) -> JSONResponse:
    body = await request.json()
    db, user, password = _tokens_authorize(body)

    # Optional fields
    role = body.get("role") or "executor"
    if isinstance(role, str):
        role = role.strip() or "executor"
    else:
        role = "executor"

    device_name = body.get("device_name") or None
    if isinstance(device_name, str):
        device_name = device_name.strip() or None

    store = get_auth_store()

    # user_id: use supplied integer or auto-assign
    user_id = body.get("user_id")
    if not isinstance(user_id, int):
        user_id = store.next_user_id()

    # expires_at
    expires_at = None
    expires_in_days = body.get("expires_in_days")
    if expires_in_days is not None:
        if not isinstance(expires_in_days, int) or expires_in_days <= 0:
            json_error("validation_failed", '"expires_in_days" must be a positive integer.', 422)
        expires_at = (datetime.now(UTC) + timedelta(days=expires_in_days)).strftime("%Y-%m-%d %H:%M:%S")

    # Generate the token: malu_<base64url(32 random bytes)>
    raw_bytes = secrets.token_bytes(32)
    raw = base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")
    token = "malu_" + raw
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:8]

    # Insert into SQLite
    conn = store.connection
    cursor = conn.execute(
        """
        INSERT INTO users
            (token_hash, token_prefix, user_id, role,
             pg_dbname, pg_user, pg_password, expires_at, device_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (token_hash, prefix, user_id, role, db, user, seal(password), expires_at, device_name),
    )
    conn.commit()
    row_id = cursor.lastrowid

    return JSONResponse(
        status_code=201,
        content={
            "token": token,
            "id": row_id,
            "user_id": user_id,
            "role": role,
            "pg_dbname": db,
            "pg_user": user,
            "expires_at": expires_at,
            "device_name": device_name,
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/tokens — list tokens for a connection
# ---------------------------------------------------------------------------


@router.get("/v1/tokens")
async def list_tokens(request: Request) -> JSONResponse:
    body = await request.json()
    db, user, _password = _tokens_authorize(body)

    store = get_auth_store()
    cursor = store.connection.execute(
        """
        SELECT id, token_prefix, user_id, role, pg_dbname, pg_user, expires_at, device_name, created_at
          FROM users
         WHERE pg_dbname = ? AND pg_user = ?
         ORDER BY id
        """,
        (db, user),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    # Ensure integer types (SQLite Row returns int already, but be explicit)
    for r in rows:
        r["id"] = int(r["id"])
        r["user_id"] = int(r["user_id"])

    return JSONResponse(content={"tokens": rows})


# ---------------------------------------------------------------------------
# DELETE /v1/tokens/{id} — revoke a token
# ---------------------------------------------------------------------------


@router.delete("/v1/tokens/{token_id}")
async def delete_token(token_id: int, request: Request) -> JSONResponse:
    body = await request.json()
    db, user, _password = _tokens_authorize(body)

    store = get_auth_store()
    cursor = store.connection.execute(
        "SELECT pg_dbname, pg_user FROM users WHERE id = ?",
        (token_id,),
    )
    found = cursor.fetchone()
    if found is None:
        json_error("not_found", "Token not found.", 404)

    # Only allow revoking a token that belongs to the connection the caller authenticated with
    if found["pg_dbname"] != db or found["pg_user"] != user:
        json_error("forbidden", "This token does not belong to the supplied Postgres connection.", 403)

    store.connection.execute("DELETE FROM users WHERE id = ?", (token_id,))
    store.connection.commit()

    return JSONResponse(content={"deleted": True, "id": token_id})
