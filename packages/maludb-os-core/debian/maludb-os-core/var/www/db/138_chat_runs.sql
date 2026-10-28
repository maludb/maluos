-- 138: chat runs for an application's command bar (A6, 2026-09-22).
--
-- docs/business-os-integration.md, "Agents — the application's command bar": the bar posts each
-- utterance to the kernel's chat endpoint; the kernel runs ONE turn of the application's shipped
-- agent (its expert) as a run with trigger 'chat', the person as requester, the application on the
-- run and on every ledger row it produces. Two columns carry the conversation: the key the
-- application gives a conversation, and the person's own words (the run's instructions hold the
-- rendered prompt around them), so the next turn can carry the last few in. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/138_chat_runs.sql

BEGIN;

ALTER TABLE agent_runs
    ADD COLUMN conversation_key text,
    ADD COLUMN chat_utterance   text;
CREATE INDEX agent_runs_conversation_idx ON agent_runs (application_id, conversation_key, id DESC) WHERE conversation_key IS NOT NULL;
COMMENT ON COLUMN agent_runs.conversation_key IS 'A chat run (A6): the application''s conversation id, so a later turn can carry the earlier ones.';
COMMENT ON COLUMN agent_runs.chat_utterance IS 'A chat run: what the person said, verbatim (instructions hold the prompt built around it).';

CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id,
       r.location_id, r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id,
       r.harness, r.sdk_version, r.request_id, r.status, r.error,
       r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens, r.cost, r.currency,
       r.started_at, r.finished_at, r.instructions, r.result, r.parent_run_id, r.requested_by,
       r.approval_request_id,
       r.application_id,
       r.conversation_key, r.chat_utterance
  FROM agent_runs r LEFT JOIN members am ON am.id = r.agent_member_id
 WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);

COMMIT;

-- The chat endpoint stamps the application on the ledger rows a run produced; the ledger is otherwise the
-- runner's to write. Applied 2026-09-22 with the rest of this migration.
GRANT UPDATE (application_id) ON prompt_ledger TO app_rw;
