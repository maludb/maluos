"""
Attribute endpoints — CRUD for attributes, attribute templates, and attribute check.

Ports PHP's attributes.php, attributes_id.php, attribute-templates.php,
attribute-templates_id.php, and attribute-check.php.

An attribute is a typed property on any node OR edge, addressed by
(target_kind, target_id).  Created/upserted (on target+attr_name) via the
idempotent maludb_svpor_attribute_create(...) facade.  All queries run inside
db_tx_core() because the facade references its malu$* base tables unqualified.

Attribute templates are the form-catalog that drives forms: which attributes
apply to a given node/edge type, their value_type, requirement, label, unit, etc.

Attribute check is an advisory completeness check — the DB never rejects on
missing attributes; this is for the form layer to validate completeness.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error
from app.helpers.attributes import ATTRIBUTE_COLS, shape_attribute, svpor_create_attribute
from app.helpers.query import Col, QuerySpec, content_range, parse_query, resolve_total, wants_count
from app.helpers.writes import as_items

router = APIRouter()


# ---------------------------------------------------------------------------
# Query spec — allowlist for the PostgREST-style grammar on GET /v1/attributes.
# Mirrors ATTRIBUTE_COLS; legacy ?target_kind=/?target_id=/?attr_name=/?provenance=
# (all exact) are kept for back-compat.
# ---------------------------------------------------------------------------

ATTRIBUTE_QUERY = QuerySpec(
    columns={
        "id": Col("attribute_id", int),
        "target_kind": Col("target_kind", str),
        "target_id": Col("target_id", int),
        "attr_name": Col("attr_name", str),
        "value_timestamp": Col("value_timestamp", str),
        "value_range": Col("value_range", str),
        "value_numeric": Col("value_numeric", float),
        "value_text": Col("value_text", str),
        "value_jsonb": Col("value_jsonb", str),
        "unit": Col("unit", str),
        "provenance": Col("provenance", str),
        "confidence": Col("confidence", float),
        "valid_from": Col("valid_from", str),
        "valid_to": Col("valid_to", str),
        "metadata": Col("metadata_jsonb", str),
        "created_at": Col("created_at", str),
        "ref_source": Col("ref_source", str),
        "ref_entity": Col("ref_entity", str),
        "ref_key": Col("ref_key", str),
    },
    default_order=[("id", "desc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATE_COLS: str = (
    "template_id AS id, applies_to, type_value, attr_name, value_type, requirement,"
    " label, description, unit, allowed_values, default_value, display_order, created_at"
)


def _shape_template(row: dict[str, Any]) -> None:
    """Normalize scalar types on a template row *in place*.

    Mirrors PHP's shape_template(): cast integer columns and decode JSON string
    columns.
    """
    row["id"] = int(row["id"]) if row.get("id") is not None else None
    row["display_order"] = (
        int(row["display_order"]) if row.get("display_order") is not None else None
    )
    for key in ("allowed_values", "default_value"):
        val = row.get(key)
        if val is None:
            row[key] = None
        elif isinstance(val, str):
            row[key] = json.loads(val)
        # else: already decoded by psycopg (dict/list) — leave as-is


def _load_attribute(conn, attribute_id: int) -> dict | None:
    """Fetch a single attribute, or None if not found."""
    row = db_one(
        conn,
        f"SELECT {ATTRIBUTE_COLS} FROM maludb_svpor_attribute WHERE attribute_id = %s",
        [attribute_id],
    )
    if row is None:
        return None
    shape_attribute(row)
    return row


def _load_template(conn, template_id: int) -> dict | None:
    """Fetch a single template, or None if not found."""
    row = db_one(
        conn,
        f"SELECT {TEMPLATE_COLS} FROM maludb_attribute_template WHERE template_id = %s",
        [template_id],
    )
    if row is None:
        return None
    _shape_template(row)
    return row


# ===========================================================================
# GET /v1/attributes — list attributes
# ===========================================================================


@router.get("/v1/attributes")
def list_attributes(auth: Auth, request: Request, response: Response):
    # target_kind / target_id / attr_name / provenance are ordinary spec columns:
    # bare values are exact-match (back-compat), and the op grammar works too.
    qp = parse_query(request.query_params, ATTRIBUTE_QUERY)
    where_params = qp.where_params
    count_kind = wants_count(request)

    def _query(conn):
        sql = f"""SELECT {qp.select_list}
                    FROM maludb_svpor_attribute
                    {qp.where_sql}
                   {qp.order_sql}
                   {qp.limit_sql}"""

        rows = db_query(conn, sql, where_params + qp.limit_params)
        for r in rows:
            shape_attribute(r)
        total = resolve_total(conn, count_kind, "maludb_svpor_attribute", qp.where_sql, where_params)
        return rows, total

    rows, total = db_tx_core(auth.conn, _query)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)
    return {"attributes": rows}


# ===========================================================================
# POST /v1/attributes — create/upsert one attribute (object) or many (array)
# ===========================================================================


@router.post("/v1/attributes")
async def create_attribute(auth: Auth, request: Request):
    # A JSON array bulk-upserts; every item runs through the same idempotent
    # facade (upsert on target+attr_name) in ONE transaction (all-or-nothing).
    items, is_batch = as_items(await request.json())

    def _create(conn):
        return [svpor_create_attribute(conn, item) for item in items]

    created = db_tx_core(auth.conn, _create)
    if is_batch:
        return JSONResponse(status_code=201, content={"attributes": created})
    return JSONResponse(status_code=201, content={"attribute": created[0]})


# ===========================================================================
# GET /v1/attributes/{id} — attribute detail
# ===========================================================================


@router.get("/v1/attributes/{attribute_id}")
def get_attribute(attribute_id: int, auth: Auth):
    def _get(conn):
        return _load_attribute(conn, attribute_id)

    attr = db_tx_core(auth.conn, _get)
    if attr is None:
        json_error("not_found", "Attribute not found.", 404)
    return {"attribute": attr}


# ===========================================================================
# PATCH /v1/attributes/{id} — set provenance only
# ===========================================================================


@router.patch("/v1/attributes/{attribute_id}")
async def update_attribute(attribute_id: int, auth: Auth, request: Request):
    body = await request.json()

    if (
        "provenance" not in body
        or body["provenance"] is None
        or str(body["provenance"]).strip() == ""
    ):
        json_error(
            "bad_request",
            'PATCH supports only "provenance" (use POST to re-upsert values).',
            400,
        )

    def _update(conn):
        if db_one(conn, "SELECT 1 FROM maludb_svpor_attribute WHERE attribute_id = %s", [attribute_id]) is None:
            return None
        db_one(
            conn,
            "SELECT maludb_svpor_attribute_set_provenance(%s, %s)",
            [attribute_id, str(body["provenance"])],
        )
        return _load_attribute(conn, attribute_id)

    attr = db_tx_core(auth.conn, _update)
    if attr is None:
        json_error("not_found", "Attribute not found.", 404)
    return {"attribute": attr}


# ===========================================================================
# DELETE /v1/attributes/{id} — delete an attribute
# ===========================================================================


@router.delete("/v1/attributes/{attribute_id}")
def delete_attribute(attribute_id: int, auth: Auth):
    def _delete(conn):
        if db_one(conn, "SELECT 1 FROM maludb_svpor_attribute WHERE attribute_id = %s", [attribute_id]) is None:
            return False
        db_one(conn, "SELECT maludb_svpor_attribute_delete(%s)", [attribute_id])
        return True

    deleted = db_tx_core(auth.conn, _delete)
    if not deleted:
        json_error("not_found", "Attribute not found.", 404)
    return {"deleted": True, "id": attribute_id}


# ===========================================================================
# GET /v1/attribute-templates — list attribute templates
# ===========================================================================


@router.get("/v1/attribute-templates")
def list_attribute_templates(
    auth: Auth,
    applies_to: str | None = Query(default=None, max_length=40),
    type_value: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, le=500),
):
    def _query(conn):
        clauses: list[str] = []
        params: list = []
        if applies_to:
            clauses.append("applies_to = %s")
            params.append(applies_to)
        if type_value:
            clauses.append("type_value = %s")
            params.append(type_value)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        sql = f"""SELECT {TEMPLATE_COLS}
                    FROM maludb_attribute_template
                    {where}
                   ORDER BY applies_to, type_value, display_order NULLS LAST, attr_name
                   LIMIT %s"""
        params.append(limit)

        rows = db_query(conn, sql, params)
        for r in rows:
            _shape_template(r)
        return rows

    rows = db_tx_core(auth.conn, _query)
    return {"attribute_templates": rows}


# ===========================================================================
# POST /v1/attribute-templates — create an attribute template
# ===========================================================================


@router.post("/v1/attribute-templates")
async def create_attribute_template(auth: Auth, request: Request):
    body = await request.json()

    applies_to = str(body.get("applies_to", "")).strip()
    type_value = str(body.get("type_value", "")).strip()
    attr_name = str(body.get("attr_name", "")).strip()
    value_type = str(body.get("value_type", "")).strip()

    for name, val in [
        ("applies_to", applies_to),
        ("type_value", type_value),
        ("attr_name", attr_name),
        ("value_type", value_type),
    ]:
        if not val:
            json_error("missing_field", f'Field "{name}" is required.', 400)

    requirement = (
        str(body["requirement"])
        if body.get("requirement") and str(body["requirement"]).strip()
        else "optional"
    )
    label = str(body["label"]) if "label" in body and body["label"] is not None else None
    description = str(body["description"]) if "description" in body and body["description"] is not None else None
    unit = str(body["unit"]) if "unit" in body and body["unit"] is not None else None
    allowed_values = (
        json.dumps(body["allowed_values"])
        if "allowed_values" in body and body["allowed_values"] is not None
        else None
    )
    default_value = (
        json.dumps(body["default_value"])
        if "default_value" in body and body["default_value"] is not None
        else None
    )
    display_order = None
    if "display_order" in body and body["display_order"] is not None:
        if not isinstance(body["display_order"], int):
            json_error("validation_failed", '"display_order" must be an integer.', 422)
        display_order = int(body["display_order"])

    def _create(conn):
        row = db_one(
            conn,
            """SELECT maludb_attribute_template_create(
                        p_applies_to     => %s, p_type_value => %s, p_attr_name => %s, p_value_type => %s,
                        p_requirement    => %s, p_label => %s, p_description => %s, p_unit => %s,
                        p_allowed_values => %s::jsonb, p_default_value => %s::jsonb, p_display_order => %s
                    ) AS id""",
            [
                applies_to, type_value, attr_name, value_type,
                requirement, label, description, unit,
                allowed_values, default_value, display_order,
            ],
        )
        t = db_one(
            conn,
            f"SELECT {TEMPLATE_COLS} FROM maludb_attribute_template WHERE template_id = %s",
            [int(row["id"])],  # type: ignore[index]
        )
        _shape_template(t)  # type: ignore[arg-type]
        return t

    created = db_tx_core(auth.conn, _create)
    return JSONResponse(status_code=201, content={"attribute_template": created})


# ===========================================================================
# GET /v1/attribute-templates/{id} — template detail
# ===========================================================================


@router.get("/v1/attribute-templates/{template_id}")
def get_attribute_template(template_id: int, auth: Auth):
    def _get(conn):
        return _load_template(conn, template_id)

    t = db_tx_core(auth.conn, _get)
    if t is None:
        json_error("not_found", "Attribute template not found.", 404)
    return {"attribute_template": t}


# ===========================================================================
# PATCH /v1/attribute-templates/{id} — not supported (405)
# ===========================================================================


@router.patch("/v1/attribute-templates/{template_id}")
def patch_attribute_template(template_id: int, auth: Auth):
    json_error("method_not_allowed", "This endpoint supports GET and DELETE.", 405)


# ===========================================================================
# DELETE /v1/attribute-templates/{id} — delete a template
# ===========================================================================


@router.delete("/v1/attribute-templates/{template_id}")
def delete_attribute_template(template_id: int, auth: Auth):
    def _delete(conn):
        if db_one(conn, "SELECT 1 FROM maludb_attribute_template WHERE template_id = %s", [template_id]) is None:
            return False
        db_one(conn, "SELECT maludb_attribute_template_delete(%s)", [template_id])
        return True

    deleted = db_tx_core(auth.conn, _delete)
    if not deleted:
        json_error("not_found", "Attribute template not found.", 404)
    return {"deleted": True, "id": template_id}


# ===========================================================================
# GET /v1/attribute-check — advisory completeness check
# ===========================================================================


@router.get("/v1/attribute-check")
def attribute_check(
    auth: Auth,
    target_kind: str | None = Query(default=None, max_length=40),
    target_id: int | None = Query(default=None),
):
    if not target_kind:
        json_error("missing_field", 'Query param "target_kind" is required.', 400)
    if target_id is None:
        json_error("missing_field", 'Query param "target_id" is required.', 400)

    def _check(conn):
        row = db_one(
            conn,
            "SELECT maludb_attribute_check(%s, %s) AS check",
            [target_kind, target_id],
        )
        if row and row["check"] is not None:
            val = row["check"]
            if isinstance(val, str):
                return json.loads(val)
            return val  # already decoded by psycopg
        return None

    check = db_tx_core(auth.conn, _check)
    return {"check": check}
