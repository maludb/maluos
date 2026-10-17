"""
Verb endpoints — list, create, detail, update, delete, and linked subjects.

Ports PHP's /v1/verbs (verbs.php), /v1/verbs/{id} (verbs_id.php),
and /v1/verbs/{id}/subjects (verbs_id_subjects.php).

Live-schema mapping (DB column -> API field):
  verb_id        -> id
  verb_type      -> type
  canonical_name, description, classifier_md -> same

Subject links live in maludb_subject_verb keyed by verb_name (= canonical_name).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_exec, db_one, db_query
from app.errors import json_error
from app.helpers.query import Col, QuerySpec, build_where, content_range, parse_query, resolve_total, wants_count
from app.helpers.writes import as_items, tx_with_advisory_lock

router = APIRouter()


# ---------------------------------------------------------------------------
# Query spec — allowlist for the PostgREST-style grammar on GET /v1/verbs.
# ---------------------------------------------------------------------------

_LINKED_SUBJECTS = "(SELECT count(*) FROM maludb_subject_verb sv WHERE sv.verb_name = v.canonical_name)"

VERB_QUERY = QuerySpec(
    columns={
        "id": Col("v.verb_id", int),
        "canonical_name": Col("v.canonical_name", str),
        "type": Col("v.verb_type", str),
        "description": Col("v.description", str),
        "classifier_md": Col("v.classifier_md", str),
        "linked_subjects": Col(_LINKED_SUBJECTS, int),
    },
    default_order=[("canonical_name", "asc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_verb_detail(auth: Auth, verb_id: int) -> dict | None:
    """Fetch a verb with its embedded subjects[], or None if not found."""
    verb = db_one(
        auth.conn,
        """SELECT verb_id        AS id,
                  canonical_name AS canonical_name,
                  verb_type      AS type,
                  description,
                  classifier_md
             FROM maludb_verb
            WHERE verb_id = %s""",
        [verb_id],
    )
    if verb is None:
        return None
    verb["id"] = int(verb["id"])

    subjects = db_query(
        auth.conn,
        """SELECT s.subject_id     AS id,
                  s.canonical_name AS label,
                  s.subject_type   AS type
             FROM maludb_subject_verb sv
             JOIN maludb_subject s ON s.canonical_name = sv.subject_name
            WHERE sv.verb_name = %s
            ORDER BY s.canonical_name""",
        [verb["canonical_name"]],
    )
    for s in subjects:
        s["id"] = int(s["id"])
    verb["subjects"] = subjects

    return verb


# ---------------------------------------------------------------------------
# GET /v1/verbs — list verbs
# ---------------------------------------------------------------------------


@router.get("/v1/verbs")
async def list_verbs(auth: Auth, request: Request, response: Response):
    params = request.query_params
    qp = parse_query(params, VERB_QUERY, reserved=("q",))
    where_params = list(qp.where_params)

    # Back-compat: ?q= keeps its substring search over name + description.
    q_clause = ""
    q = params.get("q")
    if q:
        q_clause = "(v.canonical_name ILIKE %s OR v.description ILIKE %s)"
        where_params += [f"%{q}%", f"%{q}%"]

    where_sql = build_where(qp.where_clause, q_clause)

    sql = f"""SELECT {qp.select_list}
                FROM maludb_verb v
                {where_sql}
                {qp.order_sql}
                {qp.limit_sql}"""

    rows = db_query(auth.conn, sql, where_params + qp.limit_params)
    for r in rows:
        if r.get("id") is not None:
            r["id"] = int(r["id"])
        if r.get("linked_subjects") is not None:
            r["linked_subjects"] = int(r["linked_subjects"])

    total = resolve_total(auth.conn, wants_count(request), "maludb_verb v", where_sql, where_params)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)

    return {"verbs": rows}


# ---------------------------------------------------------------------------
# POST /v1/verbs — create a verb
# ---------------------------------------------------------------------------


def _insert_verb(conn, item: dict) -> dict:
    """Validate + insert one verb, returning the shaped row. Runs under the
    maludb_verb advisory lock so the MAX(verb_id)+1 id can't collide."""
    name = str(item.get("canonical_name") or "").strip()
    if not name:
        json_error("missing_field", 'Field "canonical_name" is required.', 400)

    vtype = str(item["type"]) if item.get("type") is not None else None
    description = str(item["description"]) if item.get("description") is not None else None
    classifier_md = str(item["classifier_md"]) if item.get("classifier_md") is not None else None

    created = db_one(
        conn,
        """INSERT INTO maludb_verb
               (verb_id, canonical_name, verb_type, description, classifier_md, created_at)
           SELECT COALESCE(MAX(verb_id), 0) + 1, %s, %s, %s, %s, now()
             FROM maludb_verb
           RETURNING verb_id        AS id,
                     canonical_name AS canonical_name,
                     verb_type      AS type,
                     description,
                     classifier_md""",
        [name, vtype, description, classifier_md],
    )
    created["id"] = int(created["id"])
    created["linked_subjects"] = 0
    return created


