-- 125: the agent runner may work an evaluation.
--
-- db/046 defined evaluations and db/097 gave the runner exactly what rendering a profile and
-- scheduling a duty need — which was right at the time, because nothing ran an evaluation. The
-- eval runner (docs/build-specs/eval-runner.md) does, so it needs the set it is running, the cases
-- in it, and somewhere to write each case's result and the run's score.
--
-- The grants are the boundary, as db/097 says: a policy cannot give a role a privilege it was
-- never granted, so the column list on eval_runs is deliberately short. The runner may say how a
-- run went; it may NOT change what the run was asked to test — not its set, not its agent, not its
-- config version, not its threshold, and not who started it. An evaluation that could rewrite its
-- own question is not evidence.
--
-- eval_sets and eval_cases stay read-only to it: cases are people's work (the endpoints refuse
-- agent callers, and the runner is not a person either).
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/125_runner_reads_evals.sql

BEGIN;

GRANT SELECT ON eval_sets, eval_cases TO app_runner;

GRANT SELECT, INSERT, UPDATE ON eval_results TO app_runner;
GRANT USAGE, SELECT ON SEQUENCE eval_results_id_seq TO app_runner;

GRANT SELECT ON eval_runs TO app_runner;
GRANT UPDATE (status, score, cases_total, cases_passed, cost, started_at, finished_at, updated_at)
    ON eval_runs TO app_runner;

-- The runner's own check that an evaluation changed nothing (mcp/agent_runner/evals.py). It needs
-- ONE fact about a run — did anything happen under it — and db/097's rule is that the runner reads
-- no business records, so it gets a narrow SECURITY DEFINER function rather than the activity log.
-- Same shape as db/123's record_content_flag, and for the same reason.
CREATE OR REPLACE FUNCTION run_changed_anything(p_run_id bigint)
RETURNS TABLE (action text) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT DISTINCT a.action FROM activity_log a
     WHERE a.agent_run_id = p_run_id
       AND a.action NOT LIKE 'screen.%'
       AND a.action NOT IN ('agent_run.start', 'agent_run.finish', 'notification.sent')
     ORDER BY a.action LIMIT 20
$$;
REVOKE ALL ON FUNCTION run_changed_anything(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION run_changed_anything(bigint) TO app_runner, app_rw;

COMMENT ON FUNCTION run_changed_anything(bigint) IS
    'Which state-changing actions a run took, by name. The eval runner asks it of every trial: an evaluation that changed something is stopped at once.';

-- The same permissive policy db/097 gives every table the runner works with: RLS is on these
-- tables for PEOPLE (mcp_eval_* decide who sees what); the runner's boundary is the GRANT above.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['eval_sets', 'eval_cases', 'eval_runs', 'eval_results'] LOOP
        IF (SELECT relrowsecurity FROM pg_class WHERE oid = t::regclass) THEN
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_runner', t);
            EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_runner USING (true) WITH CHECK (true)',
                           t || '_runner', t);
        END IF;
    END LOOP;
END $$;

COMMIT;
