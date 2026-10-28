-- 097_agent_runtime.sql
-- Approved by the owner 2026-09-19 (stage H1 of docs/hermes-integration-plan.md: schema + tool
-- surface + manifest, approved together). Spec: docs/build-specs/agent-runtime-hermes.md.
--
-- The agent runtime's schema. Everything a run needs already exists (042, 044, 045, 075); this
-- adds only what the design review and the H0 conformance suite showed to be missing:
--
--   1. 'hermes' as a harness. A registry row is a (model, harness) pair, so choosing Hermes for an
--      agent is choosing a model row — still "a registry entry, never a code change elsewhere".
--   2. agent_config_versions.runtime_config. harness_config cannot hold harness settings: the
--      db/071 trigger overwrites it from the cited prompt version's parameters. runtime_config is
--      the harness's own immutable settings (native toolsets, terminal backend, run limits,
--      pinned skills). app_rw holds no UPDATE on it (db/049), so a change is a new version and
--      passes change control like any other.
--   3. agent_runs: what was asked, what came back, what it ran with (profile + skill hashes, so
--      an eval can reproduce a run), and who delegated it.
--   4. approval_requests: the handler path and full POST body, because `parameters` is a summary
--      the caller chose and cannot replay the action (H3 builds the replay).
--   5. app_runner: the runner's own database role. It is not app_rw — it can write runs and the
--      ledger and nothing else, and it reads only what rendering a profile needs.

BEGIN;

-- --------------------------------------------------------------------------
-- 1. Hermes joins the harness vocabulary
-- --------------------------------------------------------------------------
ALTER TABLE model_registry DROP CONSTRAINT model_registry_harness_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_harness_check CHECK (
    harness IN ('claude_agent_sdk', 'openai_agents_sdk', 'openai_compatible', 'native', 'hermes'));

COMMENT ON COLUMN model_registry.harness IS
    'The harness that runs this model. One row per (model, harness) pair: the same provider model '
    'may appear twice under different model_keys, e.g. claude-sonnet-5 and hermes:claude-sonnet-5.';

-- --------------------------------------------------------------------------
-- 2. The harness's own immutable settings
-- --------------------------------------------------------------------------
ALTER TABLE agent_config_versions
    ADD COLUMN runtime_config jsonb NOT NULL DEFAULT '{}'
        CHECK (jsonb_typeof(runtime_config) = 'object');

COMMENT ON COLUMN agent_config_versions.runtime_config IS
    'Harness settings for this version, immutable with it. Keys the Hermes harness reads: '
    'native_toolsets (text[]; default none — terminal, file, web, browser, code_execution are '
    'capabilities OUTSIDE the MCP tool grants and must be opted into per version), '
    'terminal_backend (docker only), max_turns, run_timeout_seconds, '
    'pinned_skills ([{name, bundle_hash}] — set for agents that have an eval set, so a skill '
    'change is a gated version). Unknown keys are ignored by the renderer, never passed through.';

-- --------------------------------------------------------------------------
-- 3. A run records what it was asked, what it ran with, and what came back
-- --------------------------------------------------------------------------
ALTER TABLE agent_runs DROP CONSTRAINT agent_runs_trigger_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_trigger_check CHECK (
    trigger IN ('duty', 'location_task', 'assistant', 'chat', 'eval', 'manual', 'delegation'));

ALTER TABLE agent_runs
    ADD COLUMN parent_run_id      bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    ADD COLUMN requested_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    ADD COLUMN instructions       text,
    ADD COLUMN result             text,
    ADD COLUMN profile_hash       text,
    ADD COLUMN skills             jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(skills) = 'array'),
    ADD COLUMN usage_report       jsonb,
    ADD COLUMN approval_request_id bigint REFERENCES approval_requests(id) ON DELETE SET NULL,
    ADD CONSTRAINT agent_runs_delegation_has_parent
        CHECK (trigger <> 'delegation' OR parent_run_id IS NOT NULL);

