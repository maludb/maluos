"""maludb_os_records_mcp — record-memory MCP server (PostgreSQL, read-only).

Every tool reads the mcp_* views, which embed the §3.2 visibility rules keyed on the
caller's member context. Read-only by construction: the role can touch nothing else.
Tool surface: docs/mcp-tool-surface.md.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

import db

RO = {"readOnlyHint": True, "openWorldHint": False}
mcp = FastMCP("maludb_os_records_mcp")


async def _pool():
    return await db.get_pool(db.ENV["MCP_RECORDS_DB_USER"], db.ENV["MCP_RECORDS_DB_PASSWORD"])


async def _q(sql: str, *args) -> str:
    return db.to_json(await db.fetch_scoped(await _pool(), sql, *args))


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# The cert-study tools (calendar, attempts, plans, study log, issues, resources, events, member
# reports) retired with their tables in the kernel cut of 2026-09-22 (db/133).


class SearchIn(_Base):
    sql: str = Field(..., description="A single read-only SELECT over the mcp_* views (see below).")


@mcp.tool(name="records_search", annotations={"title": "Records search (SQL)", **RO})
async def records_search(params: SearchIn) -> str:
    """Run one read-only SELECT over the record-memory views for the long tail. Readable
    views are the kernel's mcp_* views: the directory (mcp_team_directory, mcp_departments,
    mcp_department_members, mcp_module_grants), the estate (mcp_locations, mcp_location_residents,
    mcp_location_tasks), applications (mcp_applications, mcp_application_endpoints,
    mcp_application_access, mcp_application_catalog, mcp_my_applications), the agent workforce
    (mcp_agents, mcp_agent_config_versions, mcp_agent_tool_grants, mcp_agent_duties,
    mcp_agent_runs, mcp_agent_run_events, mcp_prompt_ledger, mcp_ai_usage_postings,
    mcp_model_registry, mcp_hr_events, mcp_performance_reviews, mcp_agent_escalations),
    approvals (mcp_approval_requests, mcp_approval_policies), evals (mcp_eval_sets, mcp_eval_cases,
    mcp_eval_runs, mcp_eval_results, mcp_run_verdicts) and skills (mcp_skill_assignments,
    mcp_skill_proposals). Results are already scoped to what you may see. One statement, 5s
    timeout, 200-row cap."""
    return await db.run_search(await _pool(), params.sql)


# ---- Business OS tools ----------------------------------------------------
# Registered from their own modules so each slice adds its tools in one place
# (docs/business-os-mcp-tool-surface.md).
import business_estate
import business_agents
import business_applications
import business_approvals
import business_skills
import business_messages
import business_team
import business_aiops

business_estate.register(mcp, _q)
business_agents.register(mcp, _q)
business_applications.register(mcp, _q)
business_approvals.register(mcp, _q, db.request_member_id.get)
business_skills.register(mcp, _q)
business_messages.register(mcp, _q)
business_approvals.register_policy_and_history(mcp, _q)
business_team.register(mcp, _q)
business_aiops.register(mcp, _q)


if __name__ == "__main__":
    import server_common
    server_common.run(mcp, "MCP_RECORDS_DB_USER", "MCP_RECORDS_DB_PASSWORD", port=8811, endpoint_name="Records MCP")
