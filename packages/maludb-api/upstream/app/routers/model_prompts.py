"""
Model prompts endpoints — manage per-model extraction prompts in SQLite.

Ports PHP's model-prompts.php.

    GET  /v1/model-prompts  — list configured model prompts (api_key never returned)
    POST /v1/model-prompts  — upsert a model's prompt + LLM connection

Authorization is the Postgres login (same as /v1/tokens): supply
pg_dbname/pg_user/pg_password and we verify by connecting.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from app.auth import get_auth_store
from app.database import test_credentials
from app.errors import json_error
from app.store_crypto import seal

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper — authorize via Postgres login
# ---------------------------------------------------------------------------


def _model_prompts_authorize(body: dict) -> None:
    """Verify the Postgres login supplied in the request body."""
    db = str(body.get("pg_dbname", "")).strip() if isinstance(body.get("pg_dbname"), str) else ""
    user = str(body.get("pg_user", "")).strip() if isinstance(body.get("pg_user"), str) else ""
    password = str(body["pg_password"]) if "pg_password" in body else ""

    if not db or not user or not password:
        json_error("missing_field", "pg_dbname, pg_user and pg_password are required.", 400)

    if not test_credentials(db, user, password):
        json_error("pg_auth_failed", "Could not connect to Postgres with the supplied credentials.", 403)


# ---------------------------------------------------------------------------
# POST /v1/model-prompts — upsert
# ---------------------------------------------------------------------------


@router.post("/v1/model-prompts")
async def upsert_model_prompt(request: Request):
    body = await request.json()
    _model_prompts_authorize(body)

    model_name = str(body.get("model_name", "")).strip()
    api_format = str(body.get("api_format", "")).strip().lower()
    system_prompt = str(body.get("system_prompt", ""))
    base_url = str(body.get("base_url", "")).strip()
    api_key = str(body["api_key"]) if body.get("api_key") not in (None, "") else None
    _mt = body.get("max_tokens")
    max_tokens = int(_mt) if isinstance(_mt, int) and _mt > 0 else 2048
    _mi = body.get("model_identifier")
    model_identifier = str(_mi).strip() if _mi and str(_mi).strip() else None
    _gp = body.get("generation_params")
    generation_params = json.dumps(_gp) if isinstance(_gp, dict) else None

    if not model_name:
        json_error("missing_field", '"model_name" is required.', 400)
    if not system_prompt:
        json_error("missing_field", '"system_prompt" is required.', 400)
    if not base_url:
        json_error("missing_field", '"base_url" is required.', 400)
    if api_format not in ("openai", "anthropic"):
        json_error("validation_failed", '"api_format" must be "openai" or "anthropic".', 422)

    store = get_auth_store()
    conn = store.connection

    # Upsert — SQLite uses INSERT OR REPLACE (the table has model_name as PK).
    # To preserve api_key on update when not supplied, we read the existing row first.
    existing = store.model_prompt(model_name)
    effective_api_key = api_key if api_key is not None else (existing["api_key"] if existing else None)

    conn.execute(
        """INSERT OR REPLACE INTO model_prompts
               (model_name, model_identifier, api_format, system_prompt, base_url, api_key,
                max_tokens, generation_params, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
        (model_name, model_identifier, api_format, system_prompt, base_url,
         seal(effective_api_key), max_tokens, generation_params),
    )
    conn.commit()

    pr = store.model_prompt(model_name)
    return {
        "model_prompt": {
            "model_name": pr["model_name"],
            "api_format": pr["api_format"],
            "base_url": pr["base_url"],
            "max_tokens": int(pr["max_tokens"]) if pr["max_tokens"] is not None else 2048,
            "api_key_set": pr.get("api_key") is not None and pr["api_key"] != "",
            "system_prompt": pr["system_prompt"],
        },
    }


# ---------------------------------------------------------------------------
# GET /v1/model-prompts — list
# ---------------------------------------------------------------------------


@router.get("/v1/model-prompts")
async def list_model_prompts(request: Request):
    body = await request.json()
    _model_prompts_authorize(body)

    store = get_auth_store()
    cursor = store.connection.execute(
        """SELECT model_name, model_identifier, api_format, base_url, max_tokens,
                  (api_key IS NOT NULL AND api_key <> '') AS api_key_set,
                  updated_at, system_prompt
             FROM model_prompts ORDER BY model_name"""
    )
    rows = [dict(r) for r in cursor.fetchall()]
    for r in rows:
        r["max_tokens"] = int(r["max_tokens"]) if r["max_tokens"] is not None else 2048
        r["api_key_set"] = bool(r["api_key_set"])
    return {"model_prompts": rows}
