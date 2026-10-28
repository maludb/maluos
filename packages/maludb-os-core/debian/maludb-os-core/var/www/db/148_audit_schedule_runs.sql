-- 148: the Auditor reads which eval runs its schedules produced through a narrow function, like every
-- other read of the playbooks (db/145) — the runner has no privilege on eval_schedules itself.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/148_audit_schedule_runs.sql
BEGIN;
CREATE FUNCTION audit_schedule_eval_runs() RETURNS TABLE (eval_run_id bigint, schedule_id bigint, regression_delta numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT h.last_eval_run_id, h.id, h.regression_delta FROM eval_schedules h WHERE h.last_eval_run_id IS NOT NULL;
$$;
GRANT EXECUTE ON FUNCTION audit_schedule_eval_runs() TO app_runner;
COMMIT;
