-- 045_prompt_ledger.sql
-- Agent runs + the prompt ledger: every model call from every harness, with token counts,
-- latency and cost, linked to activity_log by request_id. Full context/response payloads
-- live in a separate table so retention can archive them while metadata keeps forever.
-- AI spend rolls up into project/task/campaign cost (decided 2026-09-17).
-- Questions: PL1–PL9, H4, H5, H9, P8, P13, E7, SM11, DB7.
-- Provider credentials are in tenant_secrets and never appear here.

BEGIN;

-- One unit of agent work: a duty run, a queued task, a chat turn, an eval case.
CREATE TABLE agent_runs (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id     bigint REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,  -- null = assistant acting for a member
    acting_member_id    bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,      -- whose rights it used
    location_id         bigint REFERENCES locations(id) ON DELETE SET NULL,
    trigger             text NOT NULL CHECK (trigger IN ('duty', 'location_task', 'assistant', 'chat',
                                                         'eval', 'manual')),
    duty_id             bigint REFERENCES agent_duties(id) ON DELETE SET NULL,
    location_task_id    bigint REFERENCES location_tasks(id) ON DELETE SET NULL,
    config_version_id   bigint REFERENCES agent_config_versions(id) ON DELETE RESTRICT,
    model_id            bigint REFERENCES model_registry(id) ON DELETE RESTRICT,
    harness             text NOT NULL,
    sdk_version         text,
    request_id          text NOT NULL,                              -- = activity_log.request_id
    project_id          bigint REFERENCES projects(id) ON DELETE SET NULL,
    task_id             bigint REFERENCES tasks(id) ON DELETE SET NULL,
    campaign_id         bigint REFERENCES campaigns(id) ON DELETE SET NULL,
    status              text NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'awaiting_approval', 'succeeded', 'failed', 'cancelled')),
    error               text,
    input_tokens        bigint NOT NULL DEFAULT 0,
    output_tokens       bigint NOT NULL DEFAULT 0,
    cache_read_tokens   bigint NOT NULL DEFAULT 0,
    cache_write_tokens  bigint NOT NULL DEFAULT 0,
    cost                numeric(14,6) NOT NULL DEFAULT 0,
    currency            char(3) NOT NULL DEFAULT 'USD',
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_runs_agent_time_idx ON agent_runs (agent_member_id, started_at DESC);
CREATE INDEX agent_runs_request_idx    ON agent_runs (request_id);
CREATE INDEX agent_runs_project_idx    ON agent_runs (project_id) WHERE project_id IS NOT NULL;
CREATE INDEX agent_runs_task_idx       ON agent_runs (task_id) WHERE task_id IS NOT NULL;
CREATE INDEX agent_runs_campaign_idx   ON agent_runs (campaign_id) WHERE campaign_id IS NOT NULL;

-- One row per model call. Never updated except payload_archived_at.
CREATE TABLE prompt_ledger (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at           timestamptz NOT NULL DEFAULT now(),
    agent_run_id          bigint REFERENCES agent_runs(id) ON DELETE RESTRICT,
    agent_member_id       bigint REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,
    acting_member_id      bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    location_id           bigint REFERENCES locations(id) ON DELETE SET NULL,   -- PL9
    harness               text NOT NULL,
    sdk_version           text,
    provider              text NOT NULL,
    model_id              bigint REFERENCES model_registry(id) ON DELETE RESTRICT,
    provider_model_id     text NOT NULL,
    request_id            text NOT NULL,                                 -- joins activity_log (PL2)
    provider_request_id   text,
    call_kind             text NOT NULL DEFAULT 'messages'
                              CHECK (call_kind IN ('messages', 'embedding', 'grader', 'other')),
    status                text NOT NULL CHECK (status IN ('ok', 'error', 'timeout', 'rate_limited',
                                                           'refused', 'cancelled')),    -- PL3
    error_code            text,
    error_message         text,
    input_tokens          integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens         integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens     integer NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),    -- PL5
    cache_write_tokens    integer NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    latency_ms            integer CHECK (latency_ms >= 0),                               -- PL4
    cost                  numeric(14,6) NOT NULL DEFAULT 0 CHECK (cost >= 0),            -- PL1
    currency              char(3) NOT NULL DEFAULT 'USD',
    project_id            bigint REFERENCES projects(id) ON DELETE SET NULL,
    task_id               bigint REFERENCES tasks(id) ON DELETE SET NULL,
    campaign_id           bigint REFERENCES campaigns(id) ON DELETE SET NULL,
    payload_archived_at   timestamptz,                                                   -- PL8
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX prompt_ledger_time_idx      ON prompt_ledger (occurred_at DESC);
CREATE INDEX prompt_ledger_agent_idx     ON prompt_ledger (agent_member_id, occurred_at DESC);
CREATE INDEX prompt_ledger_run_idx       ON prompt_ledger (agent_run_id);
CREATE INDEX prompt_ledger_request_idx   ON prompt_ledger (request_id);
CREATE INDEX prompt_ledger_model_idx     ON prompt_ledger (model_id, occurred_at DESC);
CREATE INDEX prompt_ledger_problem_idx   ON prompt_ledger (occurred_at DESC) WHERE status <> 'ok';
CREATE INDEX prompt_ledger_unarchived_idx ON prompt_ledger (occurred_at) WHERE payload_archived_at IS NULL;

-- Full payloads (subject to retention). Separate so archiving never touches metadata.
CREATE TABLE prompt_payloads (
    ledger_id         bigint PRIMARY KEY REFERENCES prompt_ledger(id) ON DELETE RESTRICT,
    context           jsonb,                              -- system prompt, messages, tool definitions
    response          jsonb,                              -- text + tool calls
    byte_size         integer CHECK (byte_size >= 0),
    sha256            text NOT NULL,
    archive_location  text,                               -- set when context/response are moved out
    created_at        timestamptz NOT NULL DEFAULT now(),
    archived_at       timestamptz
);

ALTER TABLE location_tasks
    ADD CONSTRAINT location_tasks_agent_run_fk
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL;
ALTER TABLE approval_requests
    ADD CONSTRAINT approval_requests_agent_run_fk
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL;

-- Foreign-key lookup indexes
CREATE INDEX agent_runs_location_task_idx ON agent_runs (location_task_id);
CREATE INDEX agent_runs_duty_idx ON agent_runs (duty_id);
CREATE INDEX prompt_ledger_project_idx ON prompt_ledger (project_id) WHERE project_id IS NOT NULL;
CREATE INDEX prompt_ledger_task_idx ON prompt_ledger (task_id) WHERE task_id IS NOT NULL;
CREATE INDEX prompt_ledger_campaign_idx ON prompt_ledger (campaign_id) WHERE campaign_id IS NOT NULL;

COMMIT;
