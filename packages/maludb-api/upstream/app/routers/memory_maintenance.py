"""
Memory maintenance endpoints — thin proxies over maludb_core lifecycle functions.

These power the external memory-organization agent's safe maintenance actions:
consolidation, lifecycle transitions, staleness propagation, MAUT scoring /
reinforcement, and retention-candidate listing. Each is a direct call to an
executor-granted maludb_core function inside db_tx_core(); a pg_proc guard returns
501 when the core build predates the function. No per-schema facade is required: the
tenant role inherits maludb_memory_executor (USAGE on maludb_core) and maludb_core is
already on the search_path (mirrors the existing maludb_core.secret_set call).
"""

from __future__ import annotations

import json

import psycopg
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error

router = APIRouter()

# apply_lifecycle_state / propagate_staleness / retention_candidates accept these.
_OBJECT_TYPES = ("fact", "memory", "episode_object")


def _require_core_fn(conn: psycopg.Connection, proname: str) -> None:
    """Return 501 (capability unavailable) when a maludb_core function is absent."""
    has = db_one(conn, "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = %s) AS ok", [proname])
    if not has or not has["ok"]:
        json_error(
            f"{proname}_unavailable",
            f"maludb_core.{proname} is not available in this database (requires a newer maludb_core).",
            501,
        )


def _object_type(body: dict) -> str:
    object_type = str(body.get("object_type", "")).strip()
    if object_type not in _OBJECT_TYPES:
        json_error("bad_request", f'Field "object_type" must be one of {list(_OBJECT_TYPES)}.', 400)
    return object_type


def _object_id(body: dict) -> int:
    raw = body.get("object_id")
    if not isinstance(raw, int) or isinstance(raw, bool):
        json_error("missing_field", 'Field "object_id" (integer) is required.', 400)
    return raw


