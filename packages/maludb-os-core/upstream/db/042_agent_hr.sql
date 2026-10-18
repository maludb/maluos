-- 042_agent_hr.sql
-- Departments & agent HR. An agent is a members row (member_kind 'agent', business_role
-- 'staff') plus an employment profile. Every change to what an agent is — job description,
-- model, tool grants, schedule, budget — is a new immutable config version; activation of a
-- version is gated by an eval run (FK added in 046).
-- Questions: H1–H13, DB7, AP2, EV8 inputs.
-- home_location_id / location_id FKs are added in 043.

BEGIN;

-- --------------------------------------------------------------------------
-- Model registry — model -> harness (harness-per-model decision). Adding a model is a row.
-- Prices are per million tokens in `currency`, used to cost prompt-ledger rows (045).
-- --------------------------------------------------------------------------
CREATE TABLE model_registry (
    id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_key                 text NOT NULL UNIQUE,              -- 'claude-opus-5'
    display_name              text NOT NULL,
    provider                  text NOT NULL CHECK (provider IN ('anthropic', 'openai', 'deepseek', 'zhipu',
                                                                'moonshot', 'qwen', 'local', 'other')),
    provider_model_id         text NOT NULL,                     -- id sent to the provider API
    harness                   text NOT NULL CHECK (harness IN ('claude_agent_sdk', 'openai_agents_sdk',
                                                               'openai_compatible', 'native')),
    endpoint_url              text,                              -- local / compatible endpoints
    api_secret_id             bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    config                    jsonb NOT NULL DEFAULT '{}',
    context_window_tokens     integer CHECK (context_window_tokens > 0),
    price_input_per_mtok      numeric(12,6) NOT NULL DEFAULT 0 CHECK (price_input_per_mtok >= 0),
    price_output_per_mtok     numeric(12,6) NOT NULL DEFAULT 0 CHECK (price_output_per_mtok >= 0),
    price_cache_read_per_mtok numeric(12,6) NOT NULL DEFAULT 0 CHECK (price_cache_read_per_mtok >= 0),
    price_cache_write_per_mtok numeric(12,6) NOT NULL DEFAULT 0 CHECK (price_cache_write_per_mtok >= 0),
    currency                  char(3) NOT NULL DEFAULT 'USD',
    status                    text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated', 'disabled')),
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Agent employment profile (current state; history lives in agent_config_versions)
-- --------------------------------------------------------------------------
CREATE TABLE agent_profiles (
    member_id                  bigint PRIMARY KEY REFERENCES members(id) ON DELETE RESTRICT,
    manager_member_id          bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,  -- human (app-enforced)
    status                     text NOT NULL DEFAULT 'candidate'
                                   CHECK (status IN ('candidate', 'active', 'suspended', 'offboarded')),
    is_office_manager          boolean NOT NULL DEFAULT false,
    model_id                   bigint NOT NULL REFERENCES model_registry(id) ON DELETE RESTRICT,
    current_config_version_id  bigint,                                  -- FK below
    monthly_budget_amount      numeric(14,2) CHECK (monthly_budget_amount >= 0),   -- H5, H9
    budget_currency            char(3) NOT NULL DEFAULT 'USD',
    home_location_id           bigint,                                  -- FK in 043
    hired_at                   timestamptz,
    hired_by                   bigint REFERENCES members(id) ON DELETE SET NULL,
    suspended_at               timestamptz,
    offboarded_at              timestamptz,
    offboarded_by              bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CHECK (manager_member_id <> member_id)
);
CREATE INDEX agent_profiles_manager_idx ON agent_profiles (manager_member_id);
CREATE INDEX agent_profiles_status_idx  ON agent_profiles (status);

-- Immutable snapshot of everything that defines the agent's behaviour (H3, H7, EV4, EV8).
CREATE TABLE agent_config_versions (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id        bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,
    version_no             integer NOT NULL CHECK (version_no > 0),
    job_description        text NOT NULL,                              -- the system prompt
    model_id               bigint NOT NULL REFERENCES model_registry(id) ON DELETE RESTRICT,
    harness_config         jsonb NOT NULL DEFAULT '{}',
    tool_grants            jsonb NOT NULL DEFAULT '[]',                -- snapshot of agent_tool_grants
    schedule               jsonb NOT NULL DEFAULT '[]',                -- snapshot of agent_duties
    monthly_budget_amount  numeric(14,2) CHECK (monthly_budget_amount >= 0),
    change_note            text,
    created_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    gating_eval_run_id     bigint,                                     -- FK in 046
    activated_at           timestamptz,
    activated_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    UNIQUE (agent_member_id, version_no)
);

ALTER TABLE agent_profiles
    ADD CONSTRAINT agent_profiles_current_config_fk
    FOREIGN KEY (current_config_version_id) REFERENCES agent_config_versions(id) ON DELETE RESTRICT;

-- Current tool/action grants, enforced by the MCP servers and the agent runner.
CREATE TABLE agent_tool_grants (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id  bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    server           text NOT NULL CHECK (server IN ('records', 'activity', 'actions', 'desk')),
    tool_name        text NOT NULL,                                    -- MCP tool or manifest action key
    constraints      jsonb NOT NULL DEFAULT '{}',                      -- e.g. {"max_amount": 500}
    granted_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at       timestamptz
);
CREATE UNIQUE INDEX agent_tool_grants_live_idx ON agent_tool_grants (agent_member_id, server, tool_name)
    WHERE revoked_at IS NULL;

-- Recurring duties — the agent's working schedule (H9).
CREATE TABLE agent_duties (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id  bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    name             text NOT NULL,
    instructions     text NOT NULL,
    schedule_cron    text NOT NULL,                                    -- 5-field cron
    timezone         text NOT NULL DEFAULT 'UTC',
    location_id      bigint,                                           -- FK in 043; null = home location
    active           boolean NOT NULL DEFAULT true,
    last_run_at      timestamptz,
    next_run_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_duties_due_idx ON agent_duties (next_run_at) WHERE active;

-- HR lifecycle events for humans and agents (H12, H13).
CREATE TABLE hr_events (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id          bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    event_type         text NOT NULL CHECK (event_type IN ('hire', 'onboard', 'adjust', 'review', 'suspend',
                                                          'reinstate', 'offboard', 'department_change',
                                                          'manager_change')),
    config_version_id  bigint REFERENCES agent_config_versions(id) ON DELETE RESTRICT,
    note               text,
    actor_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,
    occurred_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX hr_events_member_idx ON hr_events (member_id, occurred_at DESC);

-- Performance reviews (H4). metrics = the activity/ledger/eval figures at review time.
CREATE TABLE performance_reviews (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id           bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    reviewer_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    period_start        date NOT NULL,
    period_end          date NOT NULL,
    rating              smallint CHECK (rating BETWEEN 1 AND 5),
    summary             text,
    metrics             jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);
CREATE INDEX performance_reviews_member_idx ON performance_reviews (member_id, period_end DESC);

-- Escalations an agent raised to a human (H4, H8). Links to the ticket / approval that
-- carried it are added in 044.
CREATE TABLE agent_escalations (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id      bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,
    to_member_id         bigint REFERENCES members(id) ON DELETE SET NULL,
    reason_kind          text NOT NULL CHECK (reason_kind IN ('needs_approval', 'uncertain', 'blocked',
                                                            'policy', 'error', 'budget', 'other')),
    summary              text NOT NULL,
    entity_type          text,
    entity_id            bigint,
    ticket_id            bigint REFERENCES tickets(id) ON DELETE SET NULL,
    approval_request_id  bigint,                                        -- FK in 044
    resolved_at          timestamptz,
    resolved_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_escalations_agent_idx ON agent_escalations (agent_member_id, created_at DESC);

-- Foreign-key lookup indexes
CREATE INDEX agent_duties_agent_idx ON agent_duties (agent_member_id);
CREATE INDEX agent_escalations_to_idx ON agent_escalations (to_member_id);

COMMIT;
