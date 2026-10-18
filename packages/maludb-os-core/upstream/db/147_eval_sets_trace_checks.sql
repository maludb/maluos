-- 147: the eval-set view carries the Auditor's trace checks (db/145 added the column). Column appended.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/147_eval_sets_trace_checks.sql
BEGIN;
CREATE OR REPLACE VIEW mcp_eval_sets WITH (security_barrier = true) AS
 SELECT id AS eval_set_id, name, description, agent_member_id, role_key, department_id, pass_threshold, status,
        created_at, updated_at, trace_checks
   FROM eval_sets
  WHERE app_can_see_evals(agent_member_id);
COMMIT;
