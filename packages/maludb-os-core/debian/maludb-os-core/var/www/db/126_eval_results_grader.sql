-- 126: an eval result says how it was graded, and whether a person has yet.
--
-- A run's score counts only what has been GRADED (owner, 2026-09-20): a human-graded case waits
-- for a person and is in neither the passed nor the failed column until they say. mcp_eval_results
-- could not show that — it carried `passed`, which for an ungraded human case is merely the
-- placeholder the runner wrote, and a reader would take it for a failure.
--
-- Two columns appended (never inserted mid-list) and the security barrier kept, per the migration
-- rules in CLAUDE.md:
--   grader     — how this case is graded, from eval_cases
--   graded_by  — the person who graded it, NULL when nobody has
--
-- Additive; the view is replaced with the same rows and the same rule (people only).
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/126_eval_results_grader.sql

BEGIN;

CREATE OR REPLACE VIEW mcp_eval_results WITH (security_barrier = true) AS
SELECT er.id AS eval_result_id,
       er.eval_run_id,
       er.eval_case_id,
       c.title AS case_title,
       er.agent_run_id,
       er.passed,
       er.score,
       er.grader_notes,
       er.created_at,
       -- appended:
       c.grader,
       er.graded_by,
       -- A result is IN the run's score only when it has actually been graded. A `human` case with
       -- no grader_by is awaiting a person: not a pass, not a fail, and not evidence of either.
       (c.grader <> 'human' OR er.graded_by IS NOT NULL) AS is_graded
  FROM eval_results er
  JOIN mcp_eval_runs r ON r.eval_run_id = er.eval_run_id
  JOIN eval_cases c ON c.id = er.eval_case_id
 WHERE app_member_kind() = 'human';

GRANT SELECT ON mcp_eval_results TO app_rw, app_records_ro;

COMMIT;
