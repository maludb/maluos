"""maludb_os_actions_mcp — the actions/navigation MCP server (localhost-only).

Unlike the read servers, this one acts AS a member: the assistant service passes a
short-lived signed action token (Authorization: Bearer <action_token>) minted by the PHP
/assistant handler. navigate() returns an HX-Location directive; action tools resolve
entities via the read views then POST to the app's own PHP endpoints with the action token
(same validation, authorization, and activity logging a human triggers). Never exposed
through Apache.
"""
from __future__ import annotations

import contextvars
import hmac
import json
import re
import time
from hashlib import sha256

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

import db

APP_BASE = "http://127.0.0.1:8080"     # the PHP JSON API — localhost-only since the cut-over (Apache :8080)
mcp = FastMCP("maludb_os_actions_mcp")

# Per-request context set by the auth middleware.
action_token: contextvars.ContextVar[str] = contextvars.ContextVar("action_token", default="")
action_member: contextvars.ContextVar[int | None] = contextvars.ContextVar("action_member", default=None)


# One verifier for all three servers (mcp/db.py): it accepts the assistant's three-part action token
# and the agent runner's four-part run token, and refuses everything when ACTION_TOKEN_KEY is unset
# — this server's own copy had no such guard, so an empty key would have verified a forged token.
verify_action_token = db.verify_action_token


async def _read_pool():
    return await db.get_pool(db.ENV["MCP_RECORDS_DB_USER"], db.ENV["MCP_RECORDS_DB_PASSWORD"])


async def _resolve_one(sql: str, *args):
    """Run a read query scoped to the acting member; return the first row or None."""
    rows = await db.fetch_scoped(await _read_pool(), sql, *args, member_id=action_member.get(), role="member")
    return rows[0] if rows else None


def _relay_headers(token: str) -> dict:
    """PHP honours an agent RUN token only when this server vouches for it: the agent holds the
    token, never the relay key, so it cannot POST to a handler itself and step around its grants."""
    # JSON mode (docs/react-migration-plan.md): the HTML/HTMX branches are gone at cut-over, and
    # json_mode_finish() answers every handler from what it reported.
    headers = {"X-Action-Token": token, "Accept": "application/json"}
    if token.count(".") == 3:
        signature = db.relay_signature(token)
        if signature:
            headers["X-Action-Relay"] = signature
    return headers


# An evaluation must be able to run on a Tuesday afternoon without anyone bracing for it, so an
# eval run may not change anything (docs/build-specs/eval-runner.md). The answer is cached per run
# because it cannot change: a run's trigger is written when the run is created and never updated.
_eval_runs: dict[int, bool] = {}


class CannotTell(Exception):
    """We could not establish whether this call belongs to an evaluation."""


async def _is_eval_run(run_id: int | None) -> bool:
    """Is the run this call belongs to an evaluation? Asked of the RUN ROW, never of the token —
    the agent holds the token, so nothing it holds may claim or deny this.

    When it cannot be established, this RAISES rather than guessing either way. Letting the write
    through would break the one rule an eval run has; answering "recorded" would tell an ordinary
    agent its work was done when it was not. Refusing is the only honest third answer."""
    if run_id is None:
        return False
    if run_id not in _eval_runs:
        try:
            # mcp_agent_runs, not agent_runs: this server reads as app_records_ro, which has no
            # privilege on the base table at all — asking it was why the first attempt could not
            # tell, and (correctly) refused every write rather than guessing.
            rows = await db.fetch_scoped(await _read_pool(),
                                         "SELECT trigger FROM mcp_agent_runs WHERE agent_run_id = $1", run_id,
                                         member_id=action_member.get(), role="member")
        except Exception as exc:      # noqa: BLE001
            raise CannotTell(str(exc)) from exc
        if not rows:
            raise CannotTell(f"run {run_id} is not visible to this caller")
        _eval_runs[run_id] = rows[0]["trigger"] == "eval"
        if len(_eval_runs) > 500:
            _eval_runs.pop(next(iter(_eval_runs)))
    return _eval_runs[run_id]


