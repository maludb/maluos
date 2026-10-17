"""
Memory pipeline endpoints — config, documents, search, ingest.

Ports PHP's memory_config.php, memory_documents.php, memory_search.php,
memory_ingest.php.  The API is the model worker: it chunks text, calls the
LLM (extraction) and the embedding model, then writes results back via the
maludb_* facades.

Endpoints:
    GET  /v1/memory/config     — read namespace config
    POST /v1/memory/config     — full config setup (secret + provider + alias + bind)
    PUT  /v1/memory/config     — same as POST
    POST /v1/memory/documents  — upload + chunk + extract + embed + ingest
    POST /v1/memory/search     — embed query + vector search
    POST /v1/memory/ingest     — text -> LLM pipeline (per-model prompt)
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app import config
from app.auth import Auth, get_auth_store
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error
from app.helpers.llm import (
    llm_complete,
    llm_json_from_text,
    mem_chunk,
    mem_embed,
    mem_extract,
    mem_resolve_token,
    mem_vector_literal,
)
from app.helpers.llm_resolve import resolve_embed_config, resolve_task_config
from app.helpers.subject_types import resolve_subject_types

router = APIRouter()


# ---------------------------------------------------------------------------
# Two model stores, with cross-fallback
# ---------------------------------------------------------------------------
#
# Model configuration lives in two independent stores:
#
#   Store A — Postgres per-namespace config (maludb_memory_model_config).
#             Primary for /v1/memory/documents and /v1/memory/search.
#   Store B — SQLite model_prompts (auth_store.model_prompt).
#             Primary for /v1/memory/ingest (and the skills pipeline).
#
# A tenant may have set up only one of them.  These helpers let each endpoint
# borrow the *LLM connection* (base_url / model / token / generation_params /
# api_format) from the other store when its own store is empty, so a partial
# setup does not produce hard "model_not_configured" errors.  The prompt itself
# is never crossed over: each endpoint keeps its own contract (candidate_edges
# for documents, the ingest-extraction JSON for ingest).

# Default ingest system prompt, used when /v1/memory/ingest falls back to the
# namespace store (which has no ingest-contract prompt of its own).
_DEFAULT_INGEST_PROMPT_FILE = config.PROJECT_ROOT / "config" / "prompts" / "chatgpt-4o.system.txt"
_FALLBACK_INGEST_PROMPT = (
    "You are a memory-extraction service. Convert the TEXT plus CONTEXT HINTS into a "
    "SINGLE JSON object describing the entities, events, and relationships it contains, "
    "ingestible directly into a knowledge graph. Output ONLY one JSON object — no prose, "
    "no markdown. Choose subject types from these ENTITY TYPES:\n{{ENTITY_TYPES}}\n"
    "and these EVENT KINDS:\n{{EVENT_KINDS}}\nUse small canonical verbs and reuse "
    "KNOWN_SUBJECTS / KNOWN_VERBS where they match. Do not invent details."
)


def _namespace_config(conn, namespace: str) -> dict:
    """Read the Postgres per-namespace model config (Store A); {} if none set."""
    row = db_tx_core(conn, lambda c: db_one(c, "SELECT maludb_memory_model_config(%s) AS cfg", [namespace]))
    if row and row["cfg"] is not None:
        cfg = row["cfg"] if isinstance(row["cfg"], dict) else json.loads(row["cfg"])
        if isinstance(cfg, dict):
            return cfg
    return {}


def _has_llm_connection(cfg_raw: dict) -> bool:
    """True if a namespace config carries a usable extraction connection."""
    return bool(str(cfg_raw.get("base_url") or "").strip() and str(cfg_raw.get("model_identifier") or "").strip())


def _default_ingest_prompt() -> str:
    """The ingest-contract system prompt to use when no model_prompt is configured."""
    try:
        text = _DEFAULT_INGEST_PROMPT_FILE.read_text()
        return text if text.strip() else _FALLBACK_INGEST_PROMPT
    except OSError:
        return _FALLBACK_INGEST_PROMPT


# ---------------------------------------------------------------------------
# GET /v1/memory/config — read namespace config
# ---------------------------------------------------------------------------


@router.get("/v1/memory/config")
def get_memory_config(auth: Auth, namespace: str = "default"):
    row = db_tx_core(auth.conn, lambda c: db_one(c, "SELECT maludb_memory_model_config(%s) AS cfg", [namespace]))
    cfg = None
    if row and row["cfg"] is not None:
        cfg = row["cfg"] if isinstance(row["cfg"], dict) else json.loads(row["cfg"])
    return {"namespace": namespace, "config": cfg}


# ---------------------------------------------------------------------------
# POST/PUT /v1/memory/config — full config setup
# ---------------------------------------------------------------------------


@router.post("/v1/memory/config")
@router.put("/v1/memory/config")
async def set_memory_config(auth: Auth, request: Request):
    body = await request.json()

    namespace = str(body.get("namespace") or "default").strip() or "default"
    _sn = body.get("secret_name")
    secret_name = str(_sn).strip() if _sn and str(_sn).strip() else None
    token = str(body["token"]) if "token" in body and body["token"] is not None else None

    provider = body.get("provider") if isinstance(body.get("provider"), dict) else {}
    alias = body.get("alias") if isinstance(body.get("alias"), dict) else {}

    prov_name = str(provider.get("name", "")).strip()
    prov_kind = str(provider.get("kind", "")).strip()
    prov_adapter = str(provider["adapter_name"]) if provider.get("adapter_name") is not None else None
    prov_sens = str(provider.get("data_sensitivity", "")).strip() or "internal"

    alias_name = str(alias.get("name", "")).strip()
    alias_model = str(alias.get("model_identifier", "")).strip()
    alias_ctx = int(alias["context_length"]) if alias.get("context_length") is not None else None
    base_url = str(alias.get("base_url", "")).strip()

    embedding_model = str(body.get("embedding_model", "")).strip()
    _pt = body.get("prompt_template")
    prompt_template = str(_pt) if "prompt_template" in body and _pt is not None else None
    gen_params = json.dumps(body["generation_params"]) if isinstance(body.get("generation_params"), dict) else "{}"
    default_subject = str(body.get("default_subject_type", "")).strip() or "other"
    default_prov = str(body.get("default_provenance", "")).strip() or "suggested"

    # Shape validation
    if not prov_name or not prov_kind:
        json_error("missing_field", "provider.name and provider.kind are required.", 400)
    if not alias_name or not alias_model:
        json_error("missing_field", "alias.name and alias.model_identifier are required.", 400)
    if not base_url:
        json_error("missing_field", "alias.base_url is required.", 400)
    if not embedding_model:
        json_error("missing_field", '"embedding_model" is required.', 400)
    if prompt_template is not None and "{{chunk}}" not in prompt_template:
        json_error("validation_failed", "prompt_template must contain the {{chunk}} placeholder.", 422)
    if token is not None and secret_name is None:
        json_error("missing_field", '"secret_name" is required when a token is provided.', 400)

    def _setup(conn):
        # 1. Store the token encrypted (redacted from logs).
        if token is not None:
            db_one(
                conn,
                "SELECT secret_id FROM maludb_core.secret_set(p_name => %s, p_kind => 'provider', p_value => %s)",
                [secret_name, token],
            )
        # 2. Register the provider.
        db_one(
            conn,
            """SELECT maludb_register_model_provider(
                        p_name => %s, p_kind => %s, p_adapter_name => %s,
                        p_secret_ref => %s, p_data_sensitivity => %s) AS id""",
            [prov_name, prov_kind, prov_adapter, secret_name, prov_sens],
        )
        # 3. Register the alias.
        db_one(
            conn,
            """SELECT maludb_register_model_alias(
                        p_alias => %s, p_provider => %s, p_model_identifier => %s,
                        p_context_length => %s, p_runtime_params => jsonb_build_object('base_url', %s::text)) AS id""",
            [alias_name, prov_name, alias_model, alias_ctx, base_url],
        )
        # 4. Bind alias + prompt + embedding + defaults.
        db_one(
            conn,
            """SELECT maludb_memory_set_model_config(
                        p_extraction_alias     => %s,
                        p_prompt_template      => %s,
                        p_embedding_model      => %s,
                        p_namespace            => %s,
                        p_generation_params    => %s::jsonb,
                        p_default_subject_type => %s,
                        p_default_provenance   => %s) AS cfg""",
            [alias_name, prompt_template, embedding_model, namespace, gen_params, default_subject, default_prov],
        )
        # 5. Read it back.
        row = db_one(conn, "SELECT maludb_memory_model_config(%s) AS cfg", [namespace])
        if row and row["cfg"] is not None:
            return row["cfg"] if isinstance(row["cfg"], dict) else json.loads(row["cfg"])
        return None

    cfg = db_tx_core(auth.conn, _setup)
    return {"namespace": namespace, "config": cfg}


# ---------------------------------------------------------------------------
# POST /v1/memory/documents — upload + chunk + extract + embed + ingest
# ---------------------------------------------------------------------------


def _to_text_array(v: Any) -> list[str]:
    """Normalize a list value to a list of trimmed, non-empty strings."""
    if not isinstance(v, list):
        return []
    return [s.strip() for s in v if isinstance(s, str) and s.strip()]


def _pg_text_array(items: list[str]) -> str:
    """Format a Python list as a Postgres text[] literal."""
    escaped = ['"' + s.replace('"', '\\"') + '"' for s in items]
    return "{" + ",".join(escaped) + "}"


@router.post("/v1/memory/documents")
async def memory_documents(auth: Auth, request: Request):
    body = await request.json()

    title = str(body.get("title", "")).strip()
    text = str(body.get("text", ""))
    if not title:
        json_error("missing_field", 'Field "title" is required.', 400)
    if not text.strip():
        json_error("missing_field", 'Field "text" is required.', 400)

    namespace = str(body.get("namespace") or "default").strip() or "default"
    source_type = str(body.get("source_type") or "document").strip() or "document"
    media_type = str(body["media_type"]) if body.get("media_type") is not None else None
    _dt = body.get("document_type")
    doc_type = str(_dt).strip() if _dt and str(_dt).strip() else None
    metadata = json.dumps(body["metadata"]) if isinstance(body.get("metadata"), dict) else "{}"

    chunk_cfg = body.get("chunk") if isinstance(body.get("chunk"), dict) else {}

    payload = documents_core(
        auth,
        title=title,
        text=text,
        source_type=source_type,
        media_type=media_type,
        document_type=doc_type,
        metadata_json=metadata,
        projects=_to_text_array(body.get("projects")),
        subjects=_to_text_array(body.get("subjects")),
        verbs=_to_text_array(body.get("verbs")),
        events=_to_text_array(body.get("events")),
        chunk_max=max(200, int(chunk_cfg.get("max", 2000))),
        chunk_overlap=max(0, int(chunk_cfg.get("overlap", 200))),
        embedding_model=(
            str(body["embedding_model"]).strip()
            if body.get("embedding_model") and str(body["embedding_model"]).strip()
            else None
        ),
        explicit_model=str(body.get("model") or "").strip() or None,
        provided_edges=body.get("edges") if isinstance(body.get("edges"), list) else None,
        namespace=namespace,
    )
    return JSONResponse(status_code=201, content=payload)


def documents_core(
    auth,
    *,
    title: str,
    text: str,
    source_type: str,
    media_type: str | None,
    document_type: str | None,
    metadata_json: str,
    projects: list[str],
    subjects: list[str],
    verbs: list[str],
    events: list[str],
    chunk_max: int,
    chunk_overlap: int,
    embedding_model: str | None,
    explicit_model: str | None,
    provided_edges: list | None,
    namespace: str,
) -> dict:
    """The documents pipeline (chunk → extract → embed → ingest), shared by the
    REST route and the MCP store_document tool.  Raises APIError on failure."""
    doc_type = document_type
    metadata = metadata_json

    # Model config — Store A (namespace) is primary here.
    cfg_raw = _namespace_config(auth.conn, namespace)

    # Embedding model precedence: caller > namespace config > the user's
    # 'embed' choice > env default.
    user_embed = resolve_embed_config(get_auth_store(), auth.user_id)
    embedding_model = (
        embedding_model
        or cfg_raw.get("embedding_model")
        or user_embed.get("embedding_model")
        or os.environ.get("MALUDB_EMBED_MODEL", "maludb-local-dev")
    )
    default_subject = cfg_raw.get("default_subject_type", "other")
    default_prov = cfg_raw.get("default_provenance", "suggested")

    # Extraction connection: Store A (namespace) first, else borrow from Store B
    # (model_prompts) so a tenant that only configured /v1/memory/ingest can still
    # extract here.  The candidate_edges contract (prompt_template) is never taken
    # from Store B — its prompt targets a different contract.
    if _has_llm_connection(cfg_raw):
        extract_cfg = {
            "api_format": "openai",
            "base_url": cfg_raw.get("base_url", ""),
            "model_identifier": cfg_raw.get("model_identifier", ""),
            "prompt_template": cfg_raw.get("prompt_template"),
            "generation_params": cfg_raw.get("generation_params", {}),
            "max_tokens": 2048,
            "token": mem_resolve_token(auth.conn, cfg_raw.get("secret_ref")),
        }
    else:
        # Borrow a connection from Store B: explicit model -> the user's
        # 'extract' choice -> the legacy 'chatgpt-4o' model_prompts row.
        # Only the connection crosses over — the candidate_edges contract
        # (prompt_template) never comes from Store B.
        fb_model = explicit_model
        store_b = get_auth_store()
        pr = resolve_task_config(store_b, auth.user_id, "extract", fb_model)
        if pr is None:
            pr = store_b.model_prompt(fb_model or "chatgpt-4o")
        if pr and str(pr.get("base_url") or "").strip():
            extract_cfg = {
                "api_format": pr.get("api_format", "openai"),
                "base_url": pr.get("base_url", ""),
                "model_identifier": pr.get("model_identifier") or pr.get("model_name") or "",
                "prompt_template": cfg_raw.get("prompt_template"),  # default candidate_edges template
                "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
                "max_tokens": int(pr.get("max_tokens", 2048)),
                "token": pr.get("api_key"),
            }
        else:
            # Neither store configured — only caller-supplied "edges" can be ingested;
            # mem_extract (if reached) raises model_not_configured.
            extract_cfg = {
                "api_format": "openai",
                "base_url": "",
                "model_identifier": "",
                "prompt_template": cfg_raw.get("prompt_template"),
                "generation_params": cfg_raw.get("generation_params", {}),
                "max_tokens": 2048,
                "token": mem_resolve_token(auth.conn, cfg_raw.get("secret_ref")),
            }

    model_id = str(extract_cfg.get("model_identifier") or "")
    # Embedding config — the user's stored embed connection (if any), with the
    # resolved embedding_model name on top.
    embed_cfg: dict[str, str] = {**user_embed, "embedding_model": embedding_model}

    # 1. Obtain candidate edges: caller-supplied (bypass) OR LLM extraction per chunk
    provided = provided_edges
    chunks = mem_chunk(text, chunk_max, chunk_overlap)

    edges: list[dict] = []
    extractor = "provided"
    if provided is not None:
        for e in provided:
            if isinstance(e, dict):
                edges.append(e)
    else:
        extractor = "llm"
        for chunk in chunks:
            for e in mem_extract(chunk, extract_cfg):
                if isinstance(e, dict):
                    if not e.get("source_span") or not str(e["source_span"]).strip():
                        e["source_span"] = chunk
                    edges.append(e)

    if not edges:
        json_error("no_edges", 'No SVPO edges to ingest (supply "edges" or configure an extraction model).', 422)

    # 2. Embed each edge
    for e in edges:
        span = str(e.get("source_span", "")).strip()
        if not span:
            span = (str(e.get("subject_text", "")) + " " + str(e.get("verb_text", ""))).strip()
        e["__vector"] = mem_vector_literal(mem_embed(span, embed_cfg))
        e["source_span"] = span

    # 3. One transaction per document: upload, then ingest every edge.
    def _ingest(conn):
        doc = db_one(
            conn,
            """SELECT maludb_upload_document(
                        p_title => %s, p_content_text => %s, p_source_type => %s,
                        p_media_type => %s, p_document_type => %s,
                        p_projects => %s::text[], p_subjects => %s::text[],
                        p_verbs => %s::text[], p_events => %s::text[],
                        p_metadata_jsonb => %s::jsonb) AS id""",
            [
                title,
                text,
                source_type,
                media_type,
                doc_type,
                _pg_text_array(projects),
                _pg_text_array(subjects),
                _pg_text_array(verbs),
                _pg_text_array(events),
                metadata,
            ],
        )
        document_id = int(doc["id"])

        # M12: an unseen subject type is registered (or falls back, the declared type kept as an attribute) — the core
        # refuses a type its catalogue lacks, and a host's vocabulary types (product, policy …) are not in it.
        declared = [str(e.get("subject_type", "")).strip() or default_subject for e in edges]
        type_of = resolve_subject_types(conn, declared, default_subject, db_query)

        out: list[dict] = []
        for e in edges:
            subject_text = str(e.get("subject_text", "")).strip()
            verb_text = str(e.get("verb_text", "")).strip()
            if not subject_text or not verb_text:
                json_error("validation_failed", "Each edge needs subject_text and verb_text.", 422)

            declared_ty = str(e.get("subject_type", "")).strip() or default_subject
            subject_ty = type_of.get(declared_ty, declared_ty)
            pred_list = list(e["predicate"]) if isinstance(e.get("predicate"), list) else []
            if subject_ty != declared_ty and subject_ty != declared_ty.lower():
                pred_list.append({"attr_name": "declared_subject_type", "value_text": declared_ty})
            predicate = json.dumps(pred_list)
            confidence = str(e["confidence"]) if "confidence" in e and e["confidence"] is not None else None
            provenance = str(e.get("provenance", "")).strip() or default_prov
            extr_model = model_id if model_id else extractor

            st = db_one(
                conn,
                """SELECT maludb_memory_ingest_edge(
                            p_source_kind      => 'document', p_source_id => %s,
                            p_subject_text     => %s, p_verb_text => %s,
                            p_predicate        => %s::jsonb,
                            p_embedding        => %s::maludb_core.malu_vector,
                            p_embedding_model  => %s,
                            p_subject_type     => %s,
                            p_source_span      => %s,
                            p_confidence       => %s::numeric,
                            p_provenance       => %s,
                            p_extraction_model => %s,
                            p_namespace        => %s,
                            p_document_id      => %s) AS statement_id""",
                [
                    document_id,
                    subject_text,
                    verb_text,
                    predicate,
                    e["__vector"],
                    embedding_model,
                    subject_ty,
                    str(e["source_span"]),
                    confidence,
                    provenance,
                    extr_model,
                    namespace,
                    document_id,
                ],
            )
            out.append(
                {
                    "statement_id": int(st["statement_id"]),
                    "subject_text": subject_text,
                    "verb_text": verb_text,
                    "subject_type": subject_ty,
                    "provenance": provenance,
                }
            )
        return {"document_id": document_id, "edges": out}

    result = db_tx_core(auth.conn, _ingest)

    return {
        "document_id": result["document_id"],
        "namespace": namespace,
        "embedding_model": embedding_model,
        "extractor": extractor,
        "chunk_count": len(chunks),
        "edges": result["edges"],
    }


# ---------------------------------------------------------------------------
# POST /v1/memory/search — embed query, vector search
# ---------------------------------------------------------------------------


@router.post("/v1/memory/search")
async def memory_search(auth: Auth, request: Request):
    body = await request.json()

    query = str(body.get("query", ""))
    if not query.strip():
        json_error("missing_field", 'Field "query" is required.', 400)

    namespace = str(body.get("namespace") or "default").strip() or "default"
    subject = str(body["subject"]).strip() if body.get("subject") and str(body["subject"]).strip() else None
    verb = str(body["verb"]).strip() if body.get("verb") and str(body["verb"]).strip() else None

    if subject is None and verb is None:
        json_error("missing_field", 'Provide "subject" and/or "verb" — the compartment pre-filter is required.', 400)

    limit = max(1, min(200, int(body.get("limit", 20))))
    metric = str(body.get("metric") or "cosine").strip() or "cosine"

    return search_core(
        auth,
        query=query,
        subject=subject,
        verb=verb,
        namespace=namespace,
        limit=limit,
        metric=metric,
        embedding_model=(
            str(body["embedding_model"]).strip()
            if body.get("embedding_model") and str(body["embedding_model"]).strip()
            else None
        ),
    )


# A deleted document's vector chunks outlive it: DELETE /v1/documents/{id} removes the document
# and its graph edges, but the chunks sit in a core table no tenant role can touch and no facade
# removes (maludb_core <= 0.105.x), and the engine's exact-scan path ignores tombstones. Until the
# extension deletes them itself, search must not return them — a deleted memory that is still
# recalled is a privacy defect, not a ranking one.
SEARCH_OVERFETCH = 3
SEARCH_FETCH_MAX = 600


def drop_deleted_documents(rows: list[dict], live_documents: set[int], limit: int) -> list[dict]:
    """Keep a hit when it names no document (a statement-only chunk) or its document still
    exists; cut to *limit*; renumber rank_no so the ranks a caller sees are contiguous."""
    kept = [r for r in rows if r.get("document_id") is None or r["document_id"] in live_documents][:limit]
    for rank, r in enumerate(kept, start=1):
        r["rank_no"] = rank
    return kept


def resolve_query_vector(auth, query: str, namespace: str, embedding_model: str | None) -> tuple[str, str]:
    """(embedding model name, the query's vector literal).  Same embedding model (and precedence) as document
    ingest: caller > namespace config > the user's 'embed' choice > env default."""
    cfg_raw = _namespace_config(auth.conn, namespace)
    user_embed = resolve_embed_config(get_auth_store(), auth.user_id)
    embedding_model = (
        embedding_model
        or cfg_raw.get("embedding_model")
        or user_embed.get("embedding_model")
        or os.environ.get("MALUDB_EMBED_MODEL", "maludb-local-dev")
    )
    return embedding_model, mem_vector_literal(mem_embed(query, {**user_embed, "embedding_model": embedding_model}))


def search_core(
    auth,
    *,
    query: str,
    subject: str | None,
    verb: str | None,
    namespace: str,
    limit: int,
    metric: str,
    embedding_model: str | None,
    vector: str | None = None,
) -> dict:
    """Embed the query and run the vector search, shared by the REST route and
    the MCP search_memory tool.  Raises APIError on failure.  A caller that searches several
    compartments for one question embeds it once (resolve_query_vector) and passes `vector`."""
    if vector is None:
        embedding_model, vector = resolve_query_vector(auth, query, namespace, embedding_model)

    # Ask for more than was wanted: chunks of deleted documents are dropped below, and a
    # search that loses some must still be able to fill its limit.
    fetch = min(limit * SEARCH_OVERFETCH, SEARCH_FETCH_MAX)

    def _search(c):  # noqa: ANN001, ANN202
        found = db_query(
            c,
            """SELECT chunk_id, statement_id, document_id, source_text, distance, similarity,
                    rank_no, subject_name, verb_name
               FROM maludb_memory_search(
                        p_query_embedding => %s::maludb_core.malu_vector,
                        p_subject         => %s,
                        p_verb            => %s,
                        p_namespace       => %s,
                        p_limit           => %s,
                        p_metric          => %s)""",
            [vector, subject, verb, namespace, fetch, metric],
        )
        doc_ids = sorted({int(r["document_id"]) for r in found if r["document_id"] is not None})
        live = (
            db_query(c, "SELECT document_id FROM maludb_document WHERE document_id = ANY(%s)", [doc_ids])
            if doc_ids
            else []
        )
        return found, {int(r["document_id"]) for r in live}

    rows, live_documents = db_tx_core(auth.conn, _search)
    for r in rows:
        for k in ("chunk_id", "statement_id", "document_id", "rank_no"):
            r[k] = int(r[k]) if r[k] is not None else None
        for k in ("distance", "similarity"):
            r[k] = float(r[k]) if r[k] is not None else None
    rows = drop_deleted_documents(rows, live_documents, limit)

    return {
        "namespace": namespace,
        "embedding_model": embedding_model,
        "results": rows,
    }


# ---------------------------------------------------------------------------
# POST /v1/memory/ingest — text -> LLM pipeline (per-model prompt)
# ---------------------------------------------------------------------------


@router.post("/v1/memory/ingest")
async def memory_ingest(auth: Auth, request: Request):
    body = await request.json()

    text = str(body.get("text", ""))
    if not text.strip():
        json_error("missing_field", 'Field "text" is required.', 400)

    explicit_model = str(body.get("model") or "").strip() or None
    namespace = str(body.get("namespace") or "default").strip() or "default"
    preview = bool(body.get("preview"))
    source_type = str(body.get("source_type") or "document").strip() or "document"
    title = str(body.get("title") or "").strip()

    # Hints
    hints_raw = body.get("hints")
    if isinstance(hints_raw, list):
        hints_json = json.dumps(hints_raw)
    elif isinstance(hints_raw, str) and hints_raw.strip():
        decoded = None
        try:
            decoded = json.loads(hints_raw)
        except (json.JSONDecodeError, ValueError):
            pass
        if isinstance(decoded, list):
            hints_json = json.dumps(decoded)
        else:
            hints_json = json.dumps([{"subject-type": "note", "subject-name": hints_raw}])
    else:
        hints_json = "[]"

    payload = ingest_core(
        auth,
        text=text,
        hints_json=hints_json,
        namespace=namespace,
        explicit_model=explicit_model,
        preview=preview,
        source_type=source_type,
        title=title or None,
    )
    if preview:
        return payload
    return JSONResponse(status_code=201, content=payload)


def ingest_takes_namespace(conn) -> bool:
    """True when the tenant's maludb_memory_ingest_extraction has p_namespace (maludb_core 0.106.0)."""
    row = db_one(
        conn,
        """SELECT EXISTS(SELECT 1 FROM pg_proc p
                          WHERE p.proname = 'maludb_memory_ingest_extraction'
                            AND p.pronamespace = current_schema()::regnamespace
                            AND 'p_namespace' = ANY (p.proargnames)) AS ok""",
    )
    return bool(row and row["ok"])


def ingest_namespace_report(requested: str, applied: bool = False) -> dict:
    """What /v1/memory/ingest may truthfully say about the namespace it was given.

    maludb_memory_ingest_extraction(jsonb, text, bigint, text) takes no namespace, so every edge this
    route writes lands in 'default' whatever the caller asked for. The route used to echo the
    requested value back, which reads as "stored there" — and a caller scoping memory by namespace
    (one per agent or department) would believe a write was private when it was not. Until the
    extension function grows p_namespace (as maludb_memory_ingest_edge already has, which is why
    /v1/memory/documents is unaffected), say what happened instead.
    """
    if requested == "default" or applied:
        return {"namespace": requested}
    return {
        "namespace": "default",
        "namespace_requested": requested,
        "namespace_applied": False,
        "warnings": [
            f"namespace '{requested}' was not applied: /v1/memory/ingest stores into 'default'. "
            "Use /v1/memory/documents for namespaced writes."
        ],
    }


def ingest_core(
    auth,
    *,
    text: str,
    hints_json: str,
    namespace: str,
    explicit_model: str | None,
    preview: bool,
    source_type: str = "document",
    title: str | None = None,
) -> dict:
    """The ingest pipeline (resolve model → assemble prompt → LLM → graph
    ingest), shared by the REST route and the MCP store_memory tool.  Returns
    the response payload dict; raises APIError on failure."""
    # Per-model prompt + LLM connection.  Resolution order: explicit model
    # (legacy model_prompts first, then the seeded catalog + the user's
    # provider key) -> the user's 'extract' choice -> the legacy default
    # ('chatgpt-4o' model_prompts row) -> the namespace config (Store A).
    store = get_auth_store()
    pr = resolve_task_config(store, auth.user_id, "extract", explicit_model)
    model = pr["model_name"] if pr is not None else (explicit_model or "chatgpt-4o")
    if pr is None:
        pr = store.model_prompt(model)
    if pr is None:
        # No model_prompt: fall back to Store A (the Postgres namespace config).
        # Borrow its LLM connection and pair it with the default ingest system
        # prompt — the namespace prompt_template targets the candidate_edges
        # contract, not the ingest contract, so it is not reused here.
        cfg_raw = _namespace_config(auth.conn, namespace)
        if _has_llm_connection(cfg_raw):
            pr = {
                "model_name": model,
                "model_identifier": cfg_raw.get("model_identifier") or model,
                "api_format": "openai",
                "system_prompt": _default_ingest_prompt(),
                "base_url": cfg_raw.get("base_url", ""),
                "api_key": mem_resolve_token(auth.conn, cfg_raw.get("secret_ref")),
                "max_tokens": 2048,
                "generation_params": json.dumps(cfg_raw.get("generation_params") or {}),
            }
        else:
            msg = (
                f'No prompt configured for model "{model}" and no model config for '
                f'namespace "{namespace}". Set one via POST /v1/model-prompts or POST /v1/memory/config.'
            )
            json_error("model_not_configured", msg, 422)

    # Known subjects / verbs from Postgres
    subj_rows = db_query(
        auth.conn,
        "SELECT canonical_name AS name, subject_type AS type FROM maludb_subject ORDER BY canonical_name",
    )
    verb_rows = db_query(auth.conn, "SELECT canonical_name FROM maludb_verb ORDER BY canonical_name")
    known_subjects_json = json.dumps([{"name": r["name"], "type": r["type"]} for r in subj_rows], ensure_ascii=False)
    known_verbs_json = json.dumps([r["canonical_name"] for r in verb_rows], ensure_ascii=False)

    # Subject type catalog (0.96.0)
    try:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description FROM maludb_subject_type ORDER BY category, sort_order",
        )
    except Exception:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description"
            " FROM maludb_core.malu$svpor_subject_type ORDER BY category, sort_order",
        )

    entity_lines: list[str] = []
    event_lines: list[str] = []
    for r in type_rows:
        desc = " — " + r["description"] if r.get("description") and str(r["description"]).strip() else ""
        line = f"  - {r['subject_type']}{desc}"
        if (r.get("category") or "entity") == "event":
            event_lines.append(line)
        else:
            entity_lines.append(line)

    entity_block = "\n".join(entity_lines) if entity_lines else "  - other"
    event_block = "\n".join(event_lines) if event_lines else "  - task"

    # Build the messages
    system_prompt = str(pr.get("system_prompt", ""))
    system = system_prompt.replace("{{ENTITY_TYPES}}", entity_block).replace("{{EVENT_KINDS}}", event_block)
    user_msg = (
        f"TEXT:\n{text}\n\nHINTS:\n{hints_json}\n\n"
        f"KNOWN_SUBJECTS:\n{known_subjects_json}\n\nKNOWN_VERBS:\n{known_verbs_json}\n"
    )

    if preview:
        return {
            "model": model,
            "api_format": pr.get("api_format", "openai"),
            "system_prompt": system,
            "user_message": user_msg,
            "counts": {
                "known_subjects": len(subj_rows),
                "known_verbs": len(verb_rows),
                "entity_types": len(entity_lines),
                "event_kinds": len(event_lines),
            },
        }

    if not pr.get("api_key"):
        if pr.get("source") in ("catalog_explicit", "user_choice"):
            msg = (
                f'No API key stored for provider "{pr.get("provider")}".'
                f" Set one via PUT /v1/llm/providers/{pr.get('provider')}."
            )
        else:
            msg = f'No API key set for model "{model}". Set it via POST /v1/model-prompts.'
        json_error("model_api_key_missing", msg, 409)

    # Verify maludb_memory_ingest_extraction is available
    has_facade = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_memory_ingest_extraction') AS ok",
    )
    if not has_facade or not has_facade["ok"]:
        json_error(
            "ingest_unavailable",
            "maludb_memory_ingest_extraction is not available in this database (requires maludb_core 0.92.0).",
            501,
        )

    # Call the LLM
    llm_cfg: dict[str, Any] = {
        "api_format": pr.get("api_format", "openai"),
        "base_url": pr.get("base_url", ""),
        "model_identifier": pr.get("model_identifier") or model,
        "token": pr["api_key"],
        "max_tokens": int(pr.get("max_tokens", 2048)),
        "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
    }
    content = llm_complete(llm_cfg, system, user_msg)
    extraction = llm_json_from_text(content)
    if extraction is None:
        json_error("upstream_error", "LLM output was not a JSON object.", 502)

    # 0.106.0 engines carry the namespace (it becomes the document's scope, and the scope of the
    # events the extraction mints); older ones store into 'default' and the report says so.
    takes_namespace = ingest_takes_namespace(auth.conn)

    # Upload text + ingest extraction (one transaction)
    def _ingest(conn):
        doc = db_one(
            conn,
            "SELECT maludb_upload_document(p_title => %s, p_content_text => %s, p_source_type => %s) AS id",
            [(title or text[:80]).strip(), text, source_type],
        )
        document_id = int(doc["id"])
        if takes_namespace:
            row = db_one(
                conn,
                """SELECT maludb_memory_ingest_extraction(
                            p_extraction => %s::jsonb, p_source_kind => 'document',
                            p_source_id => %s, p_provenance => 'suggested', p_namespace => %s) AS result""",
                [json.dumps(extraction), document_id, namespace],
            )
        else:
            row = db_one(
                conn,
                """SELECT maludb_memory_ingest_extraction(
                            p_extraction => %s::jsonb, p_source_kind => 'document',
                            p_source_id => %s, p_provenance => 'suggested') AS result""",
                [json.dumps(extraction), document_id],
            )
        if row and row["result"] and isinstance(row["result"], str):
            result_val = json.loads(row["result"])
        else:
            result_val = row["result"] if row else None
        return {"document_id": document_id, "result": result_val}

    result = db_tx_core(auth.conn, _ingest)

    return {
        "document_id": result["document_id"],
        "model": model,
        "api_format": pr.get("api_format", "openai"),
        **ingest_namespace_report(namespace, applied=takes_namespace),
        "result": result["result"],
    }


