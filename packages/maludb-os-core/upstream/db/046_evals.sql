-- 046_evals.sql
-- Evaluations: eval sets per agent or role, cases (authored or promoted from real ledger
-- traces), runs (hiring / change control / continuous / manual) and per-case results,
-- plus continuous grading of sampled production traces.
-- Questions: EV1–EV8, H4.

BEGIN;

CREATE TABLE eval_sets (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text NOT NULL UNIQUE,
    description      text,
    agent_member_id  bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL,  -- per agent, or
    role_key         text,                                                            -- per role ('bookkeeper')
    department_id    bigint REFERENCES departments(id) ON DELETE SET NULL,
    pass_threshold   numeric(5,2) NOT NULL DEFAULT 80 CHECK (pass_threshold BETWEEN 0 AND 100),
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'retired')),
    created_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (agent_member_id IS NOT NULL OR role_key IS NOT NULL)
);

CREATE TABLE eval_cases (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_set_id        bigint NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    title              text NOT NULL,
    input              jsonb NOT NULL,                     -- task + fixture refs
    expected           jsonb,                              -- expected outcome / tool calls
    rubric             text,                               -- graded rubric for LLM/human graders
    grader             text NOT NULL DEFAULT 'rubric_llm'
                           CHECK (grader IN ('exact', 'programmatic', 'rubric_llm', 'human')),
    weight             numeric(6,2) NOT NULL DEFAULT 1 CHECK (weight > 0),
    origin             text NOT NULL DEFAULT 'authored' CHECK (origin IN ('authored', 'promoted_trace')),
    source_ledger_id   bigint REFERENCES prompt_ledger(id) ON DELETE RESTRICT,     -- EV5
    source_run_id      bigint REFERENCES agent_runs(id) ON DELETE RESTRICT,
    promoted_by        bigint REFERENCES members(id) ON DELETE SET NULL,
    active             boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (origin = 'authored' OR source_ledger_id IS NOT NULL OR source_run_id IS NOT NULL)
);
CREATE INDEX eval_cases_set_idx ON eval_cases (eval_set_id) WHERE active;

CREATE TABLE eval_runs (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_set_id        bigint NOT NULL REFERENCES eval_sets(id) ON DELETE RESTRICT,
    agent_member_id    bigint REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,
    config_version_id  bigint REFERENCES agent_config_versions(id) ON DELETE RESTRICT,   -- candidate under test
    model_id           bigint NOT NULL REFERENCES model_registry(id) ON DELETE RESTRICT,
    harness            text NOT NULL,
    trigger            text NOT NULL CHECK (trigger IN ('hiring', 'change_control', 'continuous', 'manual')),
    status             text NOT NULL DEFAULT 'queued'
                           CHECK (status IN ('queued', 'running', 'passed', 'failed', 'error', 'cancelled')),
    pass_threshold     numeric(5,2) NOT NULL,
    score              numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    cases_total        integer NOT NULL DEFAULT 0,
    cases_passed       integer NOT NULL DEFAULT 0,
    baseline_run_id    bigint REFERENCES eval_runs(id) ON DELETE SET NULL,   -- EV4 regression compare
    cost               numeric(14,6) NOT NULL DEFAULT 0,
    currency           char(3) NOT NULL DEFAULT 'USD',
    started_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    started_at         timestamptz,
    finished_at        timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_runs_agent_idx  ON eval_runs (agent_member_id, created_at DESC);   -- EV2
CREATE INDEX eval_runs_config_idx ON eval_runs (config_version_id);

CREATE TABLE eval_results (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_run_id       bigint NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    eval_case_id      bigint NOT NULL REFERENCES eval_cases(id) ON DELETE RESTRICT,
    agent_run_id      bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    passed            boolean NOT NULL,
    score             numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    grader_notes      text,
    grader_model_id   bigint REFERENCES model_registry(id) ON DELETE SET NULL,
    graded_by         bigint REFERENCES members(id) ON DELETE SET NULL,      -- human grader
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (eval_run_id, eval_case_id)
);
CREATE INDEX eval_results_case_idx ON eval_results (eval_case_id, passed);    -- EV3

-- Continuous grading of sampled production work (EV6).
CREATE TABLE trace_grades (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_run_id      bigint NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
    eval_set_id       bigint REFERENCES eval_sets(id) ON DELETE SET NULL,
    score             numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    passed            boolean,
    grader_notes      text,
    grader_model_id   bigint REFERENCES model_registry(id) ON DELETE SET NULL,
    promoted_case_id  bigint REFERENCES eval_cases(id) ON DELETE SET NULL,
    sampled_at        timestamptz NOT NULL DEFAULT now(),
    graded_at         timestamptz
);
CREATE INDEX trace_grades_time_idx ON trace_grades (graded_at DESC);
CREATE INDEX trace_grades_run_idx  ON trace_grades (agent_run_id);

ALTER TABLE agent_config_versions
    ADD CONSTRAINT agent_config_versions_gating_eval_fk
    FOREIGN KEY (gating_eval_run_id) REFERENCES eval_runs(id) ON DELETE RESTRICT;

-- Foreign-key lookup indexes
CREATE INDEX eval_runs_set_idx ON eval_runs (eval_set_id, created_at DESC);
CREATE INDEX eval_cases_source_ledger_idx ON eval_cases (source_ledger_id);
CREATE INDEX eval_results_agent_run_idx ON eval_results (agent_run_id);

COMMIT;
