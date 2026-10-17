"""
Statement endpoints — list, create, detail, update (provenance/close), delete.

Ports PHP's statements.php and statements_id.php.

A statement is (subject_kind, subject_id) --verb_id--> (object_kind, object_id).
Created via the idempotent maludb_svpor_statement_create(...) facade. Everything
runs inside db_tx_core() so the facade can resolve its malu$* base tables + RLS grants.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error
from app.helpers.query import Col, QuerySpec, content_range, parse_query, resolve_total, wants_count
from app.helpers.statements import STATEMENT_COLS, shape_statement, svpor_create_statement
from app.helpers.writes import as_items

router = APIRouter()


# ---------------------------------------------------------------------------
# Query spec — allowlist for the PostgREST-style grammar on GET /v1/statements.
# Mirrors STATEMENT_COLS; the original exact filters (provenance, *_kind, *_id,
# verb_id) are kept for back-compat as reserved legacy params.
# ---------------------------------------------------------------------------

STATEMENT_QUERY = QuerySpec(
    columns={
        "id": Col("statement_id", int),
        "subject_kind": Col("subject_kind", str),
        "subject_id": Col("subject_id", int),
        "verb_id": Col("verb_id", int),
        "object_kind": Col("object_kind", str),
        "object_id": Col("object_id", int),
        "predicate_id": Col("predicate_id", int),
        "valid_from": Col("valid_from", str),
        "valid_to": Col("valid_to", str),
        "confidence": Col("confidence", float),
        "provenance": Col("provenance", str),
        "source_package_id": Col("source_package_id", int),
        "metadata": Col("metadata_jsonb", str),
        "created_at": Col("created_at", str),
    },
    default_order=[("id", "desc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helper — load a single shaped statement row
# ---------------------------------------------------------------------------


def _load_statement(conn, statement_id: int) -> dict | None:
    """Fetch a single statement, or None if not found."""
    row = db_one(
        conn,
        f"SELECT {STATEMENT_COLS} FROM maludb_svpor_statement WHERE statement_id = %s",
        [statement_id],
    )
    if row is None:
        return None
    shape_statement(row)
    return row


# ===========================================================================
# GET /v1/statements — list statements
# ===========================================================================


@router.get("/v1/statements")
def list_statements(auth: Auth, request: Request, response: Response):
    # provenance / subject_kind / object_kind / subject_id / object_id / verb_id
    # are ordinary spec columns: bare values are exact-match (back-compat), and
    # the op grammar (?subject_id=in.(1,2)) works too — all via the parser.
    qp = parse_query(request.query_params, STATEMENT_QUERY)
    where_params = qp.where_params
    count_kind = wants_count(request)

    def _query(conn):
        sql = f"""SELECT {qp.select_list}
                    FROM maludb_svpor_statement
                    {qp.where_sql}
                   {qp.order_sql}
                   {qp.limit_sql}"""

        rows = db_query(conn, sql, where_params + qp.limit_params)
        for r in rows:
            shape_statement(r)
        total = resolve_total(conn, count_kind, "maludb_svpor_statement", qp.where_sql, where_params)
        return rows, total

    rows, total = db_tx_core(auth.conn, _query)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)
    return {"statements": rows}


# ===========================================================================
# POST /v1/statements — create one statement (JSON object) or many (JSON array)
# ===========================================================================


@router.post("/v1/statements")
async def create_statement(auth: Auth, request: Request):
    # A JSON array bulk-creates; every item runs through the same idempotent
    # facade in ONE transaction (all-or-nothing). A JSON object is unchanged.
    items, is_batch = as_items(await request.json())

    def _create(conn):
        return [svpor_create_statement(conn, item) for item in items]

    created = db_tx_core(auth.conn, _create)
    if is_batch:
        return JSONResponse(status_code=201, content={"statements": created})
    return JSONResponse(status_code=201, content={"statement": created[0]})


# ===========================================================================
# GET /v1/statements/{id} — statement detail
# ===========================================================================


@router.get("/v1/statements/{statement_id}")
def get_statement(statement_id: int, auth: Auth):
    def _get(conn):
        return _load_statement(conn, statement_id)

    stmt = db_tx_core(auth.conn, _get)
    if stmt is None:
        json_error("not_found", "Statement not found.", 404)
    return {"statement": stmt}


# ===========================================================================
# PATCH /v1/statements/{id} — update provenance and/or close
# ===========================================================================


@router.patch("/v1/statements/{statement_id}")
async def update_statement(statement_id: int, auth: Auth, request: Request):
    body = await request.json()

    set_provenance = (
        "provenance" in body
        and body["provenance"] is not None
        and str(body["provenance"]).strip() != ""
    )
    do_close = (
        ("close" in body and body["close"] is True)
        or "valid_to" in body
    )

    if not set_provenance and not do_close:
        json_error(
            "bad_request",
            "No updatable fields provided (provenance, valid_to, close).",
            400,
        )

    def _update(conn):
        if db_one(conn, "SELECT 1 FROM maludb_svpor_statement WHERE statement_id = %s", [statement_id]) is None:
            return None
        if set_provenance:
            db_one(
                conn,
                "SELECT maludb_svpor_statement_set_provenance(%s, %s)",
                [statement_id, str(body["provenance"])],
            )
        if do_close:
            # close:true -> now(); explicit valid_to -> that timestamp (null also closes at now()).
            valid_to = (
                str(body["valid_to"])
                if "valid_to" in body and body["valid_to"] is not None
                else None
            )
            db_one(
                conn,
                "SELECT maludb_svpor_statement_close(%s, COALESCE(%s::timestamptz, now()))",
                [statement_id, valid_to],
            )
        return _load_statement(conn, statement_id)

    stmt = db_tx_core(auth.conn, _update)
    if stmt is None:
        json_error("not_found", "Statement not found.", 404)
    return {"statement": stmt}


# ===========================================================================
# DELETE /v1/statements/{id} — delete a statement
# ===========================================================================


@router.delete("/v1/statements/{statement_id}")
def delete_statement(statement_id: int, auth: Auth):
    def _delete(conn):
        if db_one(conn, "SELECT 1 FROM maludb_svpor_statement WHERE statement_id = %s", [statement_id]) is None:
            return False
        db_one(conn, "SELECT maludb_svpor_statement_delete(%s)", [statement_id])
        return True

    deleted = db_tx_core(auth.conn, _delete)
    if not deleted:
        json_error("not_found", "Statement not found.", 404)
    return {"deleted": True, "id": statement_id}
