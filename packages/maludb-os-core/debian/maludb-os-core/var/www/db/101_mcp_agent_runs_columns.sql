-- 101_mcp_agent_runs_columns.sql
-- mcp_agent_runs predates the runtime (050) and cannot show what a run was asked or what it
-- answered — the first thing anyone wants to know about an agent. The five columns db/097 added
-- join the view; the row filter (app_can_see_run) is untouched, so nobody sees a run they could
-- not see before. New columns go last: CREATE OR REPLACE VIEW can only append.

BEGIN;

CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id,
       r.location_id, r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id,
       r.harness, r.sdk_version, r.request_id, r.project_id, r.task_id, r.campaign_id, r.status,
       r.error, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
       r.cost, r.currency, r.started_at, r.finished_at,
       r.instructions, r.result, r.parent_run_id, r.requested_by, r.approval_request_id
FROM agent_runs r
LEFT JOIN members am ON am.id = r.agent_member_id
WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);

COMMIT;
