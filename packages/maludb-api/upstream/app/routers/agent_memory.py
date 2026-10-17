"""
Agent memory — remember and recall, for callers that are not an extraction pipeline.

An agent fleet needs two things the document pipeline makes awkward:

  POST /v1/memory/remember   store a piece of text so it can be found again — NO LLM CALL. The caller
                             says what it is about (subject) and the text itself is what is embedded
                             and returned. Until now a recallable write either cost an extraction
                             call (/v1/memory/ingest, /v1/memory/documents) or required the caller to
                             hand-build `edges` with a `source_span`, a bypass nothing documented.
  POST /v1/memory/recall     search SEVERAL namespaces in one call, with or without a subject. A host
                             that scopes memory by namespace (one per agent, per department, one for
                             the organisation) recalls across the caller's whole scope set at once.

Both are thin: remember() builds the edges and calls documents_core(); recall() calls search_core()
per namespace and merges. No new SQL surface, so they inherit every rule the pipeline already has.

Free-text recall, honestly: maludb_memory_search() is compartmented — it REQUIRES a subject or a
verb — and a tenant role cannot enumerate its compartments. So when the caller names neither,
recall() proposes subjects by trigram similarity between the query and maludb_subject names,
searches those, and says which it tried (`subjects_tried`). A query that names nothing the tenant
knows returns no results and says so; a compartment-free search over a namespace needs an extension
function (planned for maludb_core 0.106.0). Namespaces are labels, not access control: whoever
holds the tenant token can name any of them. The HOST decides which namespaces a caller may pass.

SQL (all through existing cores):
    maludb_upload_document(...) + maludb_memory_ingest_edge(... p_namespace ...)   via documents_core
    maludb_memory_search(p_query_embedding, p_subject, p_verb, p_namespace, ...)  via search_core
    SELECT canonical_name, word_similarity(...) FROM maludb_subject                (candidates)
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_query
from app.errors import json_error
from app.helpers.llm import mem_chunk
from app.routers.memory import documents_core, search_core

router = APIRouter()

MAX_NAMESPACES = 16
MAX_SUBJECTS = 8
DEFAULT_VERB = "noted"


def _names(value, field: str, limit: int) -> list[str]:
    """A string or a list of strings -> a clean, de-duplicated list."""
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in out:
            out.append(name)
    if len(out) > limit:
        json_error("validation_failed", f'At most {limit} entries in "{field}".', 422)
    return out


def build_remember_edges(
    text: str, subjects: list[str], verb: str, subject_type: str | None, chunk_max: int, chunk_overlap: int
) -> list[dict]:
    """One edge per (subject, chunk). `source_span` is what gets embedded AND what recall returns,
    so it is the text itself — not "subject verb", which is all the pipeline would embed for an
    edge that arrives without one."""
    chunks = mem_chunk(text, chunk_max, chunk_overlap) or [text]
    edges = []
    for subject in subjects:
        for chunk in chunks:
            edge = {"subject_text": subject, "verb_text": verb, "source_span": chunk, "provenance": "provided"}
            if subject_type:
                edge["subject_type"] = subject_type
            edges.append(edge)
    return edges


def merge_recall(per_namespace: list[tuple[str, list[dict]]], limit: int) -> list[dict]:
    """Best first across namespaces; the same chunk found through two subjects is reported once."""
    seen: set[tuple[str, int]] = set()
    merged: list[dict] = []
    for namespace, rows in per_namespace:
        for row in rows:
            key = (namespace, int(row.get("chunk_id") or 0))
            if key in seen:
                continue
            seen.add(key)
            merged.append({**row, "namespace": namespace})
    merged.sort(key=lambda r: (r.get("similarity") is None, -(r.get("similarity") or 0.0)))
    for rank, row in enumerate(merged[:limit], start=1):
        row["rank_no"] = rank
    return merged[:limit]


# ===========================================================================
# POST /v1/memory/remember
# ===========================================================================


@router.post("/v1/memory/remember")
async def memory_remember(auth: Auth, request: Request):
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if not text:
        json_error("missing_field", 'Field "text" is required.', 400)
    subjects = _names(
        body.get("subjects") if body.get("subjects") is not None else body.get("subject"), "subjects", MAX_SUBJECTS
    )
    if not subjects:
        json_error(
            "missing_field",
            'Say what this is about: "subject" (or "subjects") is required. '
            "It is the compartment the memory is filed and found under.",
            400,
        )
    verb = str(body.get("verb") or DEFAULT_VERB).strip() or DEFAULT_VERB
    namespace = str(body.get("namespace") or "default").strip() or "default"
    chunk_cfg = body.get("chunk") if isinstance(body.get("chunk"), dict) else {}
    chunk_max = max(200, int(chunk_cfg.get("max", 2000)))
    chunk_overlap = max(0, int(chunk_cfg.get("overlap", 200)))

    payload = documents_core(
        auth,
        title=str(body.get("title") or "").strip() or text[:80],
        text=text,
        source_type=str(body.get("source_type") or "note").strip() or "note",
        media_type=None,
        document_type=None,
        metadata_json=json.dumps(body["metadata"]) if isinstance(body.get("metadata"), dict) else "{}",
        projects=_names(body.get("projects"), "projects", 16),
        subjects=subjects,
        verbs=[verb],
        events=[],
        chunk_max=chunk_max,
        chunk_overlap=chunk_overlap,
        embedding_model=str(body.get("embedding_model") or "").strip() or None,
        explicit_model=None,
        provided_edges=build_remember_edges(
            text, subjects, verb, str(body.get("subject_type") or "").strip() or None, chunk_max, chunk_overlap
        ),
        namespace=namespace,
    )
    return JSONResponse(
        status_code=201,
        content={
            "document_id": payload.get("document_id"),
            "namespace": payload.get("namespace", namespace),
            "embedding_model": payload.get("embedding_model"),
            "subjects": subjects,
            "verb": verb,
            "chunk_count": payload.get("chunk_count"),
            "statements": len(payload.get("edges") or []),
            "extractor": "none",
        },
    )


# ===========================================================================
# POST /v1/memory/recall
# ===========================================================================


def _candidate_subjects(auth, query: str, limit: int) -> list[dict]:
    rows = db_query(
        auth.conn,
        """SELECT canonical_name AS name, word_similarity(canonical_name, %s)::float8 AS score
             FROM maludb_subject
            WHERE word_similarity(canonical_name, %s) >= 0.45
            ORDER BY score DESC, length(canonical_name) DESC
            LIMIT %s""",
        [query, query, limit],
    )
    return [{"name": r["name"], "score": round(float(r["score"]), 3)} for r in rows]


@router.post("/v1/memory/recall")
async def memory_recall(auth: Auth, request: Request):
    body = await request.json()
    query = str(body.get("query") or "").strip()
    if not query:
        json_error("missing_field", 'Field "query" is required.', 400)
    namespaces = _names(
        body.get("namespaces") if body.get("namespaces") is not None else body.get("namespace"),
        "namespaces",
        MAX_NAMESPACES,
    ) or ["default"]
    subjects = _names(
        body.get("subjects") if body.get("subjects") is not None else body.get("subject"), "subjects", MAX_SUBJECTS
    )
    verb = str(body.get("verb") or "").strip() or None
    limit = min(50, max(1, int(body.get("limit", 8))))
    metric = str(body.get("metric") or "cosine").strip() or "cosine"
    embedding_model = str(body.get("embedding_model") or "").strip() or None

    proposed: list[dict] = []
    if not subjects and not verb:
        proposed = _candidate_subjects(auth, query, MAX_SUBJECTS)
        subjects = [c["name"] for c in proposed]
        if not subjects:
            return {
                "query": query,
                "namespaces": namespaces,
                "subjects_tried": [],
                "results": [],
                "note": "The query names no subject this tenant knows, and memory search is "
                'compartmented by subject or verb. Pass "subject" or "verb".',
            }

    per_namespace: list[tuple[str, list[dict]]] = []
    used_model = None
    for namespace in namespaces:
        for subject in subjects or [None]:
            found = search_core(
                auth,
                query=query,
                subject=subject,
                verb=verb,
                namespace=namespace,
                limit=limit,
                metric=metric,
                embedding_model=embedding_model,
            )
            used_model = found.get("embedding_model")
            per_namespace.append((namespace, found["results"]))

    return {
        "query": query,
        "namespaces": namespaces,
        "subjects_tried": subjects,
        "subjects_proposed": proposed,
        "verb": verb,
        "embedding_model": used_model,
        "results": merge_recall(per_namespace, limit),
    }
