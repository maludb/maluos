"""
Note search — retrieve notes by the subjects/verbs of their extracted edges.

Thin wrapper over the maludb_core 0.98.0 facades: all matching semantics
(subject ILIKE over canonical names + aliases against both statement
endpoints, verb-exact vs bidirectional verb-like containment, both
statement->document rails, one row per document with edges aggregated) live
in maludb_note_search; the deterministic free-text parse lives in
maludb_note_query_parse. The only server-side logic is the optional LLM
fallback for free-text queries whose action word is not in the tenant's
verb catalog (task 'query_parse' in the seeded model catalog).

Endpoints:
    GET /v1/memory/notes — structured (subject_like/verb_like/action) or
                           free-text (q=...) note search
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Query

from app.auth import Auth, get_auth_store
from app.database import db_one, db_query
from app.errors import json_error
from app.helpers.llm import llm_complete, llm_json_from_text
from app.helpers.llm_resolve import resolve_task_config

router = APIRouter()


@router.get("/v1/memory/notes")
def memory_notes(
    auth: Auth,
    q: str | None = Query(default=None, max_length=300),
    subject_like: list[str] | None = Query(default=None),
    verb_like: str | None = Query(default=None, max_length=120),
    action: str | None = Query(default=None, max_length=120),
    source_type: str = Query(default="note", max_length=60),
    all_sources: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    model: str | None = Query(default=None, max_length=120),
):
    return notes_search_core(
        auth,
        q=q,
        subject_like=subject_like,
        verb_like=verb_like,
        action=action,
        source_type=source_type,
        all_sources=all_sources,
        limit=limit,
        offset=offset,
        explicit_model=model,
    )


def notes_search_core(
    auth,
    *,
    q: str | None = None,
    subject_like: list[str] | None = None,
    verb_like: str | None = None,
    action: str | None = None,
    source_type: str = "note",
    all_sources: bool = False,
    limit: int = 20,
    offset: int = 0,
    explicit_model: str | None = None,
) -> dict:
    """Note search shared by the REST route and the MCP find_notes tool.

    Free-text flow (q given, no structured criteria): deterministic parse via
    maludb_note_query_parse; if it finds no verb and the user has a
    'query_parse' model configured, fall back to an LLM parse constrained to
    the tenant's verb catalog (LLM errors are non-fatal); otherwise search by
    the leftover tokens alone. Always ends in one maludb_note_search call.
    """
    q = (q or "").strip() or None
    subject_like = [s for s in (subject_like or []) if s.strip()] or None
    verb_like = (verb_like or "").strip() or None
    action = (action or "").strip() or None

    if not q and not subject_like and not verb_like and not action:
        json_error(
            "missing_field",
            'At least one of "q", "subject_like", "verb_like", "action" is required.',
            400,
        )

    has_facade = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_note_search') AS ok",
    )
    if not has_facade or not has_facade["ok"]:
        json_error(
            "note_search_unavailable",
            "maludb_note_search is not available in this database (requires maludb_core 0.98.0).",
            501,
        )

    parser = "structured"
    parsed_verb: str | None = None
    if q and not (subject_like or verb_like or action):
        parsed = _parse_query(auth, q, explicit_model)
        parser = parsed["parser"]
        parsed_verb = parsed.get("verb")
        if parsed_verb:
            if parsed.get("verb_is_exact", True):
                action = parsed_verb
            else:
                verb_like = parsed_verb
        subject_like = parsed.get("subject_tokens") or None
        if not subject_like and not parsed_verb:
            # Nothing usable came out of the parse (e.g. all stopwords).
            return {"query": {"q": q, "parser": parser}, "count": 0, "notes": []}

    rows = db_query(
        auth.conn,
        """SELECT document_id, title, source_type, snippet, created_at,
                  match_count, matched_edges
             FROM maludb_note_search(
                      p_subject_like => %s::text[],
                      p_verb_like    => %s,
                      p_verb_exact   => %s,
                      p_source_type  => %s,
                      p_all_sources  => %s,
                      p_limit        => %s,
                      p_offset       => %s)""",
        [subject_like, verb_like, action, source_type, all_sources, limit, offset],
    )

    notes = []
    for r in rows:
        edges = r["matched_edges"]
        if isinstance(edges, str):
            edges = json.loads(edges)
        notes.append(
            {
                "id": int(r["document_id"]),
                "title": r["title"],
                "source_type": r["source_type"],
                "snippet": r["snippet"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "match_count": int(r["match_count"]),
                "matched_edges": edges,
            }
        )

    return {
        "query": {
            "q": q,
            "parser": parser,
            "verb": parsed_verb if parser != "structured" else (action or verb_like),
            "subject_like": subject_like,
        },
        "count": len(notes),
        "notes": notes,
    }


def _parse_query(auth, q: str, explicit_model: str | None) -> dict:
    """Parse free text into a verb + subject patterns.

    Returns {"parser", "verb", "verb_is_exact", "subject_tokens"}.
    """
    row = db_one(auth.conn, "SELECT maludb_note_query_parse(%s) AS parsed", [q])
    parsed = row["parsed"] if row else None
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    parsed = parsed or {}
    tokens = parsed.get("subject_tokens") or []

    if parsed.get("verb"):
        return {
            "parser": "deterministic",
            "verb": parsed["verb"],
            "verb_is_exact": True,
            "subject_tokens": tokens,
        }

    llm = _llm_parse(auth, q, explicit_model)
    if llm is not None:
        return llm

    # No verb anywhere: search by the content tokens alone.
    return {"parser": "tokens", "verb": None, "verb_is_exact": True, "subject_tokens": tokens}


def _llm_parse(auth, q: str, explicit_model: str | None) -> dict | None:
    """LLM fallback parse, constrained to the tenant verb catalog.

    Returns None when no query_parse model is configured or the call fails —
    the search degrades to token matching rather than erroring.
    """
    store = get_auth_store()
    cfg = resolve_task_config(store, auth.user_id, "query_parse", explicit_model)
    if not cfg or not cfg.get("api_key"):
        return None

    verb_rows = db_query(auth.conn, "SELECT canonical_name, aliases FROM maludb_verb ORDER BY canonical_name")
    known_verbs = [{"verb": r["canonical_name"], "aliases": list(r["aliases"] or [])} for r in verb_rows]
    user_msg = f"QUERY:\n{q}\n\nKNOWN_VERBS:\n{json.dumps(known_verbs)}"
    llm_cfg = {
        "api_format": cfg.get("api_format", "openai"),
        "base_url": cfg.get("base_url", ""),
        "model_identifier": cfg.get("model_identifier") or cfg.get("model_name"),
        "token": cfg["api_key"],
        "max_tokens": int(cfg.get("max_tokens") or 256),
        "generation_params": json.loads(cfg["generation_params"]) if cfg.get("generation_params") else {},
    }
    try:
        content = llm_complete(llm_cfg, cfg.get("system_prompt") or "", user_msg)
        out = llm_json_from_text(content)
    except Exception:
        return None
    if not isinstance(out, dict):
        return None

    verb = str(out.get("verb") or "").strip() or None
    subject = str(out.get("subject") or "").strip()
    catalog = {v["verb"].lower(): v["verb"] for v in known_verbs}
    verb_is_exact = bool(verb) and verb.lower() in catalog
    if verb_is_exact:
        verb = catalog[verb.lower()]
    return {
        "parser": "llm",
        "verb": verb,
        # A non-catalog verb degrades to verb_like containment.
        "verb_is_exact": verb_is_exact,
        "subject_tokens": subject.split() if subject else [],
    }
