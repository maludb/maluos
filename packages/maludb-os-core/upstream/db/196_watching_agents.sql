-- 196: the watching agents (MaluOS Phase 14 slice 4c; maluos docs/phase14-watching-agents.md).
--
-- Three system_one agents in IT read the estate's node reports (db/188) and the samples of their numbers (db/195):
-- the database administrator (watch_postgres), the Linux administrator (watch_linux), the security officer
-- (watch_security). Deterministic playbooks: thresholds, no model. Like the Sysadmin's health playbook they keep
-- one row per check in system_probes (probe = 'node:<id>:<area>:<check>') and record a decision when a status
-- changes; shadow first. The runner (app_runner) reads no business records (db/097): the nodes and their samples
-- are handed over by two narrow SECURITY DEFINER functions. Additive.

ALTER TABLE system_one_decisions DROP CONSTRAINT system_one_decisions_playbook_check;
ALTER TABLE system_one_decisions ADD CONSTRAINT system_one_decisions_playbook_check
    CHECK (playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity', 'health', 'logs_and_guardrails',
                        'watch_postgres', 'watch_linux', 'watch_security'));

-- The estate's active nodes with their last report. No token, no key, no enrolment detail.
CREATE FUNCTION watch_nodes() RETURNS TABLE (location_id bigint, name text, kind text, node_role text, presence text,
    last_seen_at timestamptz, last_report_at timestamptz, silent_s integer, report jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT l.id, l.name, l.kind, l.node_role, l.presence, l.last_seen_at, l.last_report_at,
           CASE WHEN l.last_seen_at IS NULL THEN NULL ELSE extract(epoch FROM now() - l.last_seen_at)::integer END, l.report
      FROM locations l
     WHERE l.kind IN ('server', 'inference') AND l.status = 'active'
     ORDER BY l.id
$$;

-- A node's samples of the last `hours` (at most thirty days of them exist), oldest first.
CREATE FUNCTION watch_node_samples(node bigint, hours integer) RETURNS TABLE (ts timestamptz, age_s integer, numbers jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT s.ts, extract(epoch FROM now() - s.ts)::integer, s.numbers
      FROM estate_node_samples s
     WHERE s.location_id = node AND s.ts > now() - make_interval(hours => least(greatest(hours, 1), 720))
     ORDER BY s.ts
$$;

REVOKE ALL ON FUNCTION watch_nodes(), watch_node_samples(bigint, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION watch_nodes(), watch_node_samples(bigint, integer) TO app_runner;