CREATE INDEX agent_runs_parent_idx  ON agent_runs (parent_run_id) WHERE parent_run_id IS NOT NULL;
CREATE INDEX agent_runs_running_idx ON agent_runs (agent_member_id) WHERE status = 'running';

COMMENT ON COLUMN agent_runs.instructions  IS 'What the run was asked to do: the duty''s instructions, the manual request, or the delegated task.';
COMMENT ON COLUMN agent_runs.result        IS 'The agent''s final answer.';
COMMENT ON COLUMN agent_runs.profile_hash  IS 'sha256 of the rendered harness profile (config + persona) the run used.';
COMMENT ON COLUMN agent_runs.skills        IS 'Snapshot of the skills synced into the run: [{name, maludb_skill_id, bundle_hash}].';
COMMENT ON COLUMN agent_runs.usage_report  IS 'The harness''s own usage report (Hermes --usage-file). The prompt ledger, not this, is the record of cost.';
COMMENT ON COLUMN agent_runs.approval_request_id IS 'The request a run stopped on when status = awaiting_approval.';

-- One run at a time per agent: a Hermes profile must never be shared by two processes.
CREATE UNIQUE INDEX agent_runs_one_running_per_agent
    ON agent_runs (agent_member_id) WHERE status = 'running' AND agent_member_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- 4. An approval can replay the action it paused
-- --------------------------------------------------------------------------
ALTER TABLE approval_requests
    ADD COLUMN handler_path text,
    ADD COLUMN request_body jsonb CHECK (request_body IS NULL OR jsonb_typeof(request_body) = 'object');

COMMENT ON COLUMN approval_requests.handler_path IS 'The PHP handler the paused request was sent to, e.g. /sales/invoices/send.php.';
COMMENT ON COLUMN approval_requests.request_body IS 'The full POST body of the paused request. `parameters` stays the human summary; this is what is replayed, as the requester, on approval.';

-- approval_requests.agent_run_id already references agent_runs (FK approval_requests_agent_run_fk,
-- added by 045). What is missing is the app ever SETTING it: create_approval_request() must, from H3.

-- --------------------------------------------------------------------------
-- 5. app_runner — the runner's own role
-- --------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runner') THEN
        CREATE ROLE app_runner LOGIN;          -- password set out of band, like the other app roles
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO app_runner;

-- Reads: exactly what rendering a profile and scheduling a duty need. No tenant_secrets, no
-- business records — an agent reaches those through MCP under its own member identity.
GRANT SELECT ON members, agent_profiles, agent_config_versions, agent_tool_grants, agent_duties,
                agent_subagents, model_registry, applications, application_endpoints,
                application_access, departments, department_members, locations, location_residents,
                approval_requests
    TO app_runner;

-- Writes: runs, the ledger, and a duty's clock.
GRANT SELECT, INSERT ON agent_runs, prompt_ledger, prompt_payloads TO app_runner;
GRANT UPDATE (status, error, result, usage_report, profile_hash, skills, approval_request_id,
              input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost,
              finished_at, sdk_version) ON agent_runs TO app_runner;
GRANT UPDATE (last_run_at, next_run_at) ON agent_duties TO app_runner;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'members', 'agent_profiles', 'agent_config_versions', 'agent_tool_grants', 'agent_duties',
        'agent_subagents', 'model_registry', 'applications', 'application_endpoints',
        'application_access', 'departments', 'department_members', 'locations',
        'location_residents', 'approval_requests', 'agent_runs', 'prompt_ledger', 'prompt_payloads'
    ] LOOP
        IF (SELECT relrowsecurity FROM pg_class WHERE oid = t::regclass) THEN
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_runner', t);
            EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_runner USING (true) WITH CHECK (true)',
                           t || '_runner', t);
        END IF;
    END LOOP;
END $$;
-- The policy is permissive because the GRANTs above are the boundary: a policy cannot give a
-- role a privilege it was never granted.

COMMIT;
