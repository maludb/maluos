"""
MCP server endpoint — POST /mcp (Model Context Protocol, stateless Streamable HTTP).

Lets MCP clients (Claude Code, Claude Desktop, hosted agents) use MaluDB as
long-term memory with nothing but this URL and a Bearer token:

    claude mcp add --transport http maludb http://localhost:8000/mcp \\
      --header "Authorization: Bearer $TOKEN"

Implements MCP spec 2025-06-18 in its simplest conformant shape:
  - Single endpoint, POST only (GET/DELETE -> 405).  Every JSON-RPC request
    gets a single application/json response; notifications get HTTP 202.
    No sessions (no Mcp-Session-Id), no SSE, no JSON-RPC batches.
  - Methods: initialize, ping, tools/list, tools/call (+ notifications/*).
  - Auth: the same Bearer token flow as the REST API (authenticate_bearer);
    tools run as the token's user, so per-user LLM config applies.
  - Tool failures are JSON-RPC *successes* with isError:true and the standard
    {"error":{code,message}} JSON in the text block, so agents can read the
    error code and self-correct.  Protocol failures use JSON-RPC error codes.

Nine tools: store_memory, search_memory, find_subjects, explore_subject,
store_document, get_document, find_notes, find_skills, get_skill.  The
pipeline tools call the shared cores in app/routers/memory.py and
app/routers/memory_notes.py; the read tools carry their own
literal SQL (copied from the corresponding REST routers — see the repo's
SQL-traceability principle).  The TOOLS registry below is a cross-server
contract: the Fastify and PHP servers port it byte-for-byte.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from app.auth import authenticate_bearer
from app.database import db_one, db_query, db_tx_core
from app.errors import APIError, _pg_error_message, classify_database_error
from app.routers.memory import documents_core, ingest_core, search_core
from app.routers.memory_notes import notes_search_core

router = APIRouter()

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

SERVER_VERSION = "0.4.0"
PROTOCOL_VERSIONS = {"2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "maludb", "title": "MaluDB Memory", "version": SERVER_VERSION}

# ---------------------------------------------------------------------------
# Tool registry — names, schemas, and descriptions are a cross-server contract
# (ported verbatim to the Fastify and PHP servers).  Plain data only.
# ---------------------------------------------------------------------------

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

TOOLS: list[dict] = [
    {
        "name": "store_memory",
        "title": "Store memory",
        "description": (
            "Store a fact, event, or observation in MaluDB long-term memory. The server runs"
            " LLM extraction (with the user's configured extract model) and writes subjects,"
            " verbs, and edges into the knowledge graph. Call this whenever the user states"
            " something worth remembering. Pass hints for subjects you already know the text"
            " is about (use canonical names from find_subjects when possible)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to remember."},
                "hints": {
                    "type": "array",
                    "description": "Known subjects this text is about.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject_type": {"type": "string", "description": "e.g. person, project, software"},
                            "subject_name": {"type": "string"},
                        },
                        "required": ["subject_type", "subject_name"],
                    },
                },
                "namespace": {"type": "string", "default": "default"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "annotations": _WRITE,
    },
    {
        "name": "search_memory",
        "title": "Search memory",
        "description": (
            "Semantic vector search over stored memory; returns matching text spans with"
            " their source document ids. The search requires a compartment pre-filter:"
            " pass subject (canonical name) and/or verb. Call find_subjects first when you"
            " don't know the canonical subject name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "subject": {"type": "string", "description": "Canonical subject name to search within."},
                "verb": {"type": "string", "description": "Canonical verb to search within."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "namespace": {"type": "string", "default": "default"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "find_subjects",
        "title": "Find subjects",
        "description": (
            "List canonical subjects (entities) in the memory graph, optionally filtered by"
            " a name/description substring. Call this before search_memory or"
            " explore_subject when you don't know the exact canonical name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match against name or description."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            },
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "explore_subject",
        "title": "Explore subject",
        "description": (
            "Walk the knowledge graph around one subject: its edges and neighbors (depth 1)"
            " or multi-hop reach (depth 2-3). Use after find_subjects to see everything"
            " known about an entity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Canonical subject name or numeric subject id."},
                "direction": {"type": "string", "enum": ["out", "in", "both"], "default": "both"},
                "verb": {"type": "string", "description": "Only follow edges with this verb."},
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            },
            "required": ["subject"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "store_document",
        "title": "Store document",
        "description": (
            "Store a full document (meeting notes, transcript, article) in memory. The"
            " server chunks the text, extracts graph edges with the user's configured"
            " model, embeds them, and links the document to the given subjects/projects."
            " Prefer store_memory for short facts and observations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "text": {"type": "string", "description": "The full document text."},
                "source_type": {"type": "string", "default": "document"},
                "subjects": {"type": "array", "items": {"type": "string"}},
                "projects": {"type": "array", "items": {"type": "string"}},
                "namespace": {"type": "string", "default": "default"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
        "annotations": _WRITE,
    },
    {
        "name": "get_document",
        "title": "Get document",
        "description": (
            "Fetch one stored document's metadata and tags by id. Document ids come from"
            " search_memory results, store_memory, or store_document."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer"},
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "find_notes",
        "title": "Find notes",
        "description": (
            "Retrieve stored notes by the subjects/verbs of their extracted edges."
            " Pass query for free text ('Install Ubuntu' — the server parses out the"
            " verb and subject), or subject_like patterns plus verb_like (fuzzy:"
            " 'installation' finds 'install') or action (exact verb). Set"
            " all_sources=true to widen beyond notes to every stored document."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subject_like": {"type": "array", "items": {"type": "string"}},
                "verb_like": {"type": "string"},
                "action": {"type": "string"},
                "all_sources": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
            },
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "find_skills",
        "title": "Find skills",
        "description": (
            "Discover stored agent skills. Pass subject and/or verb for tag-aware ranked"
            " discovery (e.g. verb='extract'); otherwise query matches names and"
            " descriptions. Call this when the current task might already have a stored"
            " skill."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subject": {"type": "string"},
                "verb": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
            },
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_skill",
        "title": "Get skill",
        "description": (
            "Fetch one agent skill: metadata, the SKILL.md markdown instructions, and a"
            " listing of its bundle files (paths and sizes only — fetch full bundles via"
            " the REST API). Provide skill_id, or name to get the newest enabled version."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "integer"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


class _InvalidParams(Exception):
    """Handler-level parameter problem -> JSON-RPC -32602."""


def _dumps(payload) -> str:
    """Serialize tool output like the REST API would (ISO-8601 datetimes)."""
    return json.dumps(jsonable_encoder(payload), ensure_ascii=False)


def _rpc_result(req_id, result: dict) -> JSONResponse:
    return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": req_id, "result": result})


def _rpc_error(req_id, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
    )


def _text_result(payload) -> dict:
    return {"content": [{"type": "text", "text": _dumps(payload)}]}


def _error_result(code: str, message: str, sqlstate: str | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if sqlstate:
        error["sqlstate"] = sqlstate
    return {
        "content": [{"type": "text", "text": json.dumps({"error": error}, ensure_ascii=False)}],
        "isError": True,
    }


def _int_arg(args: dict, name: str, default: int) -> int:
    """Coerce an optional integer argument; a non-numeric value -> -32602."""
    value = args.get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _InvalidParams(f'"{name}" must be an integer.') from None


# ---------------------------------------------------------------------------
# Transport-level checks
# ---------------------------------------------------------------------------

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _origin_rejection(request: Request) -> JSONResponse | None:
    """DNS-rebinding guard: a present Origin must be localhost or our own host."""
    origin = request.headers.get("origin")
    if not origin:
        return None
    origin_host = (urlsplit(origin).hostname or "").lower()
    own_host = request.headers.get("host", "").rsplit(":", 1)[0].strip("[]").lower()
    if origin_host in _LOCAL_HOSTS or (own_host and origin_host == own_host):
        return None
    return JSONResponse(
        status_code=403,
        content={"error": {"code": "origin_forbidden", "message": "Origin not allowed."}},
    )


def _protocol_version_rejection(request: Request) -> JSONResponse | None:
    version = request.headers.get("mcp-protocol-version")
    if version and version not in PROTOCOL_VERSIONS:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "unsupported_protocol_version",
                    "message": f"Supported MCP protocol versions: {', '.join(sorted(PROTOCOL_VERSIONS))}.",
                }
            },
        )
    return None


# ---------------------------------------------------------------------------
# Tool handlers — (auth, args) -> MCP result dict
# ---------------------------------------------------------------------------


def _tool_store_memory(auth, args: dict) -> dict:
    text = str(args.get("text", ""))
    if not text.strip():
        raise _InvalidParams('"text" must be a non-empty string.')
    hints = args.get("hints")
    hints_json = json.dumps(hints) if isinstance(hints, list) else "[]"
    namespace = str(args.get("namespace") or "default").strip() or "default"

    payload = ingest_core(
        auth, text=text, hints_json=hints_json, namespace=namespace, explicit_model=None, preview=False
    )
    return _text_result(payload)


def _tool_search_memory(auth, args: dict) -> dict:
    query = str(args.get("query", ""))
    if not query.strip():
        raise _InvalidParams('"query" must be a non-empty string.')
    subject = str(args["subject"]).strip() if args.get("subject") and str(args["subject"]).strip() else None
    verb = str(args["verb"]).strip() if args.get("verb") and str(args["verb"]).strip() else None
    limit = max(1, min(50, _int_arg(args, "limit", 10)))
    namespace = str(args.get("namespace") or "default").strip() or "default"

    if subject is None and verb is None:
        # The compartment pre-filter is required; instead of a bare 400, return
        # the matching subjects so the agent can pick one and retry.
        terms = [t for t in query.split() if len(t) >= 3] or [query.strip()]
        rows = db_query(
            auth.conn,
            """SELECT canonical_name AS name, subject_type AS type
                 FROM maludb_subject
                WHERE canonical_name ILIKE ANY(%s)
                ORDER BY canonical_name
                LIMIT 10""",
            [[f"%{t}%" for t in terms]],
        )
        matches = ", ".join(f"{r['name']} ({r['type']})" for r in rows) or "none"
        return _error_result(
            "missing_field",
            "Provide subject and/or verb — the compartment pre-filter is required."
            f" Known subjects matching your query: {matches}."
            " Pick one or call find_subjects.",
        )

    payload = search_core(
        auth,
        query=query,
        subject=subject,
        verb=verb,
        namespace=namespace,
        limit=limit,
        metric="cosine",
        embedding_model=None,
    )
    return _text_result(payload)


def _tool_find_subjects(auth, args: dict) -> dict:
    q = str(args["query"]).strip() if args.get("query") and str(args["query"]).strip() else None
    limit = max(1, min(200, _int_arg(args, "limit", 25)))

    where = ""
    params: list = []
    if q:
        where = "WHERE s.canonical_name ILIKE %s OR s.description ILIKE %s"
        params = [f"%{q}%", f"%{q}%"]

    sql = f"""SELECT s.subject_id     AS id,
                     s.canonical_name AS name,
                     s.subject_type   AS type,
                     s.description
                FROM maludb_subject s
                {where}
               ORDER BY s.canonical_name
               LIMIT %s"""
    params.append(limit)

    rows = db_query(auth.conn, sql, params)
    for r in rows:
        r["id"] = int(r["id"])
    return _text_result({"subjects": rows})


def _resolve_subject(auth, ref: str) -> dict:
    """Resolve a subject reference (numeric id or canonical name) to a row."""
    ref = ref.strip()
    if not ref:
        raise _InvalidParams('"subject" must be a non-empty string.')

    base = "SELECT subject_id AS id, canonical_name AS name, subject_type AS type FROM maludb_subject"
    if ref.isdigit():
        row = db_one(auth.conn, f"{base} WHERE subject_id = %s", [int(ref)])
        if row is None:
            raise APIError("not_found", f"No subject with id {ref}.", 404)
        row["id"] = int(row["id"])
        return row

    row = db_one(auth.conn, f"{base} WHERE canonical_name = %s", [ref])
    if row is None:
        candidates = db_query(
            auth.conn, f"{base} WHERE canonical_name ILIKE %s ORDER BY canonical_name LIMIT 6", [f"%{ref}%"]
        )
        if len(candidates) == 1:
            row = candidates[0]
        elif not candidates:
            raise APIError("not_found", f'No subject matching "{ref}". Call find_subjects.', 404)
        else:
            names = ", ".join(c["name"] for c in candidates)
            raise APIError(
                "ambiguous_subject",
                f'Multiple subjects match "{ref}": {names}. Pick one exact canonical name.',
                422,
            )
    row["id"] = int(row["id"])
    return row


def _tool_explore_subject(auth, args: dict) -> dict:
    subject = _resolve_subject(auth, str(args.get("subject", "")))
    direction = str(args.get("direction") or "both").strip().lower()
    if direction not in ("out", "in", "both"):
        raise _InvalidParams('"direction" must be one of: out, in, both.')
    depth = max(1, min(3, _int_arg(args, "depth", 1)))
    verb = str(args["verb"]).strip() if args.get("verb") and str(args["verb"]).strip() else None
    rel_list = [verb] if verb else None

    if depth == 1:

        def _neighbors(conn):
            if rel_list:
                sql = """SELECT neighbor_kind, neighbor_id, rel, edge_store,
                                confidence, provenance, label
                           FROM maludb_graph_neighbors(%s, %s, %s, %s::text[])"""
                params = ["subject", subject["id"], direction, rel_list]
            else:
                sql = """SELECT neighbor_kind, neighbor_id, rel, edge_store,
                                confidence, provenance, label
                           FROM maludb_graph_neighbors(%s, %s, %s)"""
                params = ["subject", subject["id"], direction]
            rows = db_query(conn, sql, params)
            for r in rows:
                r["neighbor_id"] = int(r["neighbor_id"])
                r["confidence"] = float(r["confidence"]) if r["confidence"] is not None else None
            return rows

        rows = db_tx_core(auth.conn, _neighbors)
        return _text_result({"subject": subject, "direction": direction, "depth": depth, "neighbors": rows})

    def _walk(conn):
        if rel_list:
            sql = """SELECT object_kind, object_id, depth, rel, edge_store, label, path
                       FROM maludb_graph_walk(%s, %s, %s, %s, %s::text[])"""
            params = ["subject", subject["id"], depth, direction, rel_list]
        else:
            sql = """SELECT object_kind, object_id, depth, rel, edge_store, label, path
                       FROM maludb_graph_walk(%s, %s, %s, %s)"""
            params = ["subject", subject["id"], depth, direction]
        rows = db_query(conn, sql, params)
        for r in rows:
            r["object_id"] = int(r["object_id"])
            r["depth"] = int(r["depth"])
            if r["path"] is None:
                r["path"] = []
        return rows

    rows = db_tx_core(auth.conn, _walk)
    return _text_result({"subject": subject, "direction": direction, "depth": depth, "walk": rows})


def _tool_store_document(auth, args: dict) -> dict:
    title = str(args.get("title", "")).strip()
    text = str(args.get("text", ""))
    if not title:
        raise _InvalidParams('"title" must be a non-empty string.')
    if not text.strip():
        raise _InvalidParams('"text" must be a non-empty string.')

    def _strings(v) -> list[str]:
        if not isinstance(v, list):
            return []
        return [s.strip() for s in v if isinstance(s, str) and s.strip()]

    payload = documents_core(
        auth,
        title=title,
        text=text,
        source_type=str(args.get("source_type") or "document").strip() or "document",
        media_type=None,
        document_type=None,
        metadata_json=json.dumps({"source": "mcp"}),
        projects=_strings(args.get("projects")),
        subjects=_strings(args.get("subjects")),
        verbs=[],
        events=[],
        chunk_max=2000,
        chunk_overlap=200,
        embedding_model=None,
        explicit_model=None,
        provided_edges=None,
        namespace=str(args.get("namespace") or "default").strip() or "default",
    )
    return _text_result(payload)


def _tool_get_document(auth, args: dict) -> dict:
    try:
        document_id = int(args.get("document_id"))
    except (TypeError, ValueError):
        raise _InvalidParams('"document_id" must be an integer.') from None

    doc = db_one(
        auth.conn,
        """SELECT d.document_id              AS id,
                  d.title,
                  d.source_type,
                  d.media_type,
                  d.document_type,
                  d.primary_project_id,
                  d.metadata_jsonb->>'description' AS description,
                  sp.content_size,
                  sp.content_hash,
                  d.created_at,
                  d.updated_at
             FROM maludb_document d
             LEFT JOIN maludb_source_package sp ON sp.source_package_id = d.source_package_id
            WHERE d.document_id = %s""",
        [document_id],
    )
    if doc is None:
        raise APIError("not_found", "Document not found.", 404)
    doc["id"] = int(doc["id"])
    doc["content_size"] = int(doc["content_size"]) if doc["content_size"] is not None else None
    doc["primary_project_id"] = int(doc["primary_project_id"]) if doc["primary_project_id"] is not None else None

    tags = db_query(
        auth.conn,
        """SELECT tag_id, tag_kind, tag_value, tag_object_type, tag_object_id, provenance, confidence
           FROM maludb_document_tag
          WHERE document_id = %s
          ORDER BY tag_kind, tag_value, tag_id""",
        [document_id],
    )
    for t in tags:
        t["tag_id"] = int(t["tag_id"])
        t["tag_object_id"] = int(t["tag_object_id"]) if t["tag_object_id"] is not None else None
        t["confidence"] = float(t["confidence"]) if t["confidence"] is not None else None
    doc["tags"] = tags

    return _text_result({"document": doc})


def _tool_find_notes(auth, args: dict) -> dict:
    query = str(args["query"]).strip() if args.get("query") and str(args["query"]).strip() else None
    subject_like = [str(s) for s in args.get("subject_like") or [] if str(s).strip()] or None
    verb_like = str(args["verb_like"]).strip() if args.get("verb_like") and str(args["verb_like"]).strip() else None
    action = str(args["action"]).strip() if args.get("action") and str(args["action"]).strip() else None
    all_sources = bool(args.get("all_sources"))
    limit = max(1, min(200, _int_arg(args, "limit", 20)))

    if not query and not subject_like and not verb_like and not action:
        raise _InvalidParams("At least one of query, subject_like, verb_like, action is required.")

    payload = notes_search_core(
        auth,
        q=query,
        subject_like=subject_like,
        verb_like=verb_like,
        action=action,
        all_sources=all_sources,
        limit=limit,
    )
    return _text_result(payload)


def _tool_find_skills(auth, args: dict) -> dict:
    q = str(args["query"]).strip() if args.get("query") and str(args["query"]).strip() else None
    subject = str(args["subject"]).strip() if args.get("subject") and str(args["subject"]).strip() else None
    verb = str(args["verb"]).strip() if args.get("verb") and str(args["verb"]).strip() else None
    limit = max(1, min(200, _int_arg(args, "limit", 20)))

    if subject or verb:
        rows = db_query(
            auth.conn,
            """SELECT owner_schema, skill_id AS id, skill_name AS name, description,
                      version, visibility, subjects, verbs, keywords, score,
                      match_reasons, is_public, is_forkable,
                      source_owner_schema, source_skill_id, updated_at
                 FROM maludb_skill_search(%s, %s, %s, NULL, %s)""",
            [q, subject, verb, limit],
        )
        for r in rows:
            r["id"] = int(r["id"])
            r["score"] = None if r["score"] is None else float(r["score"])
            if r["source_skill_id"] is not None:
                r["source_skill_id"] = int(r["source_skill_id"])
        return _text_result({"skills": rows})

    clauses: list[str] = []
    params: list = []
    if q:
        clauses.append("(skill_name ILIKE %s OR description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""SELECT skill_id AS id, skill_name AS name, description, version,
                     visibility, packaging_kind, enabled, created_at
                FROM maludb_skill
                {where}
               ORDER BY skill_name
               LIMIT %s"""
    params.append(limit)

    rows = db_query(auth.conn, sql, params)
    for r in rows:
        r["id"] = int(r["id"])
        r["enabled"] = None if r["enabled"] is None else bool(r["enabled"])
    return _text_result({"skills": rows})


