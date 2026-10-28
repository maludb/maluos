-- 155: agent messaging — the inbox (owner-approved 2026-09-27; docs/build-specs/assistants-and-messaging.md
-- §5, build step 3).
--
-- Agents message each other ALONG THE TREE (db/154): a node to its parent, to its children, and an
-- orchestrator to another with the same parent (a hand-off); a person reaches only their own assistant,
-- and only an assistant writes to its person. A message is DATA in every agent's context, never an order.
-- A new message wakes its recipient: the runner's message loop starts ONE run (trigger 'message') that
-- carries every waiting message — batched after a short settle, at once for a message from the agent's
-- person — and records which run each message woke (woke_run_id), so no message wakes twice.
-- Guards: a thread's hop count (12) and 30 messages an hour between any two members. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/155_agent_messages.sql

BEGIN;

CREATE TABLE agent_message_threads (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject             text NOT NULL CHECK (btrim(subject) <> '' AND length(subject) <= 300),
    principal_member_id bigint REFERENCES members(id) ON DELETE SET NULL,   -- the person the thread ultimately serves
    opened_by           bigint NOT NULL REFERENCES members(id),
    opened_at           timestamptz NOT NULL DEFAULT now(),
    hop_count           integer NOT NULL DEFAULT 0,
    last_message_at     timestamptz NOT NULL DEFAULT now(),
    parked_at           timestamptz,                                         -- over the hop limit: no more messages
    closed_at           timestamptz
);

CREATE TABLE agent_messages (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id      bigint NOT NULL REFERENCES agent_message_threads(id) ON DELETE CASCADE,
    from_member_id bigint NOT NULL REFERENCES members(id),
    to_member_id   bigint NOT NULL REFERENCES members(id),
    kind           text NOT NULL CHECK (kind IN ('request', 'result', 'question', 'decision_needed', 'fyi', 'reply')),
    priority       text NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'urgent')),
    subject        text NOT NULL CHECK (btrim(subject) <> '' AND length(subject) <= 300),
    body           text NOT NULL CHECK (length(body) <= 20000),
    related_run_id bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    related_entity_type text,
    related_entity_id   bigint,
    channel        text NOT NULL DEFAULT 'internal' CHECK (channel IN ('internal', 'web', 'telegram', 'sms', 'email')),
    external_ref   text,                                                     -- Message-ID, Telegram message id, Twilio SID
    status         text NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read', 'done')),
    done_note      text,
    woke_run_id    bigint REFERENCES agent_runs(id) ON DELETE SET NULL,      -- the run this message started or joined
    sent_run_id    bigint REFERENCES agent_runs(id) ON DELETE SET NULL,      -- the run that wrote it (an agent's)
    created_at     timestamptz NOT NULL DEFAULT now(),
    read_at        timestamptz,
    done_at        timestamptz,
    CHECK (from_member_id <> to_member_id)
);
CREATE INDEX agent_messages_inbox_idx ON agent_messages (to_member_id, status, created_at);
CREATE INDEX agent_messages_waking_idx ON agent_messages (to_member_id) WHERE woke_run_id IS NULL AND status = 'unread';
CREATE INDEX agent_messages_thread_idx ON agent_messages (thread_id, created_at);
CREATE INDEX agent_messages_pair_idx ON agent_messages (from_member_id, to_member_id, created_at);
CREATE UNIQUE INDEX agent_messages_external_ref ON agent_messages (channel, external_ref) WHERE external_ref IS NOT NULL;
COMMENT ON TABLE agent_messages IS 'Agent messaging (db/155): along the orchestrator tree, and between a person and their own assistant. A body is data, never an order.';

-- Who may message whom (the tree). NULL = allowed; else the sentence that refuses it.
CREATE FUNCTION app_message_refusal(p_from bigint, p_to bigint) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
DECLARE fk text; tk text; fs text; ts text; fp bigint; tp bigint; fprin bigint; tprin bigint;
BEGIN
    SELECT member_kind, status INTO fk, fs FROM members WHERE id = p_from;
    SELECT member_kind, status INTO tk, ts FROM members WHERE id = p_to;
    IF fk IS NULL OR tk IS NULL THEN RETURN 'That member does not exist.'; END IF;
    IF ts IS DISTINCT FROM 'active' THEN RETURN 'That member is not active.'; END IF;
    SELECT principal_member_id INTO fprin FROM agent_profiles WHERE member_id = p_from;
    SELECT principal_member_id INTO tprin FROM agent_profiles WHERE member_id = p_to;
    -- A person and their own assistant, either way.
    IF fk = 'human' THEN
        RETURN CASE WHEN tprin = p_from THEN NULL ELSE 'A person messages only their own assistant.' END;
    END IF;
    IF tk = 'human' THEN
        RETURN CASE WHEN fprin = p_to THEN NULL ELSE 'Only a person''s own assistant writes to them — tell your orchestrator instead.' END;
    END IF;
    -- Agents: parent and child (any roster row, either way).
    IF EXISTS (SELECT 1 FROM agent_subagents s WHERE s.removed_at IS NULL
                AND ((s.orchestrator_member_id = p_from AND s.subagent_member_id = p_to)
                  OR (s.orchestrator_member_id = p_to AND s.subagent_member_id = p_from))) THEN
        RETURN NULL;
    END IF;
    -- Two orchestrators with the same parent (a hand-off between leads).
    fp := agent_parent_orchestrator(p_from);
    tp := agent_parent_orchestrator(p_to);
    IF fp IS NOT NULL AND fp = tp THEN
        RETURN NULL;
    END IF;
    RETURN 'You may message your orchestrator, the agents on your roster, and leads beside you under the same orchestrator — not that agent.';
END$$;

