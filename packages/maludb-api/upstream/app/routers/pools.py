"""
Pool endpoints — list, create, detail, update, archive.

Ports PHP's pools.php, pools_id.php, pools_id_archive.php.

Live-schema mapping (DB column -> API field):
    pool_id        -> id
    pool_name      -> name
    task_objective -> description
Source table: maludb_memory_pool (pool_id from sequence).
creation_kind is set to 'api'; lifecycle_state defaults to 'active'.
No DELETE in v1.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_exec, db_one, db_query
from app.errors import json_error
from app.helpers.query import Col, QuerySpec, build_where, content_range, parse_query, resolve_total, wants_count

router = APIRouter()


# ---------------------------------------------------------------------------
# Query spec — allowlist for the PostgREST-style grammar on GET /v1/pools.
# Tombstoned pools are always excluded (a permanent base predicate below).
# ---------------------------------------------------------------------------

POOL_QUERY = QuerySpec(
    columns={
        "id": Col("pool_id", int),
        "name": Col("pool_name", str),
        "description": Col("task_objective", str),
        "lifecycle_state": Col("lifecycle_state", str),
        "archived_at": Col("archived_at", str),
        "created_at": Col("created_at", str),
    },
    default_order=[("name", "asc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helper — load a single pool
# ---------------------------------------------------------------------------


def _load_pool(auth: Auth, pool_id: int) -> dict | None:
    """Fetch a single pool, or None if not found."""
    pool = db_one(
        auth.conn,
        """SELECT pool_id        AS id,
                  pool_name      AS name,
                  task_objective AS description,
                  lifecycle_state,
                  archived_at,
                  created_at,
                  updated_at
             FROM maludb_memory_pool
            WHERE pool_id = %s""",
        [pool_id],
    )
    if pool is None:
        return None
    pool["id"] = int(pool["id"])
    return pool


# ===========================================================================
# GET /v1/pools — list pools (excludes tombstoned)
# ===========================================================================


@router.get("/v1/pools")
def list_pools(auth: Auth, request: Request, response: Response):
    params = request.query_params
    qp = parse_query(params, POOL_QUERY, reserved=("q",))
    where_params = list(qp.where_params)

    # Back-compat: ?q= keeps its substring search over name + objective.
    q_clause = ""
    q = params.get("q")
    if q:
        q_clause = "(pool_name ILIKE %s OR task_objective ILIKE %s)"
        where_params += [f"%{q}%", f"%{q}%"]

    # Tombstoned pools are never listed (permanent base predicate).
    where_sql = build_where("(lifecycle_state IS DISTINCT FROM 'tombstoned')", qp.where_clause, q_clause)

    sql = f"""SELECT {qp.select_list}
                FROM maludb_memory_pool
                {where_sql}
                {qp.order_sql}
                {qp.limit_sql}"""

    rows = db_query(auth.conn, sql, where_params + qp.limit_params)
    for r in rows:
        if r.get("id") is not None:
            r["id"] = int(r["id"])

    total = resolve_total(auth.conn, wants_count(request), "maludb_memory_pool", where_sql, where_params)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)

    return {"pools": rows}


# ===========================================================================
# POST /v1/pools — create a pool
# ===========================================================================


@router.post("/v1/pools")
async def create_pool(auth: Auth, request: Request):
    body = await request.json()

    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        json_error("missing_field", 'Field "name" is required.', 400)

    description = str(body["description"]) if "description" in body and body["description"] is not None else None

    created = db_one(
        auth.conn,
        """INSERT INTO maludb_memory_pool (pool_name, task_objective, creation_kind, created_at)
           VALUES (%s, %s, 'api', now())
           RETURNING pool_id AS id, pool_name AS name, task_objective AS description,
                     lifecycle_state, archived_at, created_at""",
        [name, description],
    )
    created["id"] = int(created["id"])

    return JSONResponse(status_code=201, content={"pool": created})


# ===========================================================================
# GET /v1/pools/{id} — pool detail
# ===========================================================================


@router.get("/v1/pools/{pool_id}")
def get_pool(pool_id: int, auth: Auth):
    pool = _load_pool(auth, pool_id)
    if pool is None:
        json_error("not_found", "Pool not found.", 404)
    return {"pool": pool}


# ===========================================================================
# PATCH /v1/pools/{id} — update a pool
# ===========================================================================


@router.patch("/v1/pools/{pool_id}")
async def update_pool(pool_id: int, auth: Auth, request: Request):
    if db_one(auth.conn, "SELECT 1 FROM maludb_memory_pool WHERE pool_id = %s", [pool_id]) is None:
        json_error("not_found", "Pool not found.", 404)

    body = await request.json()
    fields: list[str] = []
    params: list = []

    if "name" in body:
        name = str(body["name"]).strip() if body["name"] is not None else ""
        if not name:
            json_error("validation_failed", 'Field "name" cannot be empty.', 422)
        fields.append("pool_name = %s")
        params.append(name)
    if "description" in body:
        fields.append("task_objective = %s")
        params.append(None if body["description"] is None else str(body["description"]))

    if not fields:
        json_error("bad_request", "No updatable fields provided (name, description).", 400)

    fields.append("updated_at = now()")
    params.append(pool_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_memory_pool SET {', '.join(fields)} WHERE pool_id = %s",
        params,
    )

    return {"pool": _load_pool(auth, pool_id)}


# ===========================================================================
# POST /v1/pools/{id}/archive — archive a pool
# ===========================================================================


@router.post("/v1/pools/{pool_id}/archive")
def archive_pool(pool_id: int, auth: Auth):
    pool = db_one(
        auth.conn,
        "SELECT lifecycle_state, archived_at FROM maludb_memory_pool WHERE pool_id = %s",
        [pool_id],
    )
    if pool is None:
        json_error("not_found", "Pool not found.", 404)
    if pool["archived_at"] is not None or pool["lifecycle_state"] == "archived":
        json_error("already_archived", "Pool is already archived.", 409)

    db_exec(
        auth.conn,
        """UPDATE maludb_memory_pool
              SET lifecycle_state = 'archived', archived_at = now(), updated_at = now()
            WHERE pool_id = %s""",
        [pool_id],
    )

    updated = db_one(
        auth.conn,
        """SELECT pool_id AS id, pool_name AS name, task_objective AS description,
                  lifecycle_state, archived_at, created_at
             FROM maludb_memory_pool WHERE pool_id = %s""",
        [pool_id],
    )
    updated["id"] = int(updated["id"])

    return {"pool": updated}