# ===========================================================================
# POST /v1/memory/reindex/run — background document/note reindex (one batch)
# ===========================================================================


def _memory_reindex_extract(auth, text: str) -> tuple[dict | None, str | None]:
    """Re-derive a document's/note's SVPOR extraction from its stored text.

    Returns (extraction, model), or (None, None) when no 'extract' model + key
    is configured for the tenant -- reindex requires a model (there is no
    deterministic SVPOR fallback the way skills have a frontmatter fallback).
    Mirrors ingest_core's extraction (same `extract` task prompt, live type
    catalog + known subjects/verbs); kept as a focused helper so the critical
    ingest path stays untouched.
    """
    store = get_auth_store()
    pr = resolve_task_config(store, auth.user_id, "extract", None)
    if pr is None or not pr.get("api_key"):
        return None, None
    model = pr.get("model_name")

    subj_rows = db_query(
        auth.conn,
        "SELECT canonical_name AS name, subject_type AS type FROM maludb_subject ORDER BY canonical_name",
    )
    verb_rows = db_query(auth.conn, "SELECT canonical_name FROM maludb_verb ORDER BY canonical_name")
    known_subjects_json = json.dumps([{"name": r["name"], "type": r["type"]} for r in subj_rows], ensure_ascii=False)
    known_verbs_json = json.dumps([r["canonical_name"] for r in verb_rows], ensure_ascii=False)

    try:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description FROM maludb_subject_type ORDER BY category, sort_order",
        )
    except Exception:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description"
            " FROM maludb_core.malu$svpor_subject_type ORDER BY category, sort_order",
        )
    entity_lines: list[str] = []
    event_lines: list[str] = []
    for r in type_rows:
        desc = " — " + r["description"] if r.get("description") and str(r["description"]).strip() else ""
        line = f"  - {r['subject_type']}{desc}"
        (event_lines if (r.get("category") or "entity") == "event" else entity_lines).append(line)
    entity_block = "\n".join(entity_lines) if entity_lines else "  - other"
    event_block = "\n".join(event_lines) if event_lines else "  - task"

    system = (
        str(pr.get("system_prompt", ""))
        .replace("{{ENTITY_TYPES}}", entity_block)
        .replace("{{EVENT_KINDS}}", event_block)
    )
    user_msg = (
        f"TEXT:\n{text}\n\nHINTS:\n[]\n\nKNOWN_SUBJECTS:\n{known_subjects_json}\n\nKNOWN_VERBS:\n{known_verbs_json}\n"
    )
    llm_cfg: dict[str, Any] = {
        "api_format": pr.get("api_format", "openai"),
        "base_url": pr.get("base_url", ""),
        "model_identifier": pr.get("model_identifier") or model,
        "token": pr["api_key"],
        "max_tokens": int(pr.get("max_tokens", 2048)),
        "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
    }
    extraction = llm_json_from_text(llm_complete(llm_cfg, system, user_msg))
    return extraction, model


