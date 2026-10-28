"""A DISABLED application's tools are closed — to people's tokens and to agents alike.

A super-admin gives every application one of three statuses (nav_items.status, db/127–129;
docs/build-specs/data-driven-nav.md): active, hidden (no sidebar entry, still usable here) or
disabled. Disabled means closed everywhere, and this is where the read servers close it: the row
rule cannot, because many mcp_* views are gated on something other than the module grant.

A tool belongs to the application whose file registered it (`business_estate.py` → the
`locations` grant). The kernel cut of 2026-09-22 (db/133) removed every business module; only the
kernel's own files remain here. Write tools need no entry here: each one POSTs to a PHP handler, and
require_module() refuses there. A new business_*.py file adds a line to OWNER.
"""
from __future__ import annotations

from typing import Any

# python module that registers the tools -> the module grant of the application they belong to.
# None = part of the platform itself (cannot be disabled).
OWNER: dict[str, str | None] = {
    "business_estate": "locations", "business_agents": "hr", "business_skills": "hr",
    "business_applications": "applications", "business_approvals": "approvals", "business_aiops": "ledger",
    "business_team": None, "business_actions": None,
}


def tool_module(mcp, name: str) -> str | None:
    """The module grant a tool belongs to, or None when it is the platform's own."""
    tool = mcp._tool_manager._tools.get(name)
    return OWNER.get(getattr(getattr(tool, "fn", None), "__module__", ""), None)


async def disabled_modules(pool: Any) -> set[str]:
    async with pool.acquire() as con:
        return set(await con.fetchval("SELECT app_disabled_modules()") or [])
