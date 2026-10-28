-- 073_agent_views_carry_new_columns.sql
-- Fixes a defect I introduced across db/070, db/071 and db/072, found in review.
--
-- Each of those migrations added columns to agent_profiles or agent_config_versions and did not
-- extend the mcp_* views that read them. So the only way for the app to reach the new facts was
-- to join back to the base tables — which the follow-up pass duly did, in PHP *and* in
-- mcp/business_agents.py. In PHP that merely breaks the project's "reads go through mcp_* views"
-- rule. In the MCP layer it breaks the tools outright, because app_records_ro holds SELECT on
-- the views and on no base table by design:
--
--     ERROR: permission denied for table agent_profiles
--
-- find_agents and agent_profile were failing for every agent and MCP client while the screens
-- worked, which is the same screen-versus-data split as db/067 — and, like that one, it was
-- mine. The rule this keeps proving: a migration that adds a column owes the view that exposes
-- it, in the same migration.
--
-- mcp_agents keeps its app_can_see_agent() masking on the budget and current config version;
-- the identity fields are not masked, because who an agent is and what it is for is exactly the
-- insider-readable part (question H1's audience is "all").

BEGIN;

DROP VIEW mcp_agents;

CREATE VIEW mcp_agents AS
 SELECT ap.member_id AS agent_member_id,
    m.display_name,
    m.job_title,
    ap.status,
    ap.agent_kind,
    ap.is_office_manager,
    ap.description,
    ap.role_key,
    ap.profile_pic_url,
    ap.manager_member_id,
    mm.display_name AS manager_name,
    ap.home_location_id,
    mr.model_key,
    mr.harness,
        CASE WHEN app_can_see_agent(ap.member_id) THEN ap.current_config_version_id
             ELSE NULL::bigint END AS current_config_version_id,
        CASE WHEN app_can_see_agent(ap.member_id) THEN ap.monthly_budget_amount
             ELSE NULL::numeric END AS monthly_budget_amount,
    ap.budget_currency,
    ap.hired_at,
    ap.suspended_at,
    ap.offboarded_at,
    -- How many subagents this orchestrator manages, and how many rosters this subagent is on.
    -- Both are zero for the other kind, which is the honest answer rather than NULL.
    ( SELECT count(*) FROM agent_subagents s
       WHERE s.orchestrator_member_id = ap.member_id AND s.removed_at IS NULL) AS subagent_count,
    ( SELECT count(*) FROM agent_subagents s
       WHERE s.subagent_member_id = ap.member_id AND s.removed_at IS NULL) AS orchestrator_count
   FROM agent_profiles ap
     JOIN members m ON m.id = ap.member_id
     JOIN members mm ON mm.id = ap.manager_member_id
     JOIN model_registry mr ON mr.id = ap.model_id
  WHERE app_is_insider();

ALTER VIEW mcp_agents SET (security_barrier = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agents TO app_rw;
GRANT SELECT ON mcp_agents TO app_records_ro;

-- Config versions carry the prompt pointer and enough of the prompt to be readable without a
-- second lookup. New columns are appended, so CREATE OR REPLACE keeps the grants.
CREATE OR REPLACE VIEW mcp_agent_config_versions AS
 SELECT v.id AS config_version_id,
    v.agent_member_id,
    v.version_no,
    v.job_description,
    v.model_id,
    v.harness_config,
    v.tool_grants,
    v.schedule,
    v.monthly_budget_amount,
    v.change_note,
    v.created_by,
    v.created_at,
    v.gating_eval_run_id,
    v.activated_at,
    v.activated_by,
    v.system_prompt_id,
    v.system_prompt_version,
    p.prompt_key AS system_prompt_key,
    p.name AS system_prompt_name
   FROM agent_config_versions v
   LEFT JOIN system_prompts p ON p.id = v.system_prompt_id
  WHERE app_can_see_agent(v.agent_member_id);

COMMIT;