@router.post("/v1/memory/reindex/run")
def memory_reindex_run(
    auth: Auth,
    limit: int = Query(default=32, le=200),
    max_age: str | None = Query(default="30 days", max_length=64),
    source_type: str | None = Query(default=None, max_length=64),
):
    """Run one document/note reindex sweep batch for the calling tenant (maludb_core 0.100.0).

    The cron-driven half of the document/note reindex (DB contract: maludb_core
    docs/document-reindex.md). Claims the stalest documents/notes via
    maludb_memory_reindex_claim, re-derives their SVPOR footprint against the
    current graph with the user's `extract` model, and applies a
    replace-footprint rewrite via maludb_memory_reindex_apply. Intended to be
    invoked on a schedule by an external cron / systemd timer. A document whose
    extraction fails is captured in `errors`; one with no configured model is
    listed in `skipped`; neither aborts the batch.
    """
    has_claim = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_memory_reindex_claim') AS ok",
    )
    if not has_claim or not has_claim["ok"]:
        json_error(
            "reindex_unavailable",
            "maludb_memory_reindex_claim is not available (requires maludb_core 0.100.0;"
            " re-run enable_memory_schema('<tenant>') after upgrading).",
            501,
        )

    age = (max_age or "").strip() or None
    src = [source_type.strip()] if source_type and source_type.strip() else None
    rows = db_query(
        auth.conn,
        "SELECT document_id, source_type, title, content_text  FROM maludb_memory_reindex_claim(%s, %s::interval, %s)",
        [limit, age, src],
    )

    reindexed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for r in rows:
        did = int(r["document_id"])
        text = r["content_text"] or ""
        if not text.strip():
            skipped.append({"document_id": did, "reason": "empty content_text"})
            continue
        try:
            extraction, model = _memory_reindex_extract(auth, text)
            if extraction is None:
                skipped.append({"document_id": did, "reason": "no extract model configured"})
                continue

            def _apply(conn, _d=did, _e=extraction, _m=model):  # noqa: ANN001, ANN202
                return db_one(
                    conn,
                    "SELECT maludb_memory_reindex_apply("
                    "  p_document_id => %s, p_extraction => %s::jsonb, p_model => %s) AS result",
                    [_d, json.dumps(_e), _m],
                )

            applied = db_tx_core(auth.conn, _apply)["result"]
            if isinstance(applied, str):
                applied = json.loads(applied)
            reindexed.append({"document_id": did, "title": r["title"], "model": model, "applied": applied})
        except Exception as exc:  # one document's failure must not abort the sweep
            errors.append({"document_id": did, "error": str(exc)})

    return {
        "claimed": len(rows),
        "reindexed": reindexed,
        "skipped": skipped,
        "errors": errors,
        "limit": limit,
        "max_age": age,
        "source_type": source_type,
    }


