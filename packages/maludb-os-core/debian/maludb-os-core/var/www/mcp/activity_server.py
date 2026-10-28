"""maludb_os_activity_mcp — activity-memory MCP server (MaluDB / activity_log, read-only).

Reads the mcp_activity_* views, which scope to the caller (own trail + public feed;
organizers additionally get the community stream). Read-only by construction.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

import db

RO = {"readOnlyHint": True, "openWorldHint": False}
mcp = FastMCP("maludb_os_activity_mcp")


async def _pool():
    return await db.get_pool(db.ENV["MCP_ACTIVITY_DB_USER"], db.ENV["MCP_ACTIVITY_DB_PASSWORD"])


async def _q(sql: str, *args) -> str:
    return db.to_json(await db.fetch_scoped(await _pool(), sql, *args))


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class TimelineIn(_Base):
    date_from: str | None = None
    date_to: str | None = None
    action_prefix: str | None = Field(None, description="e.g. 'agent.' or 'application.'")


@mcp.tool(name="actor_timeline", annotations={"title": "My activity timeline", **RO})
async def actor_timeline(params: TimelineIn) -> str:
    """The caller's own activity trail (what they did in the app, when)."""
    w, a = [], []
    if params.date_from:
        a.append(params.date_from); w.append(f"occurred_at >= ${len(a)}::timestamptz")
    if params.date_to:
        a.append(params.date_to); w.append(f"occurred_at <= (${len(a)}::date + 1)")
    if params.action_prefix:
        a.append(params.action_prefix + "%"); w.append(f"action LIKE ${len(a)}")
    where = (" WHERE " + " AND ".join(w)) if w else ""
    return await _q(f"SELECT occurred_at, source, action, screen, entity_type, entity_id FROM mcp_activity_my{where} ORDER BY occurred_at DESC LIMIT 200", *a)


class RecordHistoryIn(_Base):
    entity_type: str
    entity_id: int


@mcp.tool(name="record_history", annotations={"title": "Record history", **RO})
async def record_history(params: RecordHistoryIn) -> str:
    """The change history of one record (who changed it, when, before/after)."""
    return await _q(
        "SELECT occurred_at, actor_name, action, before, after FROM mcp_activity_record_history WHERE entity_type = $1 AND entity_id = $2 ORDER BY occurred_at",
        params.entity_type, params.entity_id,
    )


class SinceIn(_Base):
    since: str | None = Field(None, description="ISO timestamp; defaults to the last 7 days")


@mcp.tool(name="since_last_login", annotations={"title": "What changed recently", **RO})
async def since_last_login(params: SinceIn) -> str:
    """Public community activity since a time (new issues, replies, events, resources,
    plans) — 'what changed since I last logged in?'."""
    since = params.since
    where = "WHERE occurred_at >= $1::timestamptz" if since else "WHERE occurred_at >= now() - interval '7 days'"
    args = [since] if since else []
    return await _q(f"SELECT occurred_at, action, entity_type, entity_id FROM mcp_activity_community_feed {where} ORDER BY occurred_at DESC LIMIT 200", *args)


class SearchIn(_Base):
    sql: str = Field(..., description="A single read-only SELECT over the activity views.")


@mcp.tool(name="activity_search", annotations={"title": "Activity search (SQL)", **RO})
async def activity_search(params: SearchIn) -> str:
    """Run one read-only SELECT over the activity views for the long tail. Readable views:
    mcp_activity_my (occurred_at, source, action, screen, route, entity_type, entity_id,
    before, after, request_id), mcp_activity_record_history, mcp_activity_community_feed
    (+ organizer-only mcp_activity_community). Scoped to what you may see. One statement,
    5s timeout, 200-row cap."""
    return await db.run_search(await _pool(), params.sql)


if __name__ == "__main__":
    import server_common
    server_common.run(mcp, "MCP_ACTIVITY_DB_USER", "MCP_ACTIVITY_DB_PASSWORD", port=8812, endpoint_name="Activity MCP")
