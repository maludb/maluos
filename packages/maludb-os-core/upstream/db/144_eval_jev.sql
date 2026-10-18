-- 144: evals graded by JEV (2026-09-26 — docs/build-specs/eval-jev-grader.md).
--
-- A case may be graded by JEV (TypeSafe's System One model, through OpenRouter): its `checks` are typed
-- questions — noul / choice / score — each with a pass rule; the runner asks them all in one call per
-- trial, through the ledger proxy. An answer JEV is unsure of routes the case to a person
-- (`awaiting_person`), excluded from the score until graded. Every check's answer is kept in
-- `grader_detail`, also when a person grades, so agreement can be measured (mcp_eval_check_calibration).
-- Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/144_eval_jev.sql

BEGIN;
ALTER TABLE eval_cases DROP CONSTRAINT eval_cases_grader_check;
ALTER TABLE eval_cases ADD CONSTRAINT eval_cases_grader_check
    CHECK (grader IN ('exact', 'programmatic', 'rubric_llm', 'jev', 'human'));
ALTER TABLE eval_cases ADD COLUMN checks jsonb;
ALTER TABLE eval_cases ADD CONSTRAINT eval_cases_jev_has_checks
    CHECK (grader <> 'jev' OR (jsonb_typeof(checks) = 'array' AND jsonb_array_length(checks) BETWEEN 1 AND 24));
COMMENT ON COLUMN eval_cases.checks IS 'JEV checks: [{id, type noul|choice|score, instructions, criteria, pass_at|accept|min_level, min_confidence, uncertain, required, weight}].';

ALTER TABLE eval_results ADD COLUMN awaiting_person boolean NOT NULL DEFAULT false;
ALTER TABLE eval_results ADD COLUMN grader_detail jsonb;
COMMENT ON COLUMN eval_results.awaiting_person IS 'JEV was unsure (or not configured): a person grades this result; excluded from the score until then.';
COMMENT ON COLUMN eval_results.grader_detail IS 'JEV: {verdict, trials:[{verdict, checks:{id:{outcome,value,choice,score,confidence,probabilities}}, guard}]}; kept when a person grades.';

-- The result view: a JEV result awaiting a person is not graded until someone grades it. Columns appended.
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
    (((c.grader <> 'human'::text) AND NOT er.awaiting_person) OR (er.graded_by IS NOT NULL)) AS is_graded,
    er.awaiting_person,
    er.grader_detail
   FROM ((eval_results er
     JOIN mcp_eval_runs r ON ((r.eval_run_id = er.eval_run_id)))
     JOIN eval_cases c ON ((c.id = er.eval_case_id)))
  WHERE (app_member_kind() = 'human'::text);

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
  WHERE ((app_member_kind() = 'human'::text) AND app_can_see_evals(s.agent_member_id));

-- Per set and check: how JEV answered across every trial it graded, and — where a person graded the
-- same result — how often the check's confident outcome agreed with the person's verdict.
CREATE VIEW mcp_eval_check_calibration WITH (security_barrier = true) AS
 SELECT c.eval_set_id,
        chk.key AS check_id,
        count(*) AS answers,
        count(*) FILTER (WHERE chk.value->>'outcome' = 'pass') AS passes,
        count(*) FILTER (WHERE chk.value->>'outcome' = 'fail') AS fails,
        count(*) FILTER (WHERE chk.value->>'outcome' = 'uncertain') AS uncertain,
        count(*) FILTER (WHERE er.graded_by IS NOT NULL AND chk.value->>'outcome' <> 'uncertain') AS person_graded,
        count(*) FILTER (WHERE er.graded_by IS NOT NULL AND (
            (chk.value->>'outcome' = 'pass' AND er.passed) OR (chk.value->>'outcome' = 'fail' AND NOT er.passed))) AS person_agreed,
        round(avg((chk.value->>'confidence')::numeric), 3) AS mean_confidence
   FROM eval_results er
   JOIN eval_cases c ON c.id = er.eval_case_id AND c.grader = 'jev'
   JOIN eval_sets s ON s.id = c.eval_set_id
   CROSS JOIN LATERAL jsonb_array_elements(COALESCE(er.grader_detail->'trials', '[]'::jsonb)) t(trial)
   CROSS JOIN LATERAL jsonb_each(COALESCE(t.trial->'checks', '{}'::jsonb)) chk
  WHERE app_member_kind() = 'human' AND app_can_see_evals(s.agent_member_id)
  GROUP BY c.eval_set_id, chk.key;
GRANT SELECT ON mcp_eval_check_calibration TO app_rw, app_records_ro;

-- JEV in the model registry: not an agent harness — a grader reached through the ledger proxy.
ALTER TABLE model_registry DROP CONSTRAINT model_registry_provider_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_provider_check
    CHECK (provider IN ('anthropic', 'openai', 'deepseek', 'zhipu', 'moonshot', 'qwen', 'fireworks', 'openrouter', 'local', 'other'));
INSERT INTO model_registry (model_key, display_name, provider, provider_model_id, harness, endpoint_url,
                            context_window_tokens, price_input_per_mtok, price_output_per_mtok, config)
VALUES ('jev:typesafe/jev-1.13', 'JEV 1.13 (TypeSafe, via OpenRouter)', 'openrouter', 'typesafe/jev-1.13', 'native',
        'https://openrouter.ai/api/v1/systemone', 32000, 0.042, 0,
        '{"kind": "decisions", "role": "eval_grader", "key_env": "OPENROUTER_API_KEY"}')
ON CONFLICT (model_key) DO NOTHING;
COMMIT;
