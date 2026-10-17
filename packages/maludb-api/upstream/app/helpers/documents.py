"""
Document-to-graph link/unlink helpers (maludb_core 0.87.0).

Ported from PHP config/response.php — the "Document ↔ graph helpers" section.
Documents are first-class graph nodes: a project/subject/stakeholder tag on a
document is mirrored as a real edge  (document) --concerns|mentions|involves-->
(subject)  plus the resolved id on the soft tag row, exactly as
maludb_upload_document does.  All helpers MUST run inside db_tx_core() (the
graph facades resolve their malu$* base tables there).
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.database import db_exec, db_one, db_query
from app.errors import json_error

# ---------------------------------------------------------------------------
# document_link_spec — tag_kind → (subject_type, verb)
# ---------------------------------------------------------------------------

_LINK_SPEC: dict[str, tuple[str, str]] = {
    "project": ("project", "concerns"),
    "subject": ("concept", "mentions"),
    "stakeholder": ("person", "involves"),
}


def document_link_spec(tag_kind: str) -> tuple[str, str] | None:
    """Map a document tag_kind to (subject_type, verb) for graph wiring.

    Returns None for unknown kinds.  Mirrors PHP's document_link_spec().
    """
    return _LINK_SPEC.get(tag_kind)


# ---------------------------------------------------------------------------
# document_link_subject — resolve-or-create + edge + soft tag (idempotent)
# ---------------------------------------------------------------------------

def document_link_subject(
    conn: psycopg.Connection,
    document_id: int,
    tag_kind: str,
    name: str,
    provenance: str = "provided",
) -> int | None:
    """Link a document to a project/subject/stakeholder by name (idempotent).

    Resolve-or-create the subject WITHOUT clobbering an existing subject's
    type, create the document→subject edge, and record the resolved id on the
    soft tag row.  Returns the subject_id (None for a blank name).

    MUST run inside db_tx_core().  Mirrors PHP's document_link_subject().
    """
    name = name.strip()
    if not name:
        return None

    spec = document_link_spec(tag_kind)
    if spec is None:
        json_error("validation_failed", f'Unsupported document link kind "{tag_kind}".', 422)
    subject_type, verb = spec  # type: ignore[misc]

    # Resolve-or-create the subject.  Reuse an existing one as-is (never
    # override its type) — mirrors maludb_core._document_graph_link;
    # register_svpor_subject() would clobber the type.
    row = db_one(conn, "SELECT subject_id FROM maludb_subject WHERE canonical_name = %s", [name])
    if row is not None:
        subject_id = int(row["subject_id"])
    else:
        row = db_one(
            conn,
            "SELECT register_svpor_subject(p_canonical_name => %s, p_subject_type => %s) AS id",
            [name, subject_type],
        )
        subject_id = int(row["id"])  # type: ignore[index]

    verb_id = int(
        db_one(conn, "SELECT maludb_core.resolve_svpor_verb(%s) AS id", [verb])["id"]  # type: ignore[index]
    )

    db_one(
        conn,
        """SELECT maludb_svpor_statement_create(
                    p_subject_kind => 'document', p_subject_id => %s,
                    p_verb_id      => %s,
                    p_object_kind  => 'subject',  p_object_id  => %s,
                    p_provenance   => %s) AS id""",
        [document_id, verb_id, subject_id, provenance],
    )

    # The soft tag carries the resolved object so the UI can link to the real record.
    tag = db_one(
        conn,
        """SELECT tag_id FROM maludb_document_tag
          WHERE document_id = %s AND tag_kind = %s AND tag_value = %s AND provenance = %s""",
        [document_id, tag_kind, name, provenance],
    )
    if tag is None:
        db_exec(
            conn,
            """INSERT INTO maludb_document_tag
               (document_id, tag_kind, tag_value, tag_object_type, tag_object_id, provenance)
               VALUES (%s, %s, %s, 'subject', %s, %s)""",
            [document_id, tag_kind, name, subject_id, provenance],
        )
    else:
        db_exec(
            conn,
            "UPDATE maludb_document_tag SET tag_object_type = 'subject', tag_object_id = %s WHERE tag_id = %s",
            [subject_id, int(tag["tag_id"])],
        )

    return subject_id


# ---------------------------------------------------------------------------
# document_unlink_subject — remove edge + soft tag + repoint primary
# ---------------------------------------------------------------------------

def document_unlink_subject(
    conn: psycopg.Connection,
    document_id: int,
    tag_kind: str,
    name: str,
    provenance: str = "provided",
) -> None:
    """Remove a document-to-subject link by name.

    Delete the edge, delete the soft tag row, and if the subject was the
    document's primary project, repoint primary_project_id to the first
    remaining project tag (else NULL).  No-op when the link does not exist.

    MUST run inside db_tx_core().  Mirrors PHP's document_unlink_subject().
    """
    name = name.strip()
    if not name:
        return

    spec = document_link_spec(tag_kind)
    if spec is None:
        json_error("validation_failed", f'Unsupported document link kind "{tag_kind}".', 422)
    _, verb = spec  # type: ignore[misc]

    row = db_one(conn, "SELECT subject_id FROM maludb_subject WHERE canonical_name = %s", [name])
    if row is not None:
        subject_id = int(row["subject_id"])
        verb_id = int(
            db_one(conn, "SELECT maludb_core.resolve_svpor_verb(%s) AS id", [verb])["id"]  # type: ignore[index]
        )
        stmt = db_one(
            conn,
            """SELECT statement_id FROM maludb_svpor_statement
              WHERE subject_kind = 'document' AND subject_id = %s
                AND object_kind  = 'subject'  AND object_id  = %s AND verb_id = %s""",
            [document_id, subject_id, verb_id],
        )
        if stmt is not None:
            db_one(
                conn,
                "SELECT maludb_svpor_statement_delete(%s) AS d",
                [int(stmt["statement_id"])],
            )
        # If this was the primary project, repoint to the first OTHER project tag (else NULL).
        db_exec(
            conn,
            """UPDATE maludb_document SET primary_project_id = (
                 SELECT t.tag_object_id FROM maludb_document_tag t
                  WHERE t.document_id = %s AND t.tag_kind = 'project'
                    AND t.tag_value <> %s AND t.tag_object_id IS NOT NULL
                  ORDER BY t.tag_id LIMIT 1)
              WHERE document_id = %s AND primary_project_id = %s""",
            [document_id, name, document_id, subject_id],
        )

    db_exec(
        conn,
        """DELETE FROM maludb_document_tag
          WHERE document_id = %s AND tag_kind = %s AND tag_value = %s AND provenance = %s""",
        [document_id, tag_kind, name, provenance],
    )


# ---------------------------------------------------------------------------
# document_neighbors — documents linked through the unified graph
# ---------------------------------------------------------------------------

def document_neighbors(conn: psycopg.Connection, subject_id: int) -> list[dict[str, Any]]:
    """Fetch documents linked to a subject through the unified graph.

    Returns [{id, title, rel}], one row per document (first rel kept).
    MUST run inside db_tx_core().  Mirrors PHP's document_neighbors().
    """
    rows = db_query(
        conn,
        """SELECT neighbor_id, label, rel
           FROM maludb_graph_neighbors('subject', %s, 'both', ARRAY['concerns','mentions','involves'])
          WHERE neighbor_kind = 'document'
          ORDER BY neighbor_id""",
        [subject_id],
    )
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for r in rows:
        nid = int(r["neighbor_id"])
        if nid in seen:
            continue
        seen.add(nid)
        out.append({"id": nid, "title": r["label"], "rel": r["rel"]})
    return out