async def app_post(path: str, fields: dict, base: str = APP_BASE) -> dict:
    """POST to an app endpoint with the action token, in JSON mode, and read PHP's answer:
    {ok: true, did, location…} · 202 {status: pending_approval} · 4xx {error: {message, errors}}.

    Except under an evaluation, where the call is RECORDED AND NEVER SENT. This is the one control
    that makes an eval run safe, and it sits here — at the MCP boundary, where tool grants are
    enforced — rather than in a handler or in the agent's persona, neither of which is a control."""
    try:
        evaluating = await _is_eval_run(db.request_run_id.get())
    except CannotTell as why:
        return {"status": "error", "http_status": 503,
                "message": "This action was not attempted: the platform could not establish whether "
                           f"this run is an evaluation, and an evaluation may not change anything ({why}). "
                           "Nothing was changed. Report this and stop.",
                "errors": []}
    if evaluating:
        return {"status": "recorded", "would_have_called": path,
                "arguments": {k: v for k, v in fields.items() if k != "csrf_token"},
                "note": "This is an evaluation. The action was recorded and NOTHING was changed. "
                        "Carry on as though it had succeeded, and say in your report what you did."}
    async with httpx.AsyncClient(base_url=base, timeout=20.0) as c:
        r = await c.post(path, data=fields, headers=_relay_headers(action_token.get()))
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return {"status": "success" if r.status_code < 400 else "error", "http_status": r.status_code}
    if body.get("ok") is True:
        out = {k: v for k, v in body.items() if k != "ok"}
        # A create answered a sentence and no id, while most follow-on tools need one (action
        # smoke, 2026-09-19). PHP already says where the record lives; its id is the path's tail.
        # A handler that names its record itself (a scope added to an application, db/141) is believed.
        found = re.search(r"/(\d+)/?(?:[?#].*)?$", str(body.get("location", "")))
        if found and "record_id" not in out:
            out["record_id"] = int(found.group(1))
        return {"status": "success", **out}
    if body.get("status") == "pending_approval":
        return {k: v for k, v in body.items() if k != "ok"}
    error = body.get("error") or {}
    return {"status": "error", "http_status": r.status_code,
            "message": error.get("errors") or error.get("message") or "The action was rejected.",
            "errors": error.get("errors") or []}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# Business OS navigation + actions, generated from the action manifest
# (docs/business-os-action-manifest.md → mcp/action_registry.json).
#
# The cert-study screens and their four tools (log_study_time, post_issue, rsvp_event,
# record_exam_result) retired with the React cut-over, 2026-09-19: those modules were not ported.
# --------------------------------------------------------------------------
import business_actions

business_actions.register(mcp, app_post, _resolve_one, action_member.get)

# Applications from us (A7, 2026-09-22): their registries under mcp/registries/ become tools on
# this same door — approval hook in front, the eval control in app_post, the relay key here.
import application_actions

_taken = {a["action"] for a in business_actions.ACTIONS.values() if a.get("built")}
_app_tools = application_actions.register(mcp, app_post, action_token.get, _taken)


if __name__ == "__main__":
    import uvicorn

    import agent_grants

    agent_grants.install(mcp, "Actions MCP", _read_pool, action_member.get)
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else headers.get("x-action-token", "")
        mid = verify_action_token(token) if token else None
        if mid is None:
            body = json.dumps({"error": "unauthorized: valid action token required"}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        action_token.set(token)
        action_member.set(mid)
        # WHICH RUN this call belongs to. The read servers have always set it (server_common);
        # this server never did, because nothing here asked — until the eval rule, which must know
        # whether the caller is an evaluation before it lets a write through. Its absence is why
        # eval run 1 created two real tasks.
        run = db.verify_run_token(token)
        db.request_run_id.set(run[1] if run else None)
        await inner(scope, receive, send)

    uvicorn.run(app, host="127.0.0.1", port=8813, log_level="info")