def _tool_get_skill(auth, args: dict) -> dict:
    skill_id = args.get("skill_id")
    name = str(args["name"]).strip() if args.get("name") and str(args["name"]).strip() else None
    if skill_id is None and name is None:
        raise _InvalidParams('Provide "skill_id" or "name".')

    if skill_id is None:
        row = db_one(
            auth.conn,
            """SELECT skill_id FROM maludb_skill
                WHERE skill_name = %s AND (enabled IS DISTINCT FROM FALSE)
                ORDER BY skill_id DESC LIMIT 1""",
            [name],
        )
        if row is None:
            raise APIError("not_found", f'No enabled skill named "{name}".', 404)
        skill_id = int(row["skill_id"])
    else:
        try:
            skill_id = int(skill_id)
        except (TypeError, ValueError):
            raise _InvalidParams('"skill_id" must be an integer.') from None

    skill = db_one(
        auth.conn,
        """SELECT skill_id AS id, skill_name AS name, description, markdown, version,
                  visibility, enabled, bundle_hash, frontmatter_jsonb,
                  source_owner_schema, source_skill_id, created_at
             FROM maludb_skill WHERE skill_id = %s""",
        [skill_id],
    )
    if skill is None:
        raise APIError("not_found", "Skill not found.", 404)
    skill["id"] = int(skill["id"])
    if skill["source_skill_id"] is not None:
        skill["source_skill_id"] = int(skill["source_skill_id"])
    skill["enabled"] = None if skill["enabled"] is None else bool(skill["enabled"])

    # Listing only — no maludb_source_package join, so file contents never load.
    files = db_query(
        auth.conn,
        """SELECT relative_path, file_size, media_type
             FROM maludb_skill_file
            WHERE skill_id = %s
            ORDER BY relative_path""",
        [skill_id],
    )
    for f in files:
        f["file_size"] = int(f["file_size"]) if f["file_size"] is not None else None

    return _text_result({"skill": skill, "files": files})