# ===========================================================================
# POST /v1/memory/embeddings/run — drain the entity-card embedding queue
# ===========================================================================


def _has_real_embedder(embed_cfg: dict) -> bool:
    """True if a real embedding endpoint is configured (user 'embed' choice or
    MALUDB_EMBED_* env) -- as opposed to mem_embed's deterministic fallback,
    which is not worth persisting as an entity-card vector."""
    if embed_cfg:
        return True
    return bool(
        os.environ.get("MALUDB_EMBED_BASE_URL")
        and os.environ.get("MALUDB_EMBED_TOKEN")
        and os.environ.get("MALUDB_EMBED_MODEL")
    )


@router.post("/v1/memory/embeddings/run")
def memory_embeddings_run(
    auth: Auth,
    limit: int = Query(default=64, le=512),
    kinds: str | None = Query(default=None, max_length=120),
):
    """Drain one batch of the entity-card embedding queue for the calling tenant
    (the deferred maludb_core 0.95.0 consumer; semantic spine for documents AND skills).

    Claims pending cards via `maludb_embedding_dirty_claim` (subjects/verbs/SVO
    statements marked dirty by ingest + reindex), embeds each card's text with
    the user's `embed` model, and stores the vector + refreshes semantic edges
    via `maludb_embedding_complete` (the bytea is built in SQL from a real[] via
    `vector_from_real_array(...)::bytea`, so the wire format is the DB's own).
    `?kinds=subject,verb` scopes; `?limit=` (default 64) caps the batch. Returns
    early when no real embedding model is configured (the deterministic fallback
    isn't worth persisting). One card's failure is captured in `errors`.
    Intended to be invoked on a schedule by an external cron / systemd timer.
    """
    has_claim = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_embedding_dirty_claim') AS ok",
    )
    if not has_claim or not has_claim["ok"]:
        json_error(
            "embeddings_unavailable",
            "maludb_embedding_dirty_claim is not available (requires maludb_core 0.95.0;"
            " re-run enable_memory_schema('<tenant>') after upgrading).",
            501,
        )

    embed_cfg = resolve_embed_config(get_auth_store(), auth.user_id)
    if not _has_real_embedder(embed_cfg):
        return {
            "claimed": 0,
            "embedded": [],
            "errors": [],
            "note": "no embedding model configured (set the 'embed' task or MALUDB_EMBED_* env); skipped",
        }
    model_name = embed_cfg.get("embedding_model") or os.environ.get("MALUDB_EMBED_MODEL")

    kinds_arr = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    rows = db_query(
        auth.conn,
        "SELECT object_kind, object_id, generation, card_text, content_hash  FROM maludb_embedding_dirty_claim(%s, %s)",
        [kinds_arr, limit],
    )

    embedded: list[dict] = []
    errors: list[dict] = []
    for r in rows:
        kind = r["object_kind"]
        oid = int(r["object_id"])
        try:
            vec = mem_embed(r["card_text"] or "", embed_cfg)

            def _complete(conn, _k=kind, _o=oid, _g=int(r["generation"]), _v=vec, _h=r["content_hash"]):  # noqa: ANN001, ANN202
                return db_one(
                    conn,
                    "SELECT maludb_embedding_complete("
                    "  p_object_kind => %s, p_object_id => %s, p_generation => %s,"
                    "  p_embedding => maludb_core.vector_from_real_array(%s::real[])::bytea,"
                    "  p_embedding_dim => %s, p_embedding_space => 'entity-v1',"
                    "  p_embedding_model => %s, p_content_hash => %s, p_refresh_neighbors => true) AS id",
                    [_k, _o, _g, _v, len(_v), model_name, _h],
                )

            db_tx_core(auth.conn, _complete)
            embedded.append({"object_kind": kind, "object_id": oid})
        except Exception as exc:  # one card's failure must not abort the sweep
            errors.append({"object_kind": kind, "object_id": oid, "error": str(exc)})

    return {
        "claimed": len(rows),
        "embedded": embedded,
        "errors": errors,
        "model": model_name,
        "limit": limit,
        "kinds": kinds_arr,
    }
