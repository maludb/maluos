"""
Type-list endpoints — read-only subject/verb types, CRUD document/episode types.

Ports PHP's:
  subject-types.php   — GET /v1/subject-types (read-only)
  verb-types.php      — GET /v1/verb-types (read-only)
  document-types.php  — GET/POST /v1/document-types
  document-types_id.php — PATCH/DELETE /v1/document-types/{id}
  episode-types.php   — GET/POST /v1/episode-types
  episode-types_id.php  — PATCH/DELETE /v1/episode-types/{id}

subject-types and verb-types are DB-managed (read-only picker lists).
document-types and episode-types have full CRUD with case-insensitive
uniqueness (lower(label) unique index; duplicate raises 23505 -> 409).
display_order is an integer for UI ordering.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_exec, db_one, db_query
from app.errors import json_error

router = APIRouter()


# ===========================================================================
# GET /v1/subject-types — read-only picker
# ===========================================================================


@router.get("/v1/subject-types")
async def list_subject_types(auth: Auth) -> JSONResponse:
    rows = db_query(
        auth.conn,
        """SELECT subject_type AS type,
                  display_name,
                  description,
                  sort_order
             FROM maludb_subject_type
            ORDER BY sort_order, subject_type""",
    )
    for r in rows:
        r["sort_order"] = None if r["sort_order"] is None else int(r["sort_order"])

    return JSONResponse(content={"subject_types": rows})


# ===========================================================================
# GET /v1/verb-types — read-only picker
# ===========================================================================


@router.get("/v1/verb-types")
async def list_verb_types(auth: Auth) -> JSONResponse:
    rows = db_query(
        auth.conn,
        """SELECT verb_type AS type,
                  display_name,
                  semantic_class,
                  description,
                  sort_order
             FROM maludb_verb_type
            ORDER BY sort_order, verb_type""",
    )
    for r in rows:
        r["sort_order"] = None if r["sort_order"] is None else int(r["sort_order"])

    return JSONResponse(content={"verb_types": rows})


# ===========================================================================
# Document types — CRUD
# ===========================================================================


def _load_document_type(auth: Auth, dt_id: int) -> dict | None:
    """Fetch a single document type, or None."""
    row = db_one(
        auth.conn,
        """SELECT document_type_id AS id,
                  document_type,
                  description,
                  display_order,
                  created_at
             FROM maludb_document_type
            WHERE document_type_id = %s""",
        [dt_id],
    )
    if row is None:
        return None
    row["id"] = int(row["id"])
    row["display_order"] = None if row["display_order"] is None else int(row["display_order"])
    return row


# ---------------------------------------------------------------------------
# GET /v1/document-types
# ---------------------------------------------------------------------------


@router.get("/v1/document-types")
async def list_document_types(auth: Auth) -> JSONResponse:
    rows = db_query(
        auth.conn,
        """SELECT document_type_id AS id,
                  document_type,
                  description,
                  display_order,
                  created_at
             FROM maludb_document_type
            ORDER BY display_order NULLS LAST, document_type""",
    )
    for r in rows:
        r["id"] = int(r["id"])
        r["display_order"] = None if r["display_order"] is None else int(r["display_order"])

    return JSONResponse(content={"document_types": rows})


# ---------------------------------------------------------------------------
# POST /v1/document-types
# ---------------------------------------------------------------------------


@router.post("/v1/document-types")
async def create_document_type(auth: Auth, request: Request) -> JSONResponse:
    body = await request.json()

    label = str(body.get("document_type") or "").strip()
    if not label:
        json_error("missing_field", 'Field "document_type" is required.', 400)

    description = str(body["description"]) if body.get("description") is not None else None

    display_order = None
    if "display_order" in body and body["display_order"] is not None:
        if not isinstance(body["display_order"], int):
            json_error("validation_failed", '"display_order" must be an integer.', 422)
        display_order = int(body["display_order"])

    created = db_one(
        auth.conn,
        """INSERT INTO maludb_document_type (document_type, description, display_order)
           VALUES (%s, %s, %s)
           RETURNING document_type_id AS id, document_type, description, display_order, created_at""",
        [label, description, display_order],
    )
    created["id"] = int(created["id"])
    created["display_order"] = None if created["display_order"] is None else int(created["display_order"])

    return JSONResponse(status_code=201, content={"document_type": created})


# ---------------------------------------------------------------------------
# PATCH /v1/document-types/{id}
# ---------------------------------------------------------------------------


@router.patch("/v1/document-types/{dt_id}")
async def update_document_type(auth: Auth, dt_id: int, request: Request) -> JSONResponse:
    if db_one(auth.conn, "SELECT 1 FROM maludb_document_type WHERE document_type_id = %s", [dt_id]) is None:
        json_error("not_found", "Document type not found.", 404)

    body = await request.json()
    fields: list[str] = []
    params: list = []

    if "document_type" in body:
        label = str(body["document_type"]).strip()
        if not label:
            json_error("validation_failed", 'Field "document_type" cannot be empty.', 422)
        fields.append("document_type = %s")
        params.append(label)

    if "description" in body:
        fields.append("description = %s")
        params.append(None if body["description"] is None else str(body["description"]))

    if "display_order" in body:
        if body["display_order"] is not None and not isinstance(body["display_order"], int):
            json_error("validation_failed", '"display_order" must be an integer.', 422)
        fields.append("display_order = %s")
        params.append(None if body["display_order"] is None else int(body["display_order"]))

    if not fields:
        json_error(
            "bad_request",
            "No updatable fields provided (document_type, description, display_order).",
            400,
        )

    params.append(dt_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_document_type SET {', '.join(fields)} WHERE document_type_id = %s",
        params,
    )

    return JSONResponse(content={"document_type": _load_document_type(auth, dt_id)})


# ---------------------------------------------------------------------------
# DELETE /v1/document-types/{id}
# ---------------------------------------------------------------------------


@router.delete("/v1/document-types/{dt_id}")
async def delete_document_type(auth: Auth, dt_id: int) -> JSONResponse:
    n = db_exec(auth.conn, "DELETE FROM maludb_document_type WHERE document_type_id = %s", [dt_id])
    if n == 0:
        json_error("not_found", "Document type not found.", 404)

    return JSONResponse(content={"deleted": True, "id": dt_id})


# ===========================================================================
# Episode types — CRUD
# ===========================================================================


def _load_episode_type(auth: Auth, et_id: int) -> dict | None:
    """Fetch a single episode type, or None."""
    row = db_one(
        auth.conn,
        """SELECT episode_type_id AS id,
                  episode_type,
                  description,
                  display_order,
                  created_at
             FROM maludb_episode_type
            WHERE episode_type_id = %s""",
        [et_id],
    )
    if row is None:
        return None
    row["id"] = int(row["id"])
    row["display_order"] = None if row["display_order"] is None else int(row["display_order"])
    return row


# ---------------------------------------------------------------------------
# GET /v1/episode-types
# ---------------------------------------------------------------------------


@router.get("/v1/episode-types")
async def list_episode_types(auth: Auth) -> JSONResponse:
    rows = db_query(
        auth.conn,
        """SELECT episode_type_id AS id,
                  episode_type,
                  description,
                  display_order,
                  created_at
             FROM maludb_episode_type
            ORDER BY display_order NULLS LAST, episode_type""",
    )
    for r in rows:
        r["id"] = int(r["id"])
        r["display_order"] = None if r["display_order"] is None else int(r["display_order"])

    return JSONResponse(content={"episode_types": rows})


# ---------------------------------------------------------------------------
# POST /v1/episode-types
# ---------------------------------------------------------------------------


@router.post("/v1/episode-types")
async def create_episode_type(auth: Auth, request: Request) -> JSONResponse:
    body = await request.json()

    label = str(body.get("episode_type") or "").strip()
    if not label:
        json_error("missing_field", 'Field "episode_type" is required.', 400)

    description = str(body["description"]) if body.get("description") is not None else None

    display_order = None
    if "display_order" in body and body["display_order"] is not None:
        if not isinstance(body["display_order"], int):
            json_error("validation_failed", '"display_order" must be an integer.', 422)
        display_order = int(body["display_order"])

    created = db_one(
        auth.conn,
        """INSERT INTO maludb_episode_type (episode_type, description, display_order)
           VALUES (%s, %s, %s)
           RETURNING episode_type_id AS id, episode_type, description, display_order, created_at""",
        [label, description, display_order],
    )
    created["id"] = int(created["id"])
    created["display_order"] = None if created["display_order"] is None else int(created["display_order"])

    return JSONResponse(status_code=201, content={"episode_type": created})


# ---------------------------------------------------------------------------
# PATCH /v1/episode-types/{id}
# ---------------------------------------------------------------------------


@router.patch("/v1/episode-types/{et_id}")
async def update_episode_type(auth: Auth, et_id: int, request: Request) -> JSONResponse:
    if db_one(auth.conn, "SELECT 1 FROM maludb_episode_type WHERE episode_type_id = %s", [et_id]) is None:
        json_error("not_found", "Episode type not found.", 404)

    body = await request.json()
    fields: list[str] = []
    params: list = []

    if "episode_type" in body:
        label = str(body["episode_type"]).strip()
        if not label:
            json_error("validation_failed", 'Field "episode_type" cannot be empty.', 422)
        fields.append("episode_type = %s")
        params.append(label)

    if "description" in body:
        fields.append("description = %s")
        params.append(None if body["description"] is None else str(body["description"]))

    if "display_order" in body:
        if body["display_order"] is not None and not isinstance(body["display_order"], int):
            json_error("validation_failed", '"display_order" must be an integer.', 422)
        fields.append("display_order = %s")
        params.append(None if body["display_order"] is None else int(body["display_order"]))

    if not fields:
        json_error(
            "bad_request",
            "No updatable fields provided (episode_type, description, display_order).",
            400,
        )

    params.append(et_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_episode_type SET {', '.join(fields)} WHERE episode_type_id = %s",
        params,
    )

    return JSONResponse(content={"episode_type": _load_episode_type(auth, et_id)})


# ---------------------------------------------------------------------------
# DELETE /v1/episode-types/{id}
# ---------------------------------------------------------------------------


@router.delete("/v1/episode-types/{et_id}")
async def delete_episode_type(auth: Auth, et_id: int) -> JSONResponse:
    n = db_exec(auth.conn, "DELETE FROM maludb_episode_type WHERE episode_type_id = %s", [et_id])
    if n == 0:
        json_error("not_found", "Episode type not found.", 404)

    return JSONResponse(content={"deleted": True, "id": et_id})
