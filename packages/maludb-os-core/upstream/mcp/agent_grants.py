"""Tool grants — and a disabled application's tools (module_status.py) — enforced at the MCP boundary.

A person's token sees every tool on a server (row visibility does the scoping). An AGENT sees —
and may call — only the tools it holds a live agent_tool_grants row for on THIS server's
registered endpoint. install() replaces FastMCP's list_tools / call_tool handlers with versions
that ask mcp_agent_tool_grants_for() (db/099) who the caller is first.

The grant table was advisory until this module: a hired agent's token listed the whole server.
Hermes is also rendered with tools.include = the granted names, but that is the agent's own
configuration and therefore not a control; this is.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import content_screen
import db
import module_status

log = logging.getLogger("agent_grants")


def constraint_violation(constraints: dict, arguments: dict) -> str | None:
    """The one constraint the grant form offers today: max_amount, checked against the call's
    `amount`. Arguments may arrive nested under a single `params` model."""
    if not constraints:
        return None
    args = arguments.get("params") if isinstance(arguments.get("params"), dict) else arguments
    limit = constraints.get("max_amount")
    if limit is not None and args.get("amount") is not None:
        try:
            if float(args["amount"]) > float(limit):
                return f"amount {args['amount']} is above this agent's limit of {limit} for the tool"
        except (TypeError, ValueError):
            return "amount is not a number"
    return None


async def _screened(result, tool: str, get_pool, member_id: int | None):
    """Put a platform notice in front of a tool result that carries instruction-like text, and record
    the hit (db/123). The data is still delivered — the agent needs it — and a failure to record never
    breaks the call. People's tool calls are not screened: they read records as they are."""
    blocks = result[0] if isinstance(result, tuple) else result
    if not isinstance(blocks, (list, tuple)):
        return result
    texts = [b for b in blocks if getattr(b, "type", None) == "text" and isinstance(getattr(b, "text", None), str)]
    hits = content_screen.scan("\n".join(b.text for b in texts))
    if not hits or not texts:
        return result
    texts[0].text = content_screen.notice(hits) + texts[0].text
    try:
        pool = await get_pool()
        async with pool.acquire() as con:
            for h in hits:
                await con.fetchval("SELECT record_content_flag($1,$2,'tool_result',$3,$4,$5,'flagged')",
                                   member_id, db.request_run_id.get(), tool, h["pattern"], h["excerpt"])
    except Exception as exc:  # noqa: BLE001
        log.warning("content flag on %s was not recorded: %s", tool, exc)
    return result


def install(mcp: FastMCP, endpoint_name: str, get_pool: Callable[[], Awaitable[Any]],
            current_member_id: Callable[[], int | None]) -> None:
    async def grants() -> dict | None:
        """None = a person (no filtering). A dict = the agent's granted tools -> constraints."""
        member_id = current_member_id()
        if member_id is None:
            return {}  # no identity: nothing is granted
        pool = await get_pool()
        async with pool.acquire() as con:
            raw = await con.fetchval("SELECT mcp_agent_tool_grants_for($1, $2)", member_id, endpoint_name)
        info = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return info.get("tools", {}) if info.get("is_agent") else None

    async def list_tools():
        tools = await mcp.list_tools()
        closed = await module_status.disabled_modules(await get_pool())
        if closed:                                    # a disabled application's tools are not offered
            tools = [t for t in tools if module_status.tool_module(mcp, t.name) not in closed]
        granted = await grants()
        return tools if granted is None else [t for t in tools if t.name in granted]

    async def call_tool(name: str, arguments: dict[str, Any]):
        # Before the grant: a disabled application is closed to everyone, a person's token included.
        if module_status.tool_module(mcp, name) in await module_status.disabled_modules(await get_pool()):
            raise ToolError(f"'{name}' belongs to an application that is switched off for this business.")
        granted = await grants()
        if granted is not None:
            if name not in granted:
                raise ToolError(f"'{name}' is not among the tools this agent was granted on {endpoint_name}.")
            problem = constraint_violation(granted[name] or {}, arguments or {})
            if problem:
                raise ToolError(f"Refused by the tool grant: {problem}.")
        result = await mcp.call_tool(name, arguments)
        if granted is not None:                       # an agent is reading this: screen it (content_screen.py)
            result = await _screened(result, name, get_pool, current_member_id())
        return result

    mcp._mcp_server.list_tools()(list_tools)
    mcp._mcp_server.call_tool(validate_input=False)(call_tool)
