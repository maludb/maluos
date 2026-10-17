"""
Note endpoints — list, create, detail, update, delete, close-issue, reopen-issue.

Ports PHP's notes.php, notes_id.php, notes_id_close-issue.php, notes_id_reopen-issue.php.

Live-schema mapping (DB column -> API field):
    memory_id   -> id
    title       -> title
    summary     -> body
    memory_kind -> type
    project_id lives in payload_jsonb->>'project_id'
Source table: maludb_memory (memory_id from sequence).
Default type: 'note'. Type 'issue' enables close/reopen workflow.
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
# Query spec — allowlist for the PostgREST-style grammar on GET /v1/notes.
# Legacy ?type= (exact memory_kind) and ?q= (substring) are kept for back-compat.
# ---------------------------------------------------------------------------

NOTE_QUERY = QuerySpec(
    columns={
        "id": Col("memory_id", int),
        "title": Col("title", str),
        "body": Col("summary", str),
        "type": Col("memory_kind", str),
        "project_id": Col("(payload_jsonb->>'project_id')::bigint", int),
        "issue_closed_at": Col("issue_closed_at", str),
        "created_at": Col("created_at", str),
    },
    default_order=[("created_at", "desc nulls last"), ("id", "desc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helper — load a single note
# ---------------------------------------------------------------------------


def _load_note(auth: Auth, note_id: int) -> dict | None:
    """Fetch a single note, or None if not found."""
    note = db_one(
        auth.conn,
        """SELECT memory_id AS id, title, summary AS body, memory_kind AS type,
                  (payload_jsonb->>'project_id')::bigint AS project_id,
                  issue_closed_at, created_at, updated_at
             FROM maludb_memory
            WHERE memory_id = %s""",
        [note_id],
    )
    if note is None:
        return None
    note["id"] = int(note["id"])
    note["project_id"] = None if note["project_id"] is None else int(note["project_id"])
    return note


# ===========================================================================
# GET /v1/notes — list notes
# ===========================================================================


@router.get("/v1/notes")
def list_notes(auth: Auth, request: Request, response: Response):
    params = request.query_params
    # ?type= is the memory_kind spec column (bare value = exact-match, op grammar works).
    qp = parse_query(params, NOTE_QUERY, reserved=("q",))
    where_params = list(qp.where_params)

    # Back-compat: ?q= substring search over title + summary.
    q_clause = ""
    q = params.get("q")
    if q:
        q_clause = "(title ILIKE %s OR summary ILIKE %s)"
        where_params += [f"%{q}%", f"%{q}%"]

    where_sql = build_where(qp.where_clause, q_clause)

    sql = f"""SELECT {qp.select_list}
                FROM maludb_memory
                {where_sql}
                {qp.order_sql}
                {qp.limit_sql}"""

    rows = db_query(auth.conn, sql, where_params + qp.limit_params)
    for r in rows:
        if r.get("id") is not None:
            r["id"] = int(r["id"])
        if "project_id" in r:
            r["project_id"] = None if r["project_id"] is None else int(r["project_id"])

    total = resolve_total(auth.conn, wants_count(request), "maludb_memory", where_sql, where_params)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)

    return {"notes": rows}


# ===========================================================================
# POST /v1/notes — create a note
# ===========================================================================


@router.post("/v1/notes")
async def create_note(auth: Auth, request: Request):
    body = await request.json()

    title = (body.get("title") or "").strip() if isinstance(body.get("title"), str) else ""
    if not title:
        json_error("missing_field", 'Field "title" is required.', 400)

    text = str(body["body"]) if "body" in body and body["body"] is not None else None
    type_ = (
        str(body["type"])
        if "type" in body and body["type"] is not None and str(body["type"]).strip()
        else "note"
    )

    payload = "{}"
    project_id = None
    if "project_id" in body and body["project_id"] is not None:
        if not isinstance(body["project_id"], int):
            json_error("validation_failed", '"project_id" must be an integer.', 422)
        project_id = int(body["project_id"])
        if db_one(auth.conn, "SELECT 1 FROM maludb_project WHERE subject_id = %s", [project_id]) is None:
            json_error("validation_failed", "project_id does not refer to an existing project.", 422)
        import json as _json

        payload = _json.dumps({"project_id": project_id})

    note = db_one(
        auth.conn,
        """INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, recorded_at)
           VALUES (%s, %s, %s, %s::jsonb, now())
           RETURNING memory_id AS id, title, summary AS body, memory_kind AS type,
                     issue_closed_at::text AS issue_closed_at,
                     created_at::text AS created_at""",
        [type_, title, text, payload],
    )
    note["id"] = int(note["id"])
    note["project_id"] = project_id

    return JSONResponse(status_code=201, content={"note": note})


# ===========================================================================
# GET /v1/notes/{id} — note detail
# ===========================================================================


@router.get("/v1/notes/{note_id}")
def get_note(note_id: int, auth: Auth):
    note = _load_note(auth, note_id)
    if note is None:
        json_error("not_found", "Note not found.", 404)
    return {"note": note}


# ===========================================================================
# PATCH /v1/notes/{id} — update a note
# ===========================================================================


@router.patch("/v1/notes/{note_id}")
async def update_note(note_id: int, auth: Auth, request: Request):
    if db_one(auth.conn, "SELECT 1 FROM maludb_memory WHERE memory_id = %s", [note_id]) is None:
        json_error("not_found", "Note not found.", 404)

    body = await request.json()
    fields: list[str] = []
    params: list = []

    if "title" in body:
        title = str(body["title"]).strip() if body["title"] is not None else ""
        if not title:
            json_error("validation_failed", 'Field "title" cannot be empty.', 422)
        fields.append("title = %s")
        params.append(title)
    if "body" in body:
        fields.append("summary = %s")
        params.append(None if body["body"] is None else str(body["body"]))
    if "type" in body:
        type_ = str(body["type"]).strip() if body["type"] is not None else ""
        if not type_:
            json_error("validation_failed", 'Field "type" cannot be empty.', 422)
        fields.append("memory_kind = %s")
        params.append(type_)
    if "project_id" in body:
        if body["project_id"] is None:
            fields.append("payload_jsonb = payload_jsonb - 'project_id'")
        else:
            if not isinstance(body["project_id"], int):
                json_error("validation_failed", '"project_id" must be an integer or null.', 422)
            pid = int(body["project_id"])
            if db_one(auth.conn, "SELECT 1 FROM maludb_project WHERE subject_id = %s", [pid]) is None:
                json_error("validation_failed", "project_id does not refer to an existing project.", 422)
            fields.append(
                "payload_jsonb = jsonb_set(COALESCE(payload_jsonb,'{}'::jsonb), '{project_id}', to_jsonb(%s::bigint))"
            )
            params.append(pid)

    if not fields:
        json_error("bad_request", "No updatable fields provided (title, body, type, project_id).", 400)

    fields.append("updated_at = now()")
    params.append(note_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_memory SET {', '.join(fields)} WHERE memory_id = %s",
        params,
    )

    return {"note": _load_note(auth, note_id)}


# ===========================================================================
# DELETE /v1/notes/{id} — delete a note
# ===========================================================================


@router.delete("/v1/notes/{note_id}")
def delete_note(note_id: int, auth: Auth):
    n = db_exec(auth.conn, "DELETE FROM maludb_memory WHERE memory_id = %s", [note_id])
    if n == 0:
        json_error("not_found", "Note not found.", 404)
    return {"deleted": True, "id": note_id}


# ===========================================================================
# POST /v1/notes/{id}/close-issue — close an issue
# ===========================================================================


@router.post("/v1/notes/{note_id}/close-issue")
def close_issue(note_id: int, auth: Auth):
    note = db_one(
        auth.conn,
        "SELECT memory_kind, issue_closed_at FROM maludb_memory WHERE memory_id = %s",
        [note_id],
    )
    if note is None:
        json_error("not_found", "Note not found.", 404)
    if note["memory_kind"] != "issue":
        json_error("conflict", "Note is not an issue.", 409)
    if note["issue_closed_at"] is not None:
        json_error("conflict", "Issue is already closed.", 409)

    db_exec(
        auth.conn,
        "UPDATE maludb_memory SET issue_closed_at = now(), updated_at = now() WHERE memory_id = %s",
        [note_id],
    )

    row = db_one(
        auth.conn,
        """SELECT memory_id AS id, title, summary AS body, memory_kind AS type,
                  issue_closed_at FROM maludb_memory WHERE memory_id = %s""",
        [note_id],
    )
    row["id"] = int(row["id"])
    return {"note": row}


# ===========================================================================
# POST /v1/notes/{id}/reopen-issue — reopen a closed issue
# ===========================================================================


@router.post("/v1/notes/{note_id}/reopen-issue")
def reopen_issue(note_id: int, auth: Auth):
    note = db_one(
        auth.conn,
        "SELECT memory_kind, issue_closed_at FROM maludb_memory WHERE memory_id = %s",
        [note_id],
    )
    if note is None:
        json_error("not_found", "Note not found.", 404)
    if note["memory_kind"] != "issue":
        json_error("conflict", "Note is not an issue.", 409)
    if note["issue_closed_at"] is None:
        json_error("conflict", "Issue is not closed.", 409)

    db_exec(
        auth.conn,
        "UPDATE maludb_memory SET issue_closed_at = NULL, updated_at = now() WHERE memory_id = %s",
        [note_id],
    )

    row = db_one(
        auth.conn,
        """SELECT memory_id AS id, title, summary AS body, memory_kind AS type,
                  issue_closed_at FROM maludb_memory WHERE memory_id = %s""",
        [note_id],
    )
    row["id"] = int(row["id"])
    return {"note": row}