@router.post("/v1/memory/consolidate")
async def consolidate(auth: Auth, request: Request):
    """Merge memories into a new consolidated memory (maludb_core.consolidate_memories)."""
    body = await request.json()
    raw_ids = body.get("memory_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        json_error("missing_field", 'Field "memory_ids" (non-empty array) is required.', 400)
    try:
        memory_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        json_error("bad_request", '"memory_ids" must be integers.', 400)

    kind = str(body.get("kind", "")).strip()
    title = str(body.get("title", "")).strip()
    summary = str(body.get("summary", "")).strip()
    if not kind or not title:
        json_error("missing_field", 'Fields "kind" and "title" are required.', 400)
    payload = body.get("payload") or {}
    reason = body.get("reason")

    _require_core_fn(auth.conn, "consolidate_memories")

    def _do(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_core.consolidate_memories("
            " p_source_memory_ids => %s::bigint[], p_consolidated_kind => %s,"
            " p_title => %s, p_summary => %s, p_payload_jsonb => %s::jsonb, p_reason => %s"
            ") AS memory_id",
            [memory_ids, kind, title, summary, json.dumps(payload), reason],
        )

    row = db_tx_core(auth.conn, _do)
    return JSONResponse(status_code=201, content={"consolidated_into_memory_id": int(row["memory_id"])})


@router.post("/v1/memory/lifecycle")
async def set_lifecycle_state(auth: Auth, request: Request):
    """Transition an object's lifecycle state (maludb_core.apply_lifecycle_state)."""
    body = await request.json()
    object_type = _object_type(body)
    object_id = _object_id(body)
    state = str(body.get("state", "")).strip()
    if not state:
        json_error("missing_field", 'Field "state" is required.', 400)
    reason = body.get("reason")

    _require_core_fn(auth.conn, "apply_lifecycle_state")

    def _do(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_core.apply_lifecycle_state(%s, %s, %s, %s) AS ok",
            [object_type, object_id, state, reason],
        )

    db_tx_core(auth.conn, _do)
    return {"object_type": object_type, "object_id": object_id, "state": state}


@router.post("/v1/memory/staleness")
async def propagate_staleness(auth: Auth, request: Request):
    """Mark an object and its dependents stale (maludb_core.propagate_staleness)."""
    body = await request.json()
    object_type = _object_type(body)
    object_id = _object_id(body)
    reason = body.get("reason")

    _require_core_fn(auth.conn, "propagate_staleness")

    def _do(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_core.propagate_staleness(%s, %s, %s) AS affected",
            [object_type, object_id, reason],
        )

    row = db_tx_core(auth.conn, _do)
    return {"object_type": object_type, "object_id": object_id, "affected": int(row["affected"])}


@router.post("/v1/memory/score")
async def set_score(auth: Auth, request: Request):
    """Set a MAUT subscore for an object (maludb_core.set_maut_score)."""
    body = await request.json()
    object_type = _object_type(body)
    object_id = _object_id(body)
    category = str(body.get("category", "")).strip()
    if not category:
        json_error("missing_field", 'Field "category" is required.', 400)
    subscore = body.get("subscore")
    if not isinstance(subscore, (int, float)) or isinstance(subscore, bool):
        json_error("missing_field", 'Field "subscore" (number) is required.', 400)
    evaluator_name = str(body.get("evaluator_name", "")).strip()
    if not evaluator_name:
        json_error("missing_field", 'Field "evaluator_name" is required.', 400)
    evaluator_kind = str(body.get("evaluator_kind") or "automated")
    evaluator_meta = body.get("evaluator_meta")
    evidence = body.get("evidence")

    _require_core_fn(auth.conn, "set_maut_score")

    def _do(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_core.set_maut_score("
            " p_target_object_type => %s, p_target_object_id => %s, p_category => %s,"
            " p_subscore => %s, p_evaluator_name => %s, p_evaluator_kind => %s,"
            " p_evaluator_meta => %s::jsonb, p_evidence => %s::jsonb) AS maut_score_id",
            [
                object_type,
                object_id,
                category,
                subscore,
                evaluator_name,
                evaluator_kind,
                json.dumps(evaluator_meta) if evaluator_meta is not None else None,
                json.dumps(evidence) if evidence is not None else None,
            ],
        )

    row = db_tx_core(auth.conn, _do)
    return JSONResponse(status_code=201, content={"maut_score_id": int(row["maut_score_id"])})


@router.post("/v1/memory/reinforcement")
async def record_reinforcement(auth: Auth, request: Request):
    """Append a reinforcement event for an object (maludb_core.record_reinforcement)."""
    body = await request.json()
    object_type = _object_type(body)
    object_id = _object_id(body)
    event_kind = str(body.get("event_kind", "")).strip()
    if not event_kind:
        json_error("missing_field", 'Field "event_kind" is required.', 400)
    weight = body.get("weight")
    if weight is not None and (not isinstance(weight, (int, float)) or isinstance(weight, bool)):
        json_error("bad_request", '"weight" must be a number.', 400)
    context = body.get("context")

    _require_core_fn(auth.conn, "record_reinforcement")

    def _do(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_core.record_reinforcement("
            " p_target_object_type => %s, p_target_object_id => %s, p_event_kind => %s,"
            " p_weight => COALESCE(%s, 1.0), p_context_jsonb => %s::jsonb) AS event_id",
            [object_type, object_id, event_kind, weight, json.dumps(context) if context is not None else None],
        )

    row = db_tx_core(auth.conn, _do)
    return JSONResponse(status_code=201, content={"reinforcement_event_id": int(row["event_id"])})


@router.get("/v1/memory/retention-candidates")
def retention_candidates(
    auth: Auth,
    object_type: str = Query(..., max_length=32),
    cutoff: str | None = Query(default=None, max_length=64),
):
    """List objects eligible for retention review (maludb_core.retention_candidates)."""
    if object_type not in _OBJECT_TYPES:
        json_error("bad_request", f'"object_type" must be one of {list(_OBJECT_TYPES)}.', 400)

    _require_core_fn(auth.conn, "retention_candidates")
    rows = db_query(
        auth.conn,
        "SELECT object_id, lifecycle_state, last_updated, days_idle"
        " FROM maludb_core.retention_candidates(%s, COALESCE(%s::timestamptz, now()))",
        [object_type, cutoff],
    )
    return {"object_type": object_type, "candidates": rows}
