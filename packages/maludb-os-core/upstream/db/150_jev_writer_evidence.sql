-- 150: the JEV prompt writer reads the judgement evidence (owner, 2026-09-27;
-- docs/build-specs/jev-prompt-writer.md).
--
-- The system_one decision trail, system events and probes, and the eval sets, cases, runs, results,
-- schedules, alerts, calibration and trace grades were visible to people only. The JEV prompt writer
-- (an active agent whose role is jev_prompt_writer — agent 53) drafts the questions those judgements
-- are made with, and cannot diagnose a wrong answer it cannot see: the owner opened them to it, read
-- only. Each view keeps its rule for everyone else and gains "OR app_reads_judgement_evidence()". The
-- prompt ledger (every model call's full context) stays closed. Additive; the views' columns are
-- unchanged, so their grants stand.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/150_jev_writer_evidence.sql

BEGIN;

CREATE FUNCTION app_reads_judgement_evidence() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT EXISTS (SELECT 1 FROM agent_profiles p JOIN members m ON m.id = p.member_id
                    WHERE p.member_id = app_current_member_id() AND m.member_kind = 'agent'
                      AND m.status = 'active' AND p.status = 'active' AND p.role_key = 'jev_prompt_writer');
$$;
COMMENT ON FUNCTION app_reads_judgement_evidence() IS 'The JEV prompt writer (role jev_prompt_writer): may read the system_one decisions, system events and probes, and the eval judgement views (db/150). Read only; the prompt ledger stays closed.';
GRANT EXECUTE ON FUNCTION app_reads_judgement_evidence() TO app_rw, app_records_ro, app_runner;

CREATE OR REPLACE VIEW mcp_system_one_decisions WITH (security_barrier = true) AS
 SELECT d.id AS decision_id,
    d.agent_run_id,
    d.agent_member_id,
    m.display_name AS agent_name,
    d.playbook,
    d.subject_kind,
    d.subject_id,
    d.subject_label,
    d.answers,
    d.decision,
    d.mode,
    d.acted,
    d.note,
    d.created_at
   FROM (system_one_decisions d
     JOIN members m ON ((m.id = d.agent_member_id)))
  WHERE ((((app_member_kind() = 'human'::text) AND app_can_see_system_one(d.agent_member_id))) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_system_events WITH (security_barrier = true) AS
 SELECT e.id AS system_event_id,
    e.fingerprint,
    e.source,
    e.sample,
    e.first_seen,
    e.last_seen,
    e.occurrences,
    e.category,
    e.severity,
    e.classification,
    e.agent_member_id,
    m.display_name AS agent_name,
    e.status,
    e.status_by,
    sb.display_name AS status_by_name,
    e.status_at,
    e.note
   FROM ((system_events e
     LEFT JOIN members m ON ((m.id = e.agent_member_id)))
     LEFT JOIN members sb ON ((sb.id = e.status_by)))
  WHERE ((((app_member_kind() = 'human'::text) AND (app_is_super_admin() OR app_can_see_system_one(e.agent_member_id)))) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_system_probes WITH (security_barrier = true) AS
 SELECT probe,
    status,
    detail,
    measured,
    agent_member_id,
    checked_at,
    changed_at
   FROM system_probes p
  WHERE ((((app_member_kind() = 'human'::text) AND (app_is_super_admin() OR app_can_see_system_one(agent_member_id)))) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_sets WITH (security_barrier = true) AS
 SELECT id AS eval_set_id,
    name,
    description,
    agent_member_id,
    role_key,
    department_id,
    pass_threshold,
    status,
    created_at,
    updated_at,
    trace_checks
   FROM eval_sets
  WHERE ((app_can_see_evals(agent_member_id)) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_cases WITH (security_barrier = true) AS
 SELECT c.id AS eval_case_id,
    c.eval_set_id,
    c.title,
    c.input,
    c.expected,
    c.rubric,
    c.grader,
    c.weight,
    c.origin,
    c.source_ledger_id,
    c.source_run_id,
    c.promoted_by,
    c.active,
    c.created_at,
    c.checks
   FROM (eval_cases c
     JOIN eval_sets s ON ((s.id = c.eval_set_id)))
  WHERE ((((app_member_kind() = 'human'::text) AND app_can_see_evals(s.agent_member_id))) OR app_reads_judgement_evidence());

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
    c.grader,
    er.graded_by,
    (((c.grader <> 'human'::text) AND (NOT er.awaiting_person)) OR (er.graded_by IS NOT NULL)) AS is_graded,
    er.awaiting_person,
    er.grader_detail
   FROM ((eval_results er
     JOIN mcp_eval_runs r ON ((r.eval_run_id = er.eval_run_id)))
     JOIN eval_cases c ON ((c.id = er.eval_case_id)))
  WHERE (((app_member_kind() = 'human'::text)) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_runs WITH (security_barrier = true) AS
 SELECT r.id AS eval_run_id,
    r.eval_set_id,
    s.name AS eval_set_name,
    r.agent_member_id,
    r.config_version_id,
    r.model_id,
    r.harness,
    r.trigger,
    r.status,
    r.pass_threshold,
    r.score,
    r.cases_total,
    r.cases_passed,
    r.baseline_run_id,
    r.cost,
    r.currency,
    r.started_by,
    r.started_at,
    r.finished_at,
    r.created_at
   FROM (eval_runs r
     JOIN eval_sets s ON ((s.id = r.eval_set_id)))
  WHERE ((app_can_see_evals(COALESCE(r.agent_member_id, s.agent_member_id))) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_check_calibration WITH (security_barrier = true) AS
 SELECT c.eval_set_id,
    chk.key AS check_id,
    count(*) AS answers,
    count(*) FILTER (WHERE ((chk.value ->> 'outcome'::text) = 'pass'::text)) AS passes,
    count(*) FILTER (WHERE ((chk.value ->> 'outcome'::text) = 'fail'::text)) AS fails,
    count(*) FILTER (WHERE ((chk.value ->> 'outcome'::text) = 'uncertain'::text)) AS uncertain,
    count(*) FILTER (WHERE ((er.graded_by IS NOT NULL) AND ((chk.value ->> 'outcome'::text) <> 'uncertain'::text))) AS person_graded,
    count(*) FILTER (WHERE ((er.graded_by IS NOT NULL) AND ((((chk.value ->> 'outcome'::text) = 'pass'::text) AND er.passed) OR (((chk.value ->> 'outcome'::text) = 'fail'::text) AND (NOT er.passed))))) AS person_agreed,
    round(avg(((chk.value ->> 'confidence'::text))::numeric), 3) AS mean_confidence
   FROM ((((eval_results er
     JOIN eval_cases c ON (((c.id = er.eval_case_id) AND (c.grader = 'jev'::text))))
     JOIN eval_sets s ON ((s.id = c.eval_set_id)))
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE((er.grader_detail -> 'trials'::text), '[]'::jsonb)) t(trial))
     CROSS JOIN LATERAL jsonb_each(COALESCE((t.trial -> 'checks'::text), '{}'::jsonb)) chk(key, value))
  WHERE ((((app_member_kind() = 'human'::text) AND app_can_see_evals(s.agent_member_id))) OR app_reads_judgement_evidence())
  GROUP BY c.eval_set_id, chk.key;

CREATE OR REPLACE VIEW mcp_trace_grades WITH (security_barrier = true) AS
 SELECT g.id AS trace_grade_id,
    g.agent_run_id,
    r.agent_member_id,
    g.eval_set_id,
    g.score,
    g.passed,
    g.grader_notes,
    g.promoted_case_id,
    g.sampled_at,
    g.graded_at
   FROM (trace_grades g
     JOIN agent_runs r ON ((r.id = g.agent_run_id)))
  WHERE ((((app_member_kind() = 'human'::text) AND app_can_see_evals(r.agent_member_id))) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_schedules WITH (security_barrier = true) AS
 SELECT sc.id AS eval_schedule_id,
    sc.eval_set_id,
    s.name AS eval_set_name,
    s.agent_member_id,
    sc.kind,
    sc.cadence,
    sc.sample_size,
    sc.regression_delta,
    sc.active,
    sc.next_run_at,
    sc.last_run_at,
    sc.last_eval_run_id
   FROM (eval_schedules sc
     JOIN eval_sets s ON ((s.id = sc.eval_set_id)))
  WHERE ((app_can_see_evals(s.agent_member_id)) OR app_reads_judgement_evidence());

CREATE OR REPLACE VIEW mcp_eval_alerts WITH (security_barrier = true) AS
 SELECT al.id AS eval_alert_id,
    al.eval_set_id,
    s.name AS eval_set_name,
    al.agent_member_id,
    m.display_name AS agent_name,
    al.eval_run_id,
    al.schedule_id,
    al.kind,
    al.severity,
    al.score,
    al.baseline_score,
    al.detail,
    al.status,
    al.opened_at,
    al.acknowledged_by,
    al.acknowledged_at,
    al.resolved_at,
    al.resolution
   FROM ((eval_alerts al
     JOIN eval_sets s ON ((s.id = al.eval_set_id)))
     LEFT JOIN members m ON ((m.id = al.agent_member_id)))
  WHERE ((app_can_see_evals(al.agent_member_id)) OR app_reads_judgement_evidence());

COMMIT;