_TOOL_HANDLERS = {
    "store_memory": _tool_store_memory,
    "search_memory": _tool_search_memory,
    "find_subjects": _tool_find_subjects,
    "explore_subject": _tool_explore_subject,
    "store_document": _tool_store_document,
    "get_document": _tool_get_document,
    "find_notes": _tool_find_notes,
    "find_skills": _tool_find_skills,
    "get_skill": _tool_get_skill,
}


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------


def _handle_initialize(params: dict) -> dict:
    requested = params.get("protocolVersion")
    version = requested if requested in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
    }


def _handle_tools_call(auth, params: dict, req_id) -> JSONResponse:
    name = params.get("name")
    if not isinstance(name, str) or name not in _TOOL_HANDLERS:
        return _rpc_error(req_id, -32602, f"Unknown tool: {name!r}")

    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    schema = _TOOLS_BY_NAME[name]["inputSchema"]
    for req_field in schema.get("required", []):
        if req_field not in args or args[req_field] is None:
            return _rpc_error(req_id, -32602, f'Missing required argument "{req_field}" for tool "{name}".')

    try:
        result = _TOOL_HANDLERS[name](auth, args)
    except _InvalidParams as exc:
        return _rpc_error(req_id, -32602, str(exc))
    except APIError as exc:
        result = _error_result(exc.code, exc.message)
    except psycopg.errors.DatabaseError as exc:
        _status, code, sqlstate = classify_database_error(exc)
        result = _error_result(code, _pg_error_message(exc), sqlstate)
    return _rpc_result(req_id, result)


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


