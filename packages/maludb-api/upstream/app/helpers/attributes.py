"""
Typed-attribute helpers (maludb_core 0.83.0+).

Ported from PHP config/response.php — shared by the attributes router and
the attribute-by-id sub-router.  An attribute is a typed property on any node
OR edge, addressed by (target_kind, target_id); target_kind includes
'svpor_statement' so graph edges carry attributes too.  Created/upserted (on
target+attr_name) via the idempotent maludb_svpor_attribute_create(...) facade.
Both routes call svpor_create_attribute() inside db_tx_core() (the facade
references its malu$* base tables unqualified, so it needs maludb_core on the
search_path).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from app.database import db_one, db_query, db_tx_core
from app.errors import json_error

# ---------------------------------------------------------------------------
# Column list and row shaper
# ---------------------------------------------------------------------------

ATTRIBUTE_COLS: str = (
    "attribute_id AS id, target_kind, target_id, attr_name,"
    " value_timestamp, value_range, value_numeric, value_text, value_jsonb,"
    " unit, provenance, confidence, valid_from, valid_to,"
    " metadata_jsonb AS metadata, created_at, ref_source, ref_entity, ref_key"
)


def shape_attribute(row: dict[str, Any]) -> None:
    """Normalize scalar types on an attribute row *in place*.

    Mirrors PHP's shape_attribute(): cast integer columns, float columns,
    and decode the JSON string columns (if still strings — psycopg v3 with
    dict_row may auto-decode jsonb columns).
    """
    # Guard each cast on key presence so a ?select= projection that drops a
    # column stays dropped (rather than re-added as None) and never KeyErrors.
    for key in ("id", "target_id"):
        if key in row:
            val = row[key]
            row[key] = int(val) if val is not None else None

    for key in ("value_numeric", "confidence"):
        if key in row:
            val = row[key]
            row[key] = float(val) if val is not None else None

    for key in ("value_jsonb", "metadata"):
        if key in row:
            val = row[key]
            if val is None:
                row[key] = None
            elif isinstance(val, str):
                row[key] = json.loads(val)
            # else: already decoded by psycopg (dict) — leave as-is

    # value_range (tstzrange) is left as its text form.


# ---------------------------------------------------------------------------
# Create / upsert helper — MUST run inside db_tx_core()
# ---------------------------------------------------------------------------

def svpor_create_attribute(
    conn: psycopg.Connection,
    body: dict[str, Any],
    force_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create/upsert an attribute from a request body and return the (shaped) row.

    MUST run inside db_tx_core().  Upsert is on (target_kind, target_id, attr_name).
    Recognized body keys:
      target_kind (req), target_id (req int), attr_name (req),
      value_timestamp, value_range, value_numeric, value_text, value_jsonb,
      unit, provenance (default 'provided'), confidence, valid_from, valid_to,
      metadata (object), ref_source, ref_entity, ref_key.

    *force_target* = {'kind': ..., 'id': ...} overrides target_kind/target_id
    (used by scoped routes).
    """

    # ---- phase 1: parse + shape-validate (no DB writes) ----

    if force_target is not None:
        target_kind = str(force_target["kind"])
        target_id = int(force_target["id"])
    else:
        target_kind = str(body.get("target_kind", "")).strip()
        if not target_kind:
            json_error("missing_field", 'Field "target_kind" is required.', 400)
        if "target_id" not in body or not isinstance(body["target_id"], int):
            json_error("validation_failed", '"target_id" must be an integer.', 422)
        target_id = int(body["target_id"])

    attr_name = str(body.get("attr_name", "")).strip()
    if not attr_name:
        json_error("missing_field", 'Field "attr_name" is required.', 400)

    for key in ("value_numeric", "confidence"):
        if key in body and body[key] is not None:
            try:
                float(body[key])
            except (TypeError, ValueError):
                json_error("validation_failed", f'"{key}" must be a number.', 422)

    value_timestamp: str | None = str(body["value_timestamp"]) if body.get("value_timestamp") is not None else None
    value_range: str | None = str(body["value_range"]) if body.get("value_range") is not None else None
    value_numeric: str | None = (
        str(body["value_numeric"])
        if "value_numeric" in body and body["value_numeric"] is not None
        else None
    )
    value_text: str | None = str(body["value_text"]) if body.get("value_text") is not None else None
    value_jsonb: str | None = (
        json.dumps(body["value_jsonb"])
        if "value_jsonb" in body and body["value_jsonb"] is not None
        else None
    )
    unit: str | None = str(body["unit"]) if body.get("unit") is not None else None
    provenance: str = (
        str(body["provenance"])
        if body.get("provenance") and str(body.get("provenance", "")).strip()
        else "provided"
    )
    confidence: str | None = (
        str(body["confidence"])
        if "confidence" in body and body["confidence"] is not None
        else None
    )
    valid_from: str | None = str(body["valid_from"]) if body.get("valid_from") is not None else None
    valid_to: str | None = str(body["valid_to"]) if body.get("valid_to") is not None else None
    metadata: str = (
        json.dumps(body["metadata"])
        if isinstance(body.get("metadata"), dict)
        else "{}"
    )
    ref_source: str | None = str(body["ref_source"]) if body.get("ref_source") is not None else None
    ref_entity: str | None = str(body["ref_entity"]) if body.get("ref_entity") is not None else None
    ref_key: str | None = str(body["ref_key"]) if body.get("ref_key") is not None else None

    # ---- phase 2: upsert via the facade (named args; idempotent on target+attr_name) ----

    row = db_one(
        conn,
        """SELECT maludb_svpor_attribute_create(
                    p_target_kind     => %s, p_target_id => %s, p_attr_name => %s,
                    p_value_timestamp => %s::timestamptz,
                    p_value_range     => %s::tstzrange,
                    p_value_numeric   => %s::numeric,
                    p_value_text      => %s,
                    p_value_jsonb     => %s::jsonb,
                    p_unit            => %s,
                    p_provenance      => %s,
                    p_confidence      => %s::numeric,
                    p_valid_from      => %s::timestamptz,
                    p_valid_to        => %s::timestamptz,
                    p_metadata_jsonb  => %s::jsonb,
                    p_ref_source      => %s, p_ref_entity => %s, p_ref_key => %s
                ) AS id""",
        [
            target_kind, target_id, attr_name,
            value_timestamp, value_range, value_numeric,
            value_text, value_jsonb, unit,
            provenance, confidence, valid_from, valid_to,
            metadata, ref_source, ref_entity, ref_key,
        ],
    )

    attr = db_one(
        conn,
        f"SELECT {ATTRIBUTE_COLS} FROM maludb_svpor_attribute WHERE attribute_id = %s",
        [int(row["id"])],  # type: ignore[index]
    )
    shape_attribute(attr)  # type: ignore[arg-type]
    return attr  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Attach attributes (?with=attributes) — batch fetch + decode
# ---------------------------------------------------------------------------

def attach_attributes(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    view: str,
    pk_col: str,
) -> None:
    """Attach an ``attributes`` key to each row from a ``*_with_attributes`` view.

    For a list endpoint called with ``?with=attributes``: one extra query inside
    db_tx_core() (the ``*_with_attributes`` views resolve their malu$* tables
    there).  *view* and *pk_col* are endpoint constants (never user input).
    """
    if not rows:
        return

    ids = [int(r["id"]) for r in rows]
    placeholders = ",".join(["%s"] * len(ids))

    attrs = db_tx_core(
        conn,
        lambda c: db_query(
            c,
            f"SELECT {pk_col} AS id, attributes FROM {view} WHERE {pk_col} IN ({placeholders})",
            ids,
        ),
    )

    by_id: dict[int, Any] = {}
    for a in attrs:
        val = a["attributes"]
        if val is None:
            decoded = None
        elif isinstance(val, str):
            decoded = json.loads(val)
        else:
            decoded = val  # already decoded by psycopg
        by_id[int(a["id"])] = decoded

    for r in rows:
        r["attributes"] = by_id.get(int(r["id"]))