@router.post("/v1/verbs")
async def create_verb(auth: Auth, request: Request) -> JSONResponse:
    # A JSON array bulk-creates; a JSON object is unchanged. All inserts run in
    # one transaction under the maludb_verb advisory lock (all-or-nothing).
    items, is_batch = as_items(await request.json())
    created = tx_with_advisory_lock(
        auth.conn,
        "maludb_verb",
        lambda conn: [_insert_verb(conn, item) for item in items],
    )
    if is_batch:
        return JSONResponse(status_code=201, content={"verbs": created})
    return JSONResponse(status_code=201, content={"verb": created[0]})


# ---------------------------------------------------------------------------
# GET /v1/verbs/{id} — verb detail with embedded subjects
# ---------------------------------------------------------------------------


@router.get("/v1/verbs/{verb_id}")
async def get_verb(auth: Auth, verb_id: int) -> JSONResponse:
    verb = _load_verb_detail(auth, verb_id)
    if verb is None:
        json_error("not_found", "Verb not found.", 404)

    return JSONResponse(content={"verb": verb})


# ---------------------------------------------------------------------------
# PATCH /v1/verbs/{id} — update a verb
# ---------------------------------------------------------------------------


@router.patch("/v1/verbs/{verb_id}")
async def update_verb(auth: Auth, verb_id: int, request: Request) -> JSONResponse:
    if db_one(auth.conn, "SELECT 1 FROM maludb_verb WHERE verb_id = %s", [verb_id]) is None:
        json_error("not_found", "Verb not found.", 404)

    body = await request.json()
    fields: list[str] = []
    params: list = []

    if "canonical_name" in body:
        name = str(body["canonical_name"]).strip()
        if not name:
            json_error("validation_failed", 'Field "canonical_name" cannot be empty.', 422)
        fields.append("canonical_name = %s")
        params.append(name)

    if "type" in body:
        fields.append("verb_type = %s")
        params.append(None if body["type"] is None else str(body["type"]))

    if "description" in body:
        fields.append("description = %s")
        params.append(None if body["description"] is None else str(body["description"]))

    if "classifier_md" in body:
        fields.append("classifier_md = %s")
        params.append(None if body["classifier_md"] is None else str(body["classifier_md"]))

    if not fields:
        json_error(
            "bad_request",
            "No updatable fields provided (canonical_name, type, description, classifier_md).",
            400,
        )

    params.append(verb_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_verb SET {', '.join(fields)} WHERE verb_id = %s",
        params,
    )

    return JSONResponse(content={"verb": _load_verb_detail(auth, verb_id)})


# ---------------------------------------------------------------------------
# DELETE /v1/verbs/{id} — delete a verb
# ---------------------------------------------------------------------------


@router.delete("/v1/verbs/{verb_id}")
async def delete_verb(auth: Auth, verb_id: int) -> JSONResponse:
    n = db_exec(auth.conn, "DELETE FROM maludb_verb WHERE verb_id = %s", [verb_id])
    if n == 0:
        json_error("not_found", "Verb not found.", 404)

    return JSONResponse(content={"deleted": True, "id": verb_id})


# ---------------------------------------------------------------------------
# GET /v1/verbs/{id}/subjects — linked subjects for a verb
# ---------------------------------------------------------------------------


@router.get("/v1/verbs/{verb_id}/subjects")
async def verb_subjects(auth: Auth, verb_id: int) -> JSONResponse:
    verb = db_one(auth.conn, "SELECT canonical_name FROM maludb_verb WHERE verb_id = %s", [verb_id])
    if verb is None:
        json_error("not_found", "Verb not found.", 404)

    subjects = db_query(
        auth.conn,
        """SELECT s.subject_id     AS id,
                  s.canonical_name AS label,
                  s.subject_type   AS type
             FROM maludb_subject_verb sv
             JOIN maludb_subject s ON s.canonical_name = sv.subject_name
            WHERE sv.verb_name = %s
            ORDER BY s.canonical_name""",
        [verb["canonical_name"]],
    )
    for s in subjects:
        s["id"] = int(s["id"])

    return JSONResponse(content={"subjects": subjects})
