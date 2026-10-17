"""
SVPOR statement helpers (maludb_core 0.82.0).

Ported from PHP config/response.php — shared by the statements router and
the episode-scoped statements sub-router.  A statement is
  (subject_kind, subject_id) --verb_id--> (object_kind, object_id).
Created via the idempotent maludb_svpor_statement_create(...) facade; both
routes call svpor_create_statement() inside db_tx_core() (the verb/subject/
predicate resolvers and the facade need maludb_core on the search_path).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from app.database import db_one
from app.errors import json_error

# ---------------------------------------------------------------------------
# Column list and row shaper
# ---------------------------------------------------------------------------

STATEMENT_COLS: str = (
    "statement_id AS id, subject_kind, subject_id, verb_id, object_kind, object_id,"
    " predicate_id, valid_from, valid_to, confidence, provenance, source_package_id,"
    " metadata_jsonb AS metadata, created_at"
)


def shape_statement(row: dict[str, Any]) -> None:
    """Normalize scalar types on a statement row *in place*.

    Mirrors PHP's shape_statement(): cast integer columns, confidence to
    float, and decode the metadata JSON string (if still a string —
    psycopg v3 with dict_row may auto-decode jsonb columns).
    """
    # Guard each cast on key presence so a ?select= projection that drops a
    # column stays dropped (rather than re-added as None) and never KeyErrors.
    for key in ("id", "subject_id", "verb_id", "object_id", "predicate_id", "source_package_id"):
        if key in row:
            val = row[key]
            row[key] = int(val) if val is not None else None

    if "confidence" in row:
        val = row["confidence"]
        row["confidence"] = float(val) if val is not None else None

    if "metadata" in row:
        val = row["metadata"]
        if val is None:
            row["metadata"] = None
        elif isinstance(val, str):
            row["metadata"] = json.loads(val)
        # else: already decoded by psycopg (dict) — leave as-is


# ---------------------------------------------------------------------------
# Create helper — MUST run inside db_tx_core()
# ---------------------------------------------------------------------------

def svpor_create_statement(
    conn: psycopg.Connection,
    body: dict[str, Any],
    force_object: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a statement from a request body and return the created (shaped) row.

    MUST run inside db_tx_core().  Recognized body keys:
      verb | verb_id, subject_kind (default 'subject'), subject_id | subject
      (name, only when kind='subject' — create-or-resolve a person),
      object_kind, object_id, predicate | predicate_id, valid_from, valid_to,
      confidence, provenance (default 'provided'), source_package_id, metadata.

    *force_object* = {'kind': ..., 'id': ...} overrides object_kind/object_id
    (used by the episode-scoped route).
    """

    # ---- phase 1: parse + shape-validate (no DB writes) ----

    verb_id: int | None = None
    verb_name: str | None = None
    if "verb_id" in body:
        if not isinstance(body["verb_id"], int):
            json_error("validation_failed", '"verb_id" must be an integer.', 422)
        verb_id = int(body["verb_id"])
    elif "verb" in body and str(body.get("verb", "")).strip():
        verb_name = str(body["verb"])
    else:
        json_error("missing_field", 'Provide "verb" (name) or "verb_id".', 400)

    subject_kind: str = (
        str(body["subject_kind"])
        if "subject_kind" in body and str(body.get("subject_kind", "")).strip()
        else "subject"
    )

    subject_id: int | None = None
    subject_name: str | None = None
    if "subject_id" in body:
        if not isinstance(body["subject_id"], int):
            json_error("validation_failed", '"subject_id" must be an integer.', 422)
        subject_id = int(body["subject_id"])
    elif subject_kind == "subject" and "subject" in body and str(body.get("subject", "")).strip():
        subject_name = str(body["subject"])
    else:
        json_error(
            "missing_field",
            'Provide "subject_id", or "subject" (name) when subject_kind is "subject".',
            400,
        )

    if force_object is not None:
        object_kind = str(force_object["kind"])
        object_id = int(force_object["id"])
    else:
        object_kind = str(body.get("object_kind", "")).strip()
        if not object_kind:
            json_error("missing_field", 'Field "object_kind" is required.', 400)
        if "object_id" not in body or not isinstance(body["object_id"], int):
            json_error("validation_failed", '"object_id" must be an integer.', 422)
        object_id = int(body["object_id"])

    predicate_id: int | None = None
    predicate_name: str | None = None
    if "predicate_id" in body:
        if not isinstance(body["predicate_id"], int):
            json_error("validation_failed", '"predicate_id" must be an integer.', 422)
        predicate_id = int(body["predicate_id"])
    elif "predicate" in body and str(body.get("predicate", "")).strip():
        predicate_name = str(body["predicate"])

    if "confidence" in body and body["confidence"] is not None:
        try:
            float(body["confidence"])
        except (TypeError, ValueError):
            json_error("validation_failed", '"confidence" must be a number.', 422)

    valid_from: str | None = str(body["valid_from"]) if body.get("valid_from") is not None else None
    valid_to: str | None = str(body["valid_to"]) if body.get("valid_to") is not None else None
    confidence: str | None = (
        str(body["confidence"])
        if "confidence" in body and body["confidence"] is not None
        else None
    )
    provenance: str = (
        str(body["provenance"])
        if body.get("provenance") and str(body.get("provenance", "")).strip()
        else "provided"
    )
    source_pkg: int | None = (
        int(body["source_package_id"])
        if body.get("source_package_id") is not None
        else None
    )
    metadata: str = (
        json.dumps(body["metadata"])
        if isinstance(body.get("metadata"), dict)
        else "{}"
    )

    # ---- phase 2: resolve names (SELECTs), then upsert the subject, then create ----

    if verb_id is None:
        row = db_one(conn, "SELECT maludb_core.resolve_svpor_verb(%s) AS id", [verb_name])
        resolved = row["id"] if row else None
        if resolved is None:
            json_error("validation_failed", f'Unknown verb "{verb_name}".', 422)
        verb_id = int(resolved)

    if predicate_name is not None:
        row = db_one(conn, "SELECT maludb_core.resolve_svpor_predicate(%s) AS id", [predicate_name])
        resolved = row["id"] if row else None
        if resolved is None:
            json_error("validation_failed", f'Unknown predicate "{predicate_name}".', 422)
        predicate_id = int(resolved)

    if subject_id is None:
        row = db_one(
            conn,
            "SELECT register_svpor_subject(p_canonical_name => %s, p_subject_type => 'person') AS id",
            [subject_name],
        )
        subject_id = int(row["id"])  # type: ignore[index]

    row = db_one(
        conn,
        """SELECT maludb_svpor_statement_create(
                    p_subject_kind      => %s, p_subject_id => %s,
                    p_verb_id           => %s,
                    p_object_kind       => %s, p_object_id  => %s,
                    p_predicate_id      => %s,
                    p_valid_from        => %s::timestamptz, p_valid_to => %s::timestamptz,
                    p_confidence        => %s::numeric,
                    p_provenance        => %s,
                    p_source_package_id => %s,
                    p_metadata_jsonb    => %s::jsonb
                ) AS id""",
        [
            subject_kind, subject_id, verb_id,
            object_kind, object_id, predicate_id,
            valid_from, valid_to, confidence,
            provenance, source_pkg, metadata,
        ],
    )

    stmt = db_one(
        conn,
        f"SELECT {STATEMENT_COLS} FROM maludb_svpor_statement WHERE statement_id = %s",
        [int(row["id"])],  # type: ignore[index]
    )
    shape_statement(stmt)  # type: ignore[arg-type]
    return stmt  # type: ignore[return-value]