@router.post("/mcp")
async def mcp_post(request: Request):
    rejection = _origin_rejection(request) or _protocol_version_rejection(request)
    if rejection is not None:
        return rejection

    # Same Bearer flow as REST; APIError(401) propagates to api_error_handler.
    ctx = authenticate_bearer(request.headers.get("authorization"))
    try:
        raw = await request.body()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return _rpc_error(None, -32700, "Parse error")

        if isinstance(msg, list):
            return _rpc_error(None, -32600, "Batch requests are not supported (MCP 2025-06-18).")
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _rpc_error(None, -32600, "Invalid request: expected a JSON-RPC 2.0 object.")
        method = msg.get("method")
        if not isinstance(method, str) or not method:
            return _rpc_error(msg.get("id"), -32600, 'Invalid request: "method" is required.')

        # Notifications (no id) are accepted and ignored.
        if "id" not in msg:
            return Response(status_code=202)

        req_id = msg["id"]
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

        if method == "initialize":
            return _rpc_result(req_id, _handle_initialize(params))
        if method == "ping":
            return _rpc_result(req_id, {})
        if method == "tools/list":
            return _rpc_result(req_id, {"tools": TOOLS})
        if method == "tools/call":
            return _handle_tools_call(ctx, params, req_id)
        return _rpc_error(req_id, -32601, f"Method not found: {method}")
    finally:
        try:
            ctx.conn.close()
        except Exception:
            pass


@router.get("/mcp")
@router.delete("/mcp")
def mcp_method_not_allowed():
    return JSONResponse(
        status_code=405,
        content={
            "error": {
                "code": "method_not_allowed",
                "message": "MCP requires POST. SSE streaming is not supported.",
            }
        },
        headers={"Allow": "POST"},
    )
