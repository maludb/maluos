"""
Subject types an ingest may use (M12).

The core refuses a statement whose subject type is not in the tenant's subject-type catalogue ("unknown subject_type
product. Register it in malu$svpor_subject_type first"). A model told to type its subjects with a host's own vocabulary
(a knowledge base's "product", "policy", "place") would have every such statement refused, so the documents route
resolves the types an extraction uses before it ingests, the way POST /v1/graph/import already does: an unseen type is
registered when the core can register one (maludb_register_subject_type, core >= 0.102.0) and its name is a valid
catalogue name; otherwise it falls back to the namespace's default type, or a generic one, and the declared type is kept
as a predicate attribute so nothing the model said is lost.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

REGISTRABLE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


def slug_of(declared: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", declared.strip().lower())


def resolve_subject_types(
    conn: Any, declared: list[str], default_subject: str, query: Callable[..., list[dict]]
) -> dict[str, str]:
    """declared type -> the type to ingest under. Registers what it can (inside the caller's transaction)."""
    catalog = {r["subject_type"] for r in query(conn, "SELECT subject_type FROM maludb_subject_type")}
    can_register = bool(query(conn, "SELECT to_regproc('maludb_register_subject_type') IS NOT NULL AS ok")[0]["ok"])
    generic = next((t for t in ("other", "concept") if t in catalog), default_subject)
    fallback = default_subject if default_subject in catalog else generic
    out: dict[str, str] = {}
    for d in declared:
        if d in out:
            continue
        if d in catalog:
            out[d] = d
            continue
        slug = slug_of(d)
        if slug in catalog:
            out[d] = slug
        elif can_register and REGISTRABLE.match(slug):
            query(conn, "SELECT maludb_register_subject_type(%s) AS registered", [slug])
            catalog.add(slug)
            out[d] = slug
        else:
            out[d] = fallback
    return out
