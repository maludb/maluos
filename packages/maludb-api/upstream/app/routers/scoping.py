"""
Principals, scopes, forgetting, skill review and pool presence — the maludb_core 0.106.0 surface.

    GET    /v1/whoami                                      what this request is allowed (principal, scopes, ceiling)
    GET    /v1/principals                                  the principals the engine knows
    PUT    /v1/principals/{ref}                            {kind?, display_name?, home_scope?, max_sensitivity?,
                                                            enabled?}
    GET    /v1/principals/{ref}/scopes
    PUT    /v1/principals/{ref}/scopes/{scope}             {"access_level": "read" | "write"}
    DELETE /v1/principals/{ref}/scopes/{scope}
    PUT    /v1/scope                                       {"kind", "id", "scope"} — move a row into a scope
    DELETE /v1/memory/chunks/{chunk_id}                    forget one vector chunk

    POST   /v1/skills/{id}/review                          {"decision": approved|rejected|proposed, "reviewer"?,
                                                            "note"?}
    PUT    /v1/skills/{id}/principals/{ref}                reserve a skill for a principal
    DELETE /v1/skills/{id}/principals/{ref}
    POST   /v1/skills/{id}/loads                           {"run_ref"?, "principal_ref"?, "metadata"?}
    GET    /v1/skills/{id}/loads

    GET    /v1/pools/{id}/presence[?include_left=true]     who is there, doing what, cursor and TTL
    POST   /v1/pools/{id}/presence                         join / heartbeat / move the cursor
    DELETE /v1/pools/{id}/presence                         leave

The rules live in the engine, not here: a request bound to a principal (X-MaluDB-Principal, see
app/principal.py) is refused by Postgres when it administers principals, reviews its own proposal,
joins a pool outside its scopes or moves a row into a scope it cannot write — SQLSTATE 42501, which
the global handler already answers as 403. These routes only shape arguments and results.

Every route needs the 0.106.0 facades; against an older tenant they answer 501 and say what to do.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error
from app.principal import REF, SCOPE, principal_enforced

router = APIRouter()

KINDS = ("human", "agent", "service")
SENSITIVITIES = ("public", "internal", "restricted", "prohibited")
SCOPED_KINDS = ("document", "source_package", "memory", "episode", "chat_session", "pool")


def _need_engine(auth) -> None:
    if not principal_enforced(auth.conn):
        json_error(
            "engine_too_old",
            "This route needs maludb_core 0.106.0: upgrade the extension, then re-run"
            " enable_memory_schema('<tenant>').",
            501,
        )


def _ref(ref: str) -> str:
    if not REF.match(ref or ""):
        json_error("invalid_principal", "Not a principal reference.", 400)
    return ref


def _scope(scope: str) -> str:
    scope = (scope or "").strip()
    if not SCOPE.match(scope):
        json_error("invalid_scope", "Not a scope name.", 400)
    return scope


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        json_error("invalid_json", "Request body is not JSON.", 400)
    if not isinstance(body, dict):
        json_error("invalid_json", "Request body must be a JSON object.", 400)
    return body


# ===========================================================================
# whoami, principals, scopes
# ===========================================================================


@router.get("/v1/whoami")
def whoami(auth: Auth):
    if not principal_enforced(auth.conn):
        return {"restricted": False, "engine_enforces_principals": False}
    row = db_tx_core(auth.conn, lambda c: db_one(c, "SELECT maludb_principal_whoami() AS me"))
    return {**_json(row["me"]), "engine_enforces_principals": True}


@router.get("/v1/principals")
def list_principals(auth: Auth):
    _need_engine(auth)
    rows = db_query(
        auth.conn,
        """SELECT principal_ref AS ref, principal_kind AS kind, display_name, home_scope, max_sensitivity,
                  enabled, created_at::text AS created_at, updated_at::text AS updated_at
             FROM maludb_principal ORDER BY principal_ref""",
    )
    return {"principals": rows}


@router.put("/v1/principals/{ref}")
async def upsert_principal(auth: Auth, ref: str, request: Request):
    _need_engine(auth)
    body = await _body(request)
    kind = body.get("kind")
    if kind is not None and kind not in KINDS:
        json_error("invalid_field", f"kind must be one of {', '.join(KINDS)}.", 422)
    ceiling = body.get("max_sensitivity")
    if ceiling is not None and ceiling not in SENSITIVITIES:
        json_error("invalid_field", f"max_sensitivity must be one of {', '.join(SENSITIVITIES)}.", 422)
    enabled = body.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        json_error("invalid_field", "enabled must be true or false.", 422)
    home = body.get("home_scope")
    db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            """SELECT maludb_principal_upsert(p_principal_ref => %s, p_principal_kind => %s, p_display_name => %s,
                          p_home_scope => %s, p_max_sensitivity => %s, p_enabled => %s) AS id""",
            [_ref(ref), kind, body.get("display_name"), _scope(home) if home else None, ceiling, enabled],
        ),
    )
    row = db_one(
        auth.conn,
        """SELECT principal_ref AS ref, principal_kind AS kind, display_name, home_scope, max_sensitivity, enabled
             FROM maludb_principal WHERE principal_ref = %s""",
        [ref],
    )
    return {"principal": row}


@router.get("/v1/principals/{ref}/scopes")
def list_scopes(auth: Auth, ref: str, include_revoked: bool = False):
    _need_engine(auth)
    rows = db_query(
        auth.conn,
        """SELECT scope, access_level, granted_at::text AS granted_at, revoked_at::text AS revoked_at
             FROM maludb_principal_scope
            WHERE principal_ref = %s AND (%s OR revoked_at IS NULL)
            ORDER BY scope, granted_at""",
        [_ref(ref), include_revoked],
    )
    return {"principal": ref, "scopes": rows}


@router.put("/v1/principals/{ref}/scopes/{scope:path}")
async def grant_scope(auth: Auth, ref: str, scope: str, request: Request):
    _need_engine(auth)
    body = await _body(request)
    level = str(body.get("access_level") or "read").lower()
    if level not in ("read", "write"):
        json_error("invalid_field", "access_level must be read or write.", 422)
    db_tx_core(
        auth.conn,
        lambda c: db_one(c, "SELECT maludb_principal_grant_scope(%s, %s, %s) AS id", [_ref(ref), _scope(scope), level]),
    )
    return {"principal": ref, "scope": scope, "access_level": level}


@router.delete("/v1/principals/{ref}/scopes/{scope:path}")
def revoke_scope(auth: Auth, ref: str, scope: str):
    _need_engine(auth)
    row = db_tx_core(
        auth.conn, lambda c: db_one(c, "SELECT maludb_principal_revoke_scope(%s, %s) AS ok", [_ref(ref), _scope(scope)])
    )
    if not row["ok"]:
        json_error("not_found", "That principal holds no live grant on that scope.", 404)
    return {"revoked": True, "principal": ref, "scope": scope}


@router.put("/v1/scope")
async def set_scope(auth: Auth, request: Request):
    _need_engine(auth)
    body = await _body(request)
    kind = str(body.get("kind") or "").strip().lower()
    if kind not in SCOPED_KINDS:
        json_error("invalid_field", f"kind must be one of {', '.join(SCOPED_KINDS)}.", 422)
    try:
        object_id = int(body.get("id"))
    except (TypeError, ValueError):
        json_error("invalid_field", "id must be an integer.", 422)
    scope = _scope(str(body.get("scope") or ""))
    row = db_tx_core(
        auth.conn, lambda c: db_one(c, "SELECT maludb_set_scope(%s, %s, %s) AS ok", [kind, object_id, scope])
    )
    if not row["ok"]:
        json_error("not_found", f"No {kind} {object_id}.", 404)
    return {"kind": kind, "id": object_id, "scope": scope}


@router.delete("/v1/memory/chunks/{chunk_id}")
def forget_chunk(auth: Auth, chunk_id: int):
    _need_engine(auth)
    row = db_tx_core(auth.conn, lambda c: db_one(c, "SELECT maludb_forget_chunk(%s) AS ok", [chunk_id]))
    if not row["ok"]:
        json_error("not_found", "Chunk not found.", 404)
    return {"deleted": True, "id": chunk_id}


# ===========================================================================
# skills: review, principal grants, loads
# ===========================================================================


@router.post("/v1/skills/{skill_id}/review")
async def review_skill(auth: Auth, skill_id: int, request: Request):
    _need_engine(auth)
    body = await _body(request)
    decision = str(body.get("decision") or "").strip().lower()
    if decision not in ("approved", "rejected", "proposed"):
        json_error("invalid_field", "decision must be approved, rejected or proposed.", 422)
    reviewer = body.get("reviewer")
    row = db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            "SELECT maludb_skill_review(%s, %s, %s, %s) AS skill",
            [skill_id, decision, _ref(reviewer) if reviewer else None, body.get("note")],
        ),
    )
    return {"skill": _json(row["skill"])}


@router.put("/v1/skills/{skill_id}/principals/{ref}")
async def reserve_skill(auth: Auth, skill_id: int, ref: str, request: Request):
    _need_engine(auth)
    body = await _body(request)
    level = str(body.get("access_level") or "read").lower()
    if level not in ("read", "fork"):
        json_error("invalid_field", "access_level must be read or fork.", 422)
    db_tx_core(
        auth.conn,
        lambda c: db_one(c, "SELECT maludb_skill_grant_principal(%s, %s, %s) AS id", [skill_id, _ref(ref), level]),
    )
    return {"skill_id": skill_id, "principal": ref, "access_level": level}


@router.delete("/v1/skills/{skill_id}/principals/{ref}")
def unreserve_skill(auth: Auth, skill_id: int, ref: str):
    _need_engine(auth)
    row = db_tx_core(
        auth.conn, lambda c: db_one(c, "SELECT maludb_skill_revoke_principal(%s, %s) AS ok", [skill_id, _ref(ref)])
    )
    if not row["ok"]:
        json_error("not_found", "That skill is not reserved for that principal.", 404)
    return {"revoked": True, "skill_id": skill_id, "principal": ref}


@router.post("/v1/skills/{skill_id}/loads")
async def record_load(auth: Auth, skill_id: int, request: Request):
    _need_engine(auth)
    body = await _body(request)
    principal = body.get("principal_ref")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    row = db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            """SELECT maludb_skill_record_load(p_skill_id => %s, p_run_ref => %s, p_principal_ref => %s,
                          p_metadata => %s::jsonb) AS id""",
            [skill_id, body.get("run_ref"), _ref(principal) if principal else None, json.dumps(metadata)],
        ),
    )
    return JSONResponse(status_code=201, content={"load_event_id": int(row["id"]), "skill_id": skill_id})


@router.get("/v1/skills/{skill_id}/loads")
def list_loads(auth: Auth, skill_id: int, limit: int = 50):
    _need_engine(auth)
    rows = db_query(
        auth.conn,
        """SELECT load_event_id AS id, skill_name, version, bundle_hash, principal_ref, run_ref,
                  loaded_at::text AS loaded_at, metadata_jsonb AS metadata
             FROM maludb_skill_load_event WHERE skill_id = %s
            ORDER BY loaded_at DESC, load_event_id DESC LIMIT %s""",
        [skill_id, max(1, min(int(limit), 500))],
    )
    return {"skill_id": skill_id, "loads": rows}


# ===========================================================================
# pool presence
# ===========================================================================


def _pool_name(auth, pool_id: int) -> str:
    row = db_one(auth.conn, "SELECT pool_name FROM maludb_memory_pool WHERE pool_id = %s", [pool_id])
    if row is None:
        json_error("not_found", "Pool not found.", 404)  # out of this principal's scopes looks the same
    return row["pool_name"]


@router.get("/v1/pools/{pool_id}/presence")
def presence_list(auth: Auth, pool_id: int, include_left: bool = False):
    _need_engine(auth)
    name = _pool_name(auth, pool_id)
    rows = db_tx_core(
        auth.conn,
        lambda c: db_query(
            c,
            """SELECT presence_id AS id, participant_kind AS kind, participant_ref AS ref, role, declared_task,
                      cursor_jsonb AS cursor, ttl_seconds, last_seen_at::text AS last_seen_at, left_at::text AS left_at
                 FROM maludb_presence_list(%s, %s)""",
            [name, include_left],
        ),
    )
    return {"pool_id": pool_id, "present": rows}


@router.post("/v1/pools/{pool_id}/presence")
async def presence_update(auth: Auth, pool_id: int, request: Request):
    _need_engine(auth)
    body = await _body(request)
    name = _pool_name(auth, pool_id)
    cursor = body.get("cursor")
    ttl = body.get("ttl_seconds")
    if ttl is not None and (not isinstance(ttl, int) or ttl <= 0):
        json_error("invalid_field", "ttl_seconds must be a positive integer.", 422)
    row = db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            """SELECT maludb_presence_update(p_pool_name => %s, p_participant_kind => %s, p_participant_ref => %s,
                          p_role => %s, p_declared_task => %s, p_cursor_jsonb => %s::jsonb,
                          p_ttl_seconds => %s) AS id""",
            [
                name,
                body.get("kind"),
                body.get("ref"),
                body.get("role"),
                body.get("declared_task"),
                None if cursor is None else json.dumps(cursor),
                ttl,
            ],
        ),
    )
    return {"pool_id": pool_id, "presence_id": int(row["id"])}


@router.delete("/v1/pools/{pool_id}/presence")
async def presence_leave(auth: Auth, pool_id: int, request: Request):
    _need_engine(auth)
    body = await _body(request)
    name = _pool_name(auth, pool_id)
    row = db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            "SELECT maludb_presence_leave(%s, %s, %s, %s) AS ok",
            [name, body.get("kind"), body.get("ref"), body.get("reason")],
        ),
    )
    return {"pool_id": pool_id, "left": bool(row["ok"])}
