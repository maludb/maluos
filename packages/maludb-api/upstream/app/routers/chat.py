"""
Chat sessions — ordered transcripts of an agent's (or a person's) conversation with a model.

The extension has had the model since the chat-logs design (maludb-core
docs/superpowers/specs/2026-05-24-chat-logs-design.md): malu$chat_session + malu$chat_message with
an ordinal per message, a role vocabulary (system, developer, user, assistant, tool, event),
tool_call_id, a content hash and a lifecycle. The tenant facades exist — maludb_chat_start,
maludb_chat_append_message, maludb_chat_finalize, maludb_chat_get, maludb_chat_messages — and no
route ever called them: the only way in was chat_push, which flattens a whole log into one document
and loses the turns. An agent framework needs the turns: write each as it happens (so nothing is
lost if the process dies, and context compression has a durable record behind it) and search them
later ("what did we say about X last week").

    POST /v1/chat/sessions                      start            -> maludb_chat_start
    GET  /v1/chat/sessions                      list (?principal= ?external_ref= ?state= ?limit=)
    GET  /v1/chat/sessions/{id}                 one session      -> maludb_chat_get
    POST /v1/chat/sessions/{id}/messages        append one or many, in order -> maludb_chat_append_message
    GET  /v1/chat/sessions/{id}/messages        the transcript   -> maludb_chat_messages
    POST /v1/chat/sessions/{id}/finalize        close            -> maludb_chat_finalize
    GET  /v1/chat/search                        messages containing ?q= (?principal= ?role= ?limit=)

`principal` and `external_ref` are conventions this router keeps in metadata_jsonb so a host can
find "this agent's sessions" and "the session for my run 42" without a schema change. They are
labels, not access control: the tenant token reads every session in the tenant.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error

router = APIRouter()

ROLES = ("system", "developer", "user", "assistant", "tool", "event")
MAX_BATCH = 200


def _text_array(value) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def _pg_array(items: list[str]) -> str:
    return "{" + ",".join('"' + i.replace("\\", "\\\\").replace('"', '\\"') + '"' for i in items) + "}"


def _jsonb(row_value):
    return json.loads(row_value) if isinstance(row_value, str) else row_value


def normalise_message(raw, index: int) -> dict:
    """Validate one message of an append. Text and structured content may both be present."""
    if not isinstance(raw, dict):
        json_error("validation_failed", f"messages[{index}] must be an object.", 422)
    role = str(raw.get("role") or "").strip()
    if role not in ROLES:
        json_error("validation_failed", f"messages[{index}].role must be one of: {', '.join(ROLES)}.", 422)
    text = raw.get("text")
    content = raw.get("content")
    if (text is None or str(text) == "") and content is None:
        json_error("validation_failed", f'messages[{index}] needs "text" and/or "content".', 422)
    metadata = dict(raw["metadata"]) if isinstance(raw.get("metadata"), dict) else {}
    if raw.get("tool_call_id"):
        metadata["tool_call_id"] = str(raw["tool_call_id"])
    return {
        "role": role,
        "text": None if text is None else str(text),
        "content": None if content is None else json.dumps(content),
        "metadata": json.dumps(metadata),
    }


def _session_row(auth, session_id: int) -> dict:
    row = db_one(auth.conn, "SELECT maludb_chat_get(%s) AS session", [session_id])
    session = _jsonb(row["session"]) if row else None
    if not session:
        json_error("not_found", "Chat session not found.", 404)
    return session


# ===========================================================================
# POST /v1/chat/sessions
# ===========================================================================


@router.post("/v1/chat/sessions")
async def start_session(auth: Auth, request: Request):
    body = await request.json()
    metadata = dict(body["metadata"]) if isinstance(body.get("metadata"), dict) else {}
    for key in ("principal", "external_ref", "kind"):
        if body.get(key) is not None and str(body[key]).strip():
            metadata[key] = str(body[key]).strip()
    metadata.setdefault("kind", "llm-chat")

    row = db_tx_core(
        auth.conn,
        lambda c: db_one(
            c,
            """SELECT maludb_chat_start(p_title => %s, p_account_name => %s, p_projects => %s::text[],
                                    p_subjects => %s::text[], p_verbs => %s::text[],
                                    p_metadata_jsonb => %s::jsonb) AS id""",
            [
                str(body.get("title") or "").strip() or None,
                str(body.get("account") or "").strip() or None,
                _pg_array(_text_array(body.get("projects"))),
                _pg_array(_text_array(body.get("subjects"))),
                _pg_array(_text_array(body.get("verbs"))),
                json.dumps(metadata),
            ],
        ),
    )
    scope = str(body.get("scope") or "").strip()
    if scope:
        # 0.106.0: whose transcript this is. A principal-bound request already lands in its home scope.
        db_tx_core(
            auth.conn,
            lambda c: db_one(c, "SELECT maludb_set_scope('chat_session', %s, %s) AS ok", [int(row["id"]), scope]),
        )
    return JSONResponse(status_code=201, content={"session": _session_row(auth, int(row["id"]))})


# ===========================================================================
# GET /v1/chat/sessions
# ===========================================================================


@router.get("/v1/chat/sessions")
def list_sessions(
    auth: Auth, principal: str | None = None, external_ref: str | None = None, state: str | None = None, limit: int = 50
):
    rows = db_query(
        auth.conn,
        """SELECT chat_session_id AS id, chat_title AS title, lifecycle_state AS state, message_count,
                  started_at::text AS started_at, last_message_at::text AS last_message_at,
                  closed_at::text AS closed_at, metadata_jsonb AS metadata
             FROM maludb_chat_session
            WHERE (%s::text IS NULL OR metadata_jsonb->>'principal' = %s)
              AND (%s::text IS NULL OR metadata_jsonb->>'external_ref' = %s)
              AND (%s::text IS NULL OR lifecycle_state = %s)
            ORDER BY COALESCE(last_message_at, started_at) DESC
            LIMIT %s""",
        [principal, principal, external_ref, external_ref, state, state, min(200, max(1, limit))],
    )
    for r in rows:
        r["id"], r["message_count"], r["metadata"] = int(r["id"]), int(r["message_count"] or 0), _jsonb(r["metadata"])
    return {"sessions": rows}


# ===========================================================================
# GET /v1/chat/search   (declared before /{session_id} so "search" is not read as an id)
# ===========================================================================


@router.get("/v1/chat/search")
def search_messages(auth: Auth, q: str = "", principal: str | None = None, role: str | None = None, limit: int = 20):
    needle = q.strip()
    if len(needle) < 2:
        json_error("missing_field", 'Query parameter "q" needs at least two characters.', 400)
    if role is not None and role not in ROLES:
        json_error("validation_failed", f'"role" must be one of: {", ".join(ROLES)}.', 422)
    pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db_query(
        auth.conn,
        """SELECT m.chat_session_id AS session_id, s.chat_title AS title, s.metadata_jsonb->>'principal' AS principal,
                  s.metadata_jsonb->>'external_ref' AS external_ref, m.ordinal, m.role,
                  m.content_text AS text, m.created_at::text AS created_at
             FROM maludb_chat_message m
             JOIN maludb_chat_session s ON s.chat_session_id = m.chat_session_id
            WHERE m.content_text ILIKE %s
              AND (%s::text IS NULL OR s.metadata_jsonb->>'principal' = %s)
              AND (%s::text IS NULL OR m.role = %s)
            ORDER BY m.created_at DESC
            LIMIT %s""",
        [pattern, principal, principal, role, role, min(100, max(1, limit))],
    )
    for r in rows:
        r["session_id"], r["ordinal"] = int(r["session_id"]), int(r["ordinal"])
    return {"query": needle, "messages": rows}


# ===========================================================================
# GET /v1/chat/sessions/{id}   ·   messages   ·   finalize
# ===========================================================================


@router.get("/v1/chat/sessions/{session_id}")
def get_session(auth: Auth, session_id: int):
    return {"session": _session_row(auth, session_id)}


@router.post("/v1/chat/sessions/{session_id}/messages")
async def append_messages(auth: Auth, session_id: int, request: Request):
    body = await request.json()
    raw = body.get("messages") if isinstance(body.get("messages"), list) else [body]
    if not raw or len(raw) > MAX_BATCH:
        json_error("validation_failed", f"Send between 1 and {MAX_BATCH} messages.", 422)
    messages = [normalise_message(m, i) for i, m in enumerate(raw)]
    _session_row(auth, session_id)

    def _append(conn):
        ids = []
        for m in messages:  # one transaction: a batch lands whole and in order, or not at all
            row = db_one(
                conn,
                """SELECT maludb_chat_append_message(p_chat_session_id => %s, p_role => %s,
                                        p_content_text => %s, p_content_jsonb => %s::jsonb,
                                        p_metadata_jsonb => %s::jsonb) AS id""",
                [session_id, m["role"], m["text"], m["content"], m["metadata"]],
            )
            ids.append(int(row["id"]))
        return ids

    ids = db_tx_core(auth.conn, _append)
    return JSONResponse(status_code=201, content={"session_id": session_id, "message_ids": ids, "appended": len(ids)})


@router.get("/v1/chat/sessions/{session_id}/messages")
def list_messages(auth: Auth, session_id: int):
    _session_row(auth, session_id)
    rows = db_query(
        auth.conn,
        """SELECT chat_message_id AS id, ordinal, role, content_text AS text, content_jsonb AS content,
                  token_estimate, COALESCE(tool_call_id, metadata_jsonb->>'tool_call_id') AS tool_call_id,
                  created_at::text AS created_at, metadata_jsonb AS metadata
             FROM maludb_chat_messages(%s) ORDER BY ordinal""",
        [session_id],
    )
    for r in rows:
        r["id"], r["ordinal"] = int(r["id"]), int(r["ordinal"])
        r["content"], r["metadata"] = _jsonb(r["content"]), _jsonb(r["metadata"])
    return {"session_id": session_id, "messages": rows}


@router.post("/v1/chat/sessions/{session_id}/finalize")
def finalize_session(auth: Auth, session_id: int):
    _session_row(auth, session_id)
    row = db_tx_core(auth.conn, lambda c: db_one(c, "SELECT maludb_chat_finalize(%s) AS result", [session_id]))
    return {"session": _session_row(auth, session_id), "result": _jsonb(row["result"]) if row else None}
