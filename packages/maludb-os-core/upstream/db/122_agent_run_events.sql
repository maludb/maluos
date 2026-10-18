-- 122: what happened INSIDE an agent run is kept — tool calls, their outcome and how long they took.
--
-- The prompt ledger keeps every model call whole (context, response, tokens, latency, cost), and a
-- tool's arguments and result are in the next call's context. What was NOT kept anywhere: which tool
-- ran, whether it failed, and how long it took. The harness's observer plugin reported those to the
-- runner, which held them in memory (the last 500 per run) and lost them at every restart. Evaluating
-- an agent later — tool selection, error recovery, where the time went — needs them, and they cannot
-- be backfilled (owner, 2026-09-20: every agent must be creating the data evaluations will need).
--
-- One row per observed event, in the order the runner received it. No arguments and no results here:
-- those are already in prompt_payloads, and this table stays small enough to keep for good.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/122_agent_run_events.sql

BEGIN;

CREATE TABLE agent_run_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_run_id    bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    seq             integer NOT NULL CHECK (seq > 0),           -- order of arrival within the run
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    event           text NOT NULL,                              -- pre_tool_call, post_tool_call, post_api_request, warning, skill …
    tool_name       text,
    tool_call_id    text,
    status          text,
    duration_ms     integer CHECK (duration_ms IS NULL OR duration_ms >= 0),
    error_type      text,
    error_message   text,
    api_request_id  text,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb,         -- whatever else the harness reported, small
    UNIQUE (agent_run_id, seq)
);
CREATE INDEX agent_run_events_tool_idx ON agent_run_events (tool_name, occurred_at) WHERE tool_name IS NOT NULL;

COMMENT ON TABLE agent_run_events IS
    'Telemetry from inside an agent run (tool calls, outcomes, durations), written by the agent runner as the harness reports it. Arguments and results live in prompt_payloads.';

GRANT SELECT, INSERT ON agent_run_events TO app_runner;
GRANT SELECT ON agent_run_events TO app_rw;

-- Who may read a run's events = who may read the run.
CREATE VIEW mcp_agent_run_events AS
SELECT e.id AS agent_run_event_id, e.agent_run_id, r.agent_member_id, e.seq, e.occurred_at, e.event,
       e.tool_name, e.tool_call_id, e.status, e.duration_ms, e.error_type, e.error_message, e.api_request_id
  FROM agent_run_events e
  JOIN agent_runs r ON r.id = e.agent_run_id
 WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);

GRANT SELECT ON mcp_agent_run_events TO app_rw, app_records_ro;

COMMIT;
