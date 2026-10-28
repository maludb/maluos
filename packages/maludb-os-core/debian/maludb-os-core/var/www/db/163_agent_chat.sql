-- 163: Agent Chat — a person talks to one agent from its page (2026-09-29).
--
-- docs/build-specs/agent-chat.md. A turn is an ordinary agent run with trigger 'chat' (the person's
-- words are agent_runs.chat_utterance and the agent's are result, both from db/138); what is new is
-- the conversation that groups the turns and belongs to ONE person. Owner decision: conversations
-- are private to their person; the runs stay visible wherever runs are visible today. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/163_agent_chat.sql

BEGIN;

CREATE TABLE agent_conversations (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id  bigint NOT NULL REFERENCES members(id),
    member_id        bigint NOT NULL REFERENCES members(id),
    title            text NOT NULL DEFAULT '' CHECK (char_length(title) <= 120),
    created_at       timestamptz NOT NULL DEFAULT now(),
    archived_at      timestamptz
);
CREATE INDEX agent_conversations_person_idx ON agent_conversations (member_id, agent_member_id, id DESC);
COMMENT ON TABLE agent_conversations IS 'A person''s chat thread with one agent (agent-chat.md). Private to member_id; its turns are agent_runs rows with conversation_id set.';

ALTER TABLE agent_runs ADD COLUMN conversation_id bigint REFERENCES agent_conversations(id);
CREATE INDEX agent_runs_chat_idx ON agent_runs (conversation_id, id) WHERE conversation_id IS NOT NULL;
COMMENT ON COLUMN agent_runs.conversation_id IS 'An OS chat turn: the agent_conversations row it belongs to. (conversation_key is A6''s application-side id; the two never mix.)';

-- Same row-level pattern as agent_messages (db/155): the table is opened to the application role and the
-- privacy rule lives in the handlers and the view, where the caller is known.
ALTER TABLE agent_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY agent_conversations_app_rw ON agent_conversations TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON agent_conversations TO app_rw;

-- mcp_agent_runs gains conversation_id LAST; everything else is db/160's definition, unchanged.
CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id, r.location_id,
       r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id, r.harness, r.sdk_version,
       r.request_id, r.status, r.error, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
       r.cost, r.currency, r.started_at, r.finished_at, r.instructions, r.result, r.parent_run_id, r.requested_by,
       r.approval_request_id, r.application_id, r.conversation_key, r.chat_utterance, r.conversation_id
  FROM agent_runs r
  LEFT JOIN members am ON am.id = r.agent_member_id
 WHERE (SELECT app_is_insider())
   AND ((SELECT app_has_module('ledger'))
        OR r.acting_member_id = (SELECT app_current_member_id())
        OR (r.agent_member_id IS NOT NULL
            AND ((SELECT app_has_module('hr'))
                 OR r.agent_member_id = (SELECT app_current_member_id())
                 OR r.agent_member_id IN (SELECT ap.member_id FROM agent_profiles ap
                                           WHERE ap.manager_member_id = app_current_member_id()))));

-- A conversation is its person's alone — not even a super-admin sees another's list here (the runs stay
-- open to whoever may see runs). The caller-only test is a scalar subquery: once per statement (db/160).
CREATE VIEW mcp_agent_conversations WITH (security_barrier = true) AS
SELECT c.id AS conversation_id, c.agent_member_id, am.display_name AS agent_name, c.title, c.created_at, c.archived_at,
       (SELECT count(*) FROM agent_runs r WHERE r.conversation_id = c.id) AS turns,
       (SELECT max(r.id) FROM agent_runs r WHERE r.conversation_id = c.id) AS last_run_id
  FROM agent_conversations c
  LEFT JOIN members am ON am.id = c.agent_member_id
 WHERE c.member_id = (SELECT app_current_member_id());

GRANT SELECT ON mcp_agent_conversations TO app_rw, app_records_ro;

COMMIT;
