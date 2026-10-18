-- 145: the system_one harness and its first agents, the Auditor and the Sysadmin (2026-09-27 —
-- docs/build-specs/system-one-harness.md). Owner's decisions: scheduled evals are allowed (findings still
-- advise); the Auditor sits in Audit (agent work), the Sysadmin in IT (all ongoing monitoring, read-only);
-- a system_one agent runs a shipped playbook — collect, ask JEV, decide by thresholds, act — shadow first.
--
-- The runner (app_runner) reads no business records (db/097): what the playbooks need is handed over by
-- narrow SECURITY DEFINER functions here, the precedent of run_changed_anything() (db/125). Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/145_system_one.sql

BEGIN;

-- 1. The harness -----------------------------------------------------------------------------------------
ALTER TABLE model_registry DROP CONSTRAINT model_registry_harness_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_harness_check
    CHECK (harness IN ('claude_agent_sdk', 'openai_agents_sdk', 'openai_compatible', 'native', 'hermes', 'system_one'));
UPDATE model_registry SET harness = 'system_one', updated_at = now() WHERE model_key = 'jev:typesafe/jev-1.13';

-- 2. Trace checks on an eval set, and trace grades that say how they were graded ------------------------
ALTER TABLE eval_sets ADD COLUMN trace_checks jsonb;
ALTER TABLE eval_sets ADD CONSTRAINT eval_sets_trace_checks_shape
    CHECK (trace_checks IS NULL OR (jsonb_typeof(trace_checks) = 'array' AND jsonb_array_length(trace_checks) BETWEEN 1 AND 24));
COMMENT ON COLUMN eval_sets.trace_checks IS 'JEV checks the Auditor applies to sampled REAL runs of the set''s agent (same shape as eval_cases.checks).';
ALTER TABLE trace_grades ADD COLUMN grader_detail jsonb;
ALTER TABLE trace_grades ADD COLUMN awaiting_person boolean NOT NULL DEFAULT false;
ALTER TABLE trace_grades ADD COLUMN graded_by bigint REFERENCES members(id) ON DELETE SET NULL;
ALTER TABLE trace_grades ADD COLUMN graded_by_agent bigint REFERENCES members(id) ON DELETE SET NULL;