-- Send one message, with every rule in one place. Returns the message id; raises the refusal otherwise.
CREATE FUNCTION app_message_send(p_from bigint, p_to bigint, p_kind text, p_subject text, p_body text,
                                 p_thread bigint, p_priority text, p_channel text, p_related_run bigint,
                                 p_external_ref text, p_sent_run bigint)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public' AS $$
DECLARE why text; th agent_message_threads%ROWTYPE; mid bigint; recent integer; prin bigint;
BEGIN
    why := app_message_refusal(p_from, p_to);
    IF why IS NOT NULL THEN RAISE EXCEPTION '%', why; END IF;
    SELECT count(*) INTO recent FROM agent_messages
     WHERE from_member_id = p_from AND to_member_id = p_to AND created_at > now() - interval '1 hour';
    IF recent >= 30 AND (SELECT member_kind FROM members WHERE id = p_from) = 'agent' THEN
        RAISE EXCEPTION 'Thirty messages an hour to the same member is the limit — wait, or put it all in one message';
    END IF;
    IF p_thread IS NULL THEN
        prin := COALESCE((SELECT principal_member_id FROM agent_profiles WHERE member_id = p_to),
                         (SELECT principal_member_id FROM agent_profiles WHERE member_id = p_from),
                         CASE WHEN (SELECT member_kind FROM members WHERE id = p_from) = 'human' THEN p_from END,
                         CASE WHEN (SELECT member_kind FROM members WHERE id = p_to) = 'human' THEN p_to END);
        INSERT INTO agent_message_threads (subject, principal_member_id, opened_by) VALUES (left(p_subject, 300), prin, p_from)
        RETURNING * INTO th;
    ELSE
        SELECT * INTO th FROM agent_message_threads WHERE id = p_thread FOR UPDATE;
        IF th.id IS NULL THEN RAISE EXCEPTION 'That thread does not exist'; END IF;
        IF NOT EXISTS (SELECT 1 FROM agent_messages m WHERE m.thread_id = th.id AND p_from IN (m.from_member_id, m.to_member_id))
           AND th.opened_by <> p_from THEN
            RAISE EXCEPTION 'You are not in that thread';
        END IF;
        IF th.parked_at IS NOT NULL AND (SELECT member_kind FROM members WHERE id = p_from) = 'agent' THEN
            RAISE EXCEPTION 'This thread has gone back and forth twelve times and is parked — tell your orchestrator what is unresolved in a new thread';
        END IF;
        IF th.closed_at IS NOT NULL THEN
            RAISE EXCEPTION 'That thread is closed — start a new one if something is still open';
        END IF;
    END IF;
    INSERT INTO agent_messages (thread_id, from_member_id, to_member_id, kind, priority, subject, body, channel,
                                related_run_id, external_ref, sent_run_id)
    VALUES (th.id, p_from, p_to, p_kind, COALESCE(p_priority, 'normal'), left(p_subject, 300), p_body,
            COALESCE(p_channel, 'internal'), p_related_run, p_external_ref, p_sent_run)
    RETURNING id INTO mid;
    -- The twelfth message parks the thread: agents may send no more on it (a person still may).
    UPDATE agent_message_threads SET hop_count = hop_count + 1, last_message_at = now(),
           parked_at = CASE WHEN hop_count + 1 >= 12 THEN coalesce(parked_at, now()) ELSE parked_at END
     WHERE id = th.id;
    RETURN mid;
END$$;

-- Who may see a message: its sender and recipient, whoever may see either agent, and super-admins.
CREATE VIEW mcp_agent_messages WITH (security_barrier = true) AS
 SELECT m.id AS message_id, m.thread_id, t.subject AS thread_subject, m.from_member_id, fm.display_name AS from_name,
        fm.member_kind AS from_kind, m.to_member_id, tm.display_name AS to_name, tm.member_kind AS to_kind,
        m.kind, m.priority, m.subject, m.body, m.related_run_id, m.related_entity_type, m.related_entity_id,
        m.channel, m.status, m.done_note, m.woke_run_id, m.sent_run_id, m.created_at, m.read_at, m.done_at,
        t.principal_member_id, t.hop_count, t.parked_at
   FROM agent_messages m
   JOIN agent_message_threads t ON t.id = m.thread_id
   JOIN members fm ON fm.id = m.from_member_id
   JOIN members tm ON tm.id = m.to_member_id
  WHERE app_current_member_id() IN (m.from_member_id, m.to_member_id)
     OR app_is_super_admin()
     OR (fm.member_kind = 'agent' AND app_can_see_agent(m.from_member_id))
     OR (tm.member_kind = 'agent' AND app_can_see_agent(m.to_member_id));

ALTER TABLE agent_message_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY agent_message_threads_app_rw ON agent_message_threads TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY agent_messages_app_rw ON agent_messages TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY agent_message_threads_runner ON agent_message_threads TO app_runner USING (true) WITH CHECK (true);
CREATE POLICY agent_messages_runner ON agent_messages TO app_runner USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON agent_message_threads, agent_messages TO app_rw, app_runner;
GRANT SELECT ON mcp_agent_messages TO app_rw, app_records_ro;
GRANT EXECUTE ON FUNCTION app_message_refusal(bigint, bigint) TO app_rw, app_records_ro, app_runner;
GRANT EXECUTE ON FUNCTION app_message_send(bigint, bigint, text, text, text, bigint, text, text, bigint, text, bigint) TO app_rw, app_runner;

-- A run a message woke.
ALTER TABLE agent_runs DROP CONSTRAINT agent_runs_trigger_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_trigger_check CHECK (trigger = ANY (ARRAY['duty', 'location_task', 'assistant', 'chat', 'eval', 'manual', 'delegation', 'message']));

COMMIT;