-- 3. What a system_one agent decided -----------------------------------------------------------------------
CREATE TABLE system_one_decisions (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_run_id    bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_member_id bigint NOT NULL REFERENCES members(id),
    playbook        text NOT NULL CHECK (playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity', 'health', 'logs_and_guardrails')),
    subject_kind    text NOT NULL,                     -- agent_run | eval_run | eval_schedule | system_event | probe | ledger | eval_result
    subject_id      bigint,
    subject_label   text,
    answers         jsonb,                             -- JEV's answers; NULL for a deterministic check
    decision        text NOT NULL CHECK (decision IN ('record', 'finding', 'alert', 'escalate', 'mute')),
    mode            text NOT NULL CHECK (mode IN ('shadow', 'live')),
    acted           boolean NOT NULL DEFAULT false,    -- false in shadow: what it WOULD have done
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX system_one_decisions_agent_idx ON system_one_decisions (agent_member_id, created_at DESC);
CREATE INDEX system_one_decisions_decision_idx ON system_one_decisions (decision, created_at DESC) WHERE decision <> 'record';

-- 4. The Sysadmin's events, probes and collector cursors ---------------------------------------------------
CREATE TABLE system_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fingerprint     text NOT NULL UNIQUE,
    source          text NOT NULL,                     -- journal:<unit> | apache:<file> | postgresql | guardrail:<kind>
    sample          text NOT NULL,                     -- one REDACTED occurrence
    first_seen      timestamptz NOT NULL,
    last_seen       timestamptz NOT NULL,
    occurrences     integer NOT NULL DEFAULT 1,
    category        text,                              -- bug | outage | security | guardrail | performance | noise
    severity        smallint CHECK (severity BETWEEN 0 AND 4),
    classification  jsonb,                             -- JEV's answers
    agent_member_id bigint REFERENCES members(id),     -- the Sysadmin that recorded it
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved', 'muted')),
    status_by       bigint REFERENCES members(id),
    status_at       timestamptz,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX system_events_open_idx ON system_events (severity DESC, last_seen DESC) WHERE status IN ('open', 'acknowledged');

CREATE TABLE system_probes (
    probe           text PRIMARY KEY,                  -- service:<unit> | disk:/ | memory | swap | backup | app:<key> | version:<key>
    status          text NOT NULL CHECK (status IN ('ok', 'warning', 'failed')),
    detail          text NOT NULL,
    measured        jsonb,
    agent_member_id bigint REFERENCES members(id),
    checked_at      timestamptz NOT NULL DEFAULT now(),
    changed_at      timestamptz NOT NULL DEFAULT now()  -- when the status last changed
);

CREATE TABLE system_collector_state (
    source      text PRIMARY KEY,
    cursor      text,
    last_run_at timestamptz,
    last_error  text
);

ALTER TABLE system_one_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_probes ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_collector_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY system_one_decisions_app_rw ON system_one_decisions TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY system_events_app_rw ON system_events TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY system_probes_app_rw ON system_probes TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY system_one_decisions_runner ON system_one_decisions TO app_runner USING (true) WITH CHECK (true);
CREATE POLICY system_events_runner ON system_events TO app_runner USING (true) WITH CHECK (true);
CREATE POLICY system_probes_runner ON system_probes TO app_runner USING (true) WITH CHECK (true);
CREATE POLICY system_collector_state_runner ON system_collector_state TO app_runner USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON system_one_decisions, system_events, system_probes, system_collector_state TO app_runner;
GRANT SELECT, UPDATE ON system_events TO app_rw;
GRANT SELECT ON system_one_decisions, system_probes TO app_rw;

-- 5. What the playbooks may read (SECURITY DEFINER, narrow) -------------------------------------------------

-- Scheduled evals that are due, with the set's agent.
CREATE FUNCTION audit_due_schedules() RETURNS TABLE (schedule_id bigint, eval_set_id bigint, set_name text, kind text,
    cadence text, sample_size integer, regression_delta numeric, agent_member_id bigint, last_eval_run_id bigint,
    trace_checks jsonb, set_status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT h.id, h.eval_set_id, s.name, h.kind, h.cadence, h.sample_size, h.regression_delta, s.agent_member_id,
           h.last_eval_run_id, s.trace_checks, s.status
      FROM eval_schedules h JOIN eval_sets s ON s.id = h.eval_set_id
     WHERE h.active AND s.status = 'active' AND (h.next_run_at IS NULL OR h.next_run_at <= now())
     ORDER BY h.next_run_at NULLS FIRST, h.id;
$$;

-- A schedule has been worked: when it next falls due.
CREATE FUNCTION audit_schedule_worked(p_schedule bigint, p_eval_run bigint) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path TO 'public' AS $$
    UPDATE eval_schedules SET last_run_at = now(), last_eval_run_id = COALESCE(p_eval_run, last_eval_run_id),
           next_run_at = now() + CASE cadence WHEN 'hourly' THEN interval '1 hour' WHEN 'daily' THEN interval '1 day'
                                               WHEN 'weekly' THEN interval '7 days' WHEN 'monthly' THEN interval '1 month'
                                               ELSE interval '1 day' END,
           updated_at = now()
     WHERE id = p_schedule;
$$;

-- A finished eval run and the one before it on the same set (for regression).
CREATE FUNCTION audit_eval_run_outcome(p_eval_run bigint) RETURNS TABLE (eval_run_id bigint, status text, score numeric,
    previous_run_id bigint, previous_score numeric, eval_set_id bigint, agent_member_id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT r.id, r.status, r.score,
           (SELECT p.id FROM eval_runs p WHERE p.eval_set_id = r.eval_set_id AND p.id < r.id AND p.score IS NOT NULL ORDER BY p.id DESC LIMIT 1),
           (SELECT p.score FROM eval_runs p WHERE p.eval_set_id = r.eval_set_id AND p.id < r.id AND p.score IS NOT NULL ORDER BY p.id DESC LIMIT 1),
           r.eval_set_id, r.agent_member_id
      FROM eval_runs r WHERE r.id = p_eval_run;
$$;

-- Real (non-eval) finished runs of an agent since a moment, newest first, at most p_limit; never one
-- already graded.
CREATE FUNCTION audit_sample_runs(p_agent bigint, p_since timestamptz, p_limit integer) RETURNS TABLE (
    agent_run_id bigint, instructions text, result text, finished_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT r.id, r.instructions, r.result, r.finished_at
      FROM agent_runs r
     WHERE r.agent_member_id = p_agent AND r.trigger <> 'eval' AND r.status IN ('succeeded', 'awaiting_approval')
       AND r.finished_at >= p_since
       AND NOT EXISTS (SELECT 1 FROM trace_grades g WHERE g.agent_run_id = r.id)
     ORDER BY r.finished_at DESC LIMIT GREATEST(1, LEAST(p_limit, 50));
$$;

-- Gaps in the evidence since a moment: a finished agent run with no ledger row (its harness makes model
-- calls); a run voided because a call went unledgered; an evaluation that changed something; a JEV result
-- without its detail.
CREATE FUNCTION audit_evidence_gaps(p_since timestamptz) RETURNS TABLE (kind text, subject_kind text, subject_id bigint,
    agent_member_id bigint, detail text, occurred_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT 'run_without_ledger', 'agent_run', r.id, r.agent_member_id,
           'A finished ' || r.harness || ' run has no prompt-ledger row.', r.finished_at
      FROM agent_runs r
     WHERE r.finished_at >= p_since AND r.status IN ('succeeded', 'awaiting_approval') AND r.harness <> 'system_one'
       AND NOT EXISTS (SELECT 1 FROM prompt_ledger l WHERE l.agent_run_id = r.id)
    UNION ALL
    SELECT 'unledgered_call', 'agent_run', r.id, r.agent_member_id, left(r.error, 300), r.finished_at
      FROM agent_runs r WHERE r.finished_at >= p_since AND r.error LIKE '%could not be written to the prompt ledger%'
    UNION ALL
    SELECT 'eval_changed_something', 'eval_run', e.id, e.agent_member_id, 'An evaluation was stopped because a trial changed something.', e.finished_at
      FROM eval_runs e WHERE e.finished_at >= p_since AND e.status = 'error'
       AND EXISTS (SELECT 1 FROM activity_log a WHERE a.entity_type = 'eval_run' AND a.entity_id = e.id AND a.after::text ILIKE '%changed%')
    UNION ALL
    SELECT 'jev_result_without_detail', 'eval_result', x.id, e.agent_member_id, 'A JEV-graded result has no grader_detail.', x.created_at
      FROM eval_results x JOIN eval_cases c ON c.id = x.eval_case_id AND c.grader = 'jev' JOIN eval_runs e ON e.id = x.eval_run_id
     WHERE x.created_at >= p_since AND x.grader_detail IS NULL;
$$;

-- Guardrail events since a moment, from the kernel's own tables.
CREATE FUNCTION system_guardrail_events(p_since timestamptz) RETURNS TABLE (kind text, subject_id bigint, occurred_at timestamptz, text text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT 'content_flag', f.id, f.occurred_at,
           'Instructions withheld from agent ' || f.agent_member_id || ' (' || f.source || '): ' || left(f.excerpt, 200)
      FROM agent_content_flags f WHERE f.occurred_at >= p_since
    UNION ALL
    SELECT 'budget_refused', l.id, l.created_at, 'A model call was refused: ' || COALESCE(l.error_message, l.error_code)
      FROM prompt_ledger l WHERE l.created_at >= p_since AND l.status = 'refused'
    UNION ALL
    SELECT 'login_failed', a.id, a.occurred_at, 'A sign-in failed.'
      FROM activity_log a WHERE a.occurred_at >= p_since AND a.action = 'auth.login_failed'
    UNION ALL
    SELECT 'approval_' || q.status, q.id, q.updated_at, 'Approval ' || q.action_key || ' ended ' || q.status || COALESCE(': ' || left(q.execution_error, 200), '')
      FROM approval_requests q WHERE q.updated_at >= p_since AND q.status IN ('rejected', 'execution_failed')
    UNION ALL
    SELECT 'unledgered_call', r.id, r.finished_at, 'A run was voided: a model call could not be ledgered.'
      FROM agent_runs r WHERE r.finished_at >= p_since AND r.error LIKE '%could not be written to the prompt ledger%';
$$;

-- The last backup of each kind and whether it succeeded.
CREATE FUNCTION system_backup_status() RETURNS TABLE (kind text, last_ok timestamptz, last_status text, last_error text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT b.kind,
           max(b.finished_at) FILTER (WHERE b.status IN ('succeeded', 'ok', 'completed')),
           (array_agg(b.status ORDER BY b.started_at DESC))[1],
           (array_agg(b.error ORDER BY b.started_at DESC))[1]
      FROM backup_runs b GROUP BY b.kind;
$$;

-- Applications and their health endpoints and versions (for the Sysadmin's probes).
CREATE FUNCTION system_application_probes() RETURNS TABLE (application_id bigint, app_key text, name text, version text,
    status text, health_url text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT a.id, a.app_key, a.name, a.version, a.status,
           (SELECT e.url FROM application_endpoints e WHERE e.application_id = a.id AND e.status = 'active'
               AND e.kind = 'http_api' AND e.url ILIKE '%/health%' ORDER BY e.id LIMIT 1)
      FROM applications a WHERE NOT a.is_builtin AND a.status IN ('active', 'degraded');
$$;

-- An alert or finding raised by the Auditor on an eval set (eval_alerts is the table the design always had).
CREATE FUNCTION audit_open_alert(p_set bigint, p_agent bigint, p_eval_run bigint, p_schedule bigint, p_kind text,
    p_severity text, p_score numeric, p_baseline numeric, p_detail text) RETURNS bigint
LANGUAGE sql SECURITY DEFINER SET search_path TO 'public' AS $$
    INSERT INTO eval_alerts (eval_set_id, agent_member_id, eval_run_id, schedule_id, kind, severity, score, baseline_score, detail)
    VALUES (p_set, p_agent, p_eval_run, p_schedule, p_kind, p_severity, p_score, p_baseline, p_detail) RETURNING id;
$$;

-- A trace grade written by the Auditor.
CREATE FUNCTION audit_record_trace_grade(p_run bigint, p_set bigint, p_score numeric, p_passed boolean, p_notes text,
    p_model bigint, p_detail jsonb, p_awaiting boolean, p_agent bigint) RETURNS bigint
LANGUAGE sql SECURITY DEFINER SET search_path TO 'public' AS $$
    INSERT INTO trace_grades (agent_run_id, eval_set_id, score, passed, grader_notes, grader_model_id, sampled_at, graded_at,
                              grader_detail, awaiting_person, graded_by_agent)
    VALUES (p_run, p_set, p_score, p_passed, p_notes, p_model, now(), now(), p_detail, p_awaiting, p_agent) RETURNING id;
$$;

GRANT EXECUTE ON FUNCTION audit_due_schedules(), audit_schedule_worked(bigint, bigint), audit_eval_run_outcome(bigint),
    audit_sample_runs(bigint, timestamptz, integer), audit_evidence_gaps(timestamptz), system_guardrail_events(timestamptz),
    system_backup_status(), system_application_probes(),
    audit_open_alert(bigint, bigint, bigint, bigint, text, text, numeric, numeric, text),
    audit_record_trace_grade(bigint, bigint, numeric, boolean, text, bigint, jsonb, boolean, bigint) TO app_runner;

-- The departments an agent works in — the Auditor's independence rule (it never audits its own department).
CREATE FUNCTION audit_agent_departments(p_agent bigint) RETURNS bigint[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT COALESCE(array_agg(department_id), '{}') FROM department_members WHERE member_id = p_agent AND left_at IS NULL;
$$;
GRANT EXECUTE ON FUNCTION audit_agent_departments(bigint) TO app_runner;

-- 6. Who may read (views) -------------------------------------------------------------------------------------
-- The Sysadmin's events and probes: the super-admin, or an admin of the department of the agent that recorded them
-- (IT). The decision trail: the super-admin, or an admin of the deciding agent's department.
CREATE FUNCTION app_can_see_system_one(p_agent bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT app_is_super_admin()
        OR EXISTS (SELECT 1 FROM department_members dm
                    WHERE dm.member_id = p_agent AND dm.left_at IS NULL AND app_is_admin_of(dm.department_id));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_system_one(bigint) TO app_rw, app_records_ro;

CREATE VIEW mcp_system_events WITH (security_barrier = true) AS
 SELECT e.id AS system_event_id, e.fingerprint, e.source, e.sample, e.first_seen, e.last_seen, e.occurrences,
        e.category, e.severity, e.classification, e.agent_member_id, m.display_name AS agent_name,
        e.status, e.status_by, sb.display_name AS status_by_name, e.status_at, e.note
   FROM system_events e
   LEFT JOIN members m ON m.id = e.agent_member_id
   LEFT JOIN members sb ON sb.id = e.status_by
  WHERE app_member_kind() = 'human' AND (app_is_super_admin() OR app_can_see_system_one(e.agent_member_id));

CREATE VIEW mcp_system_probes WITH (security_barrier = true) AS
 SELECT p.probe, p.status, p.detail, p.measured, p.agent_member_id, p.checked_at, p.changed_at
   FROM system_probes p
  WHERE app_member_kind() = 'human' AND (app_is_super_admin() OR app_can_see_system_one(p.agent_member_id));

CREATE VIEW mcp_system_one_decisions WITH (security_barrier = true) AS
 SELECT d.id AS decision_id, d.agent_run_id, d.agent_member_id, m.display_name AS agent_name, d.playbook,
        d.subject_kind, d.subject_id, d.subject_label, d.answers, d.decision, d.mode, d.acted, d.note, d.created_at
   FROM system_one_decisions d JOIN members m ON m.id = d.agent_member_id
  WHERE app_member_kind() = 'human' AND app_can_see_system_one(d.agent_member_id);

GRANT SELECT ON mcp_system_events, mcp_system_probes, mcp_system_one_decisions TO app_rw, app_records_ro;

-- The trace grades view gains how they were graded (appended).
COMMIT;
