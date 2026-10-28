-- 190: the agent directory and delegation, the kernel half of Phase 13 slice 2 (maluos:
-- docs/phase13-slice2-delegation.md). Every agent on every node is listed by what it can do; a person or an
-- agent sends a task to an agent anywhere in the estate with a signed ENVELOPE (who originated it, what
-- authority they delegate, what the data may touch); the kernel stores the task durably, hands it to the
-- agent's node when that node long-polls its inbox, and keeps the result with its provenance. The node that
-- hosts the agent verifies the envelope itself (the kernel checks it too, and refuses what it can see is wrong).
-- A person's questions, decisions and results from estate agents are their ESTATE INBOX, read by their desk.
-- A system manager's action on a remote node (restart an agent, apply updates) travels the same way.
--
-- Additive: five tables, one single-row key table, one index on locations. agent_messages is NOT used for the
-- inbox: its tree rule lets only a person's own assistant write to them, and an agent on a node is not a member
-- until Agent HR hires it (estate_agents.agent_member_id links the two then).
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/190_estate_delegation.sql
BEGIN;

-- --------------------------------------------------------------------------
-- 1. The directory: every agent a node registered (location_id null = the coordinator's own agents)
-- --------------------------------------------------------------------------
CREATE TABLE estate_agents (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id        bigint REFERENCES locations(id) ON DELETE CASCADE,   -- the node; null for the coordinator
    name               text NOT NULL CHECK (name ~ '^[a-z][a-z0-9-]{0,30}$'),
    principal          text NOT NULL,                                          -- agent:NAME on its host
    display_name       text,
    description        text,
    capabilities       text[] NOT NULL DEFAULT '{}',                           -- free-form lowercase tags
    owner              text,                                                   -- the host's owner principal (user:LOGIN), or null
    accept_from        text[] NOT NULL DEFAULT '{}',                           -- org, dept:N, user:LOGIN, agent:NAME, node:KIND; empty = its owner only
    max_classification text CHECK (max_classification IN ('public', 'internal', 'restricted', 'prohibited')),
    approve            text[] NOT NULL DEFAULT '{}',                           -- classifications or originators that wait for the owner
    tasks              boolean NOT NULL DEFAULT true,                          -- serves the task interface
    unit_state         text,                                                   -- active, failed, inactive (from the node's report)
    card               jsonb,
    agent_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,      -- Agent HR's member once the office hires it
    status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    first_seen_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at       timestamptz NOT NULL DEFAULT now(),
    removed_at         timestamptz
);
CREATE UNIQUE INDEX estate_agents_node_name_idx ON estate_agents (coalesce(location_id, 0), name);
CREATE INDEX estate_agents_capabilities_idx ON estate_agents USING gin (capabilities) WHERE status = 'active';
COMMENT ON TABLE estate_agents IS 'The estate''s agent directory (db/190): what each node registered from its manifests; location_id null is the coordinator''s own agents. Linked to Agent HR by agent_member_id when hired.';

-- --------------------------------------------------------------------------
-- 2. The coordinator's own signing key (ed25519, made on first use; the public half is in the keys answer)
-- --------------------------------------------------------------------------
CREATE TABLE estate_coordinator (
    id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    public_key  text NOT NULL,                                                 -- ssh-ed25519 AAAA… (the same shape as a node's)
    secret_key  text NOT NULL,                                                 -- base64, libsodium's 64-byte secret key
    created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE estate_coordinator IS 'The coordinator''s envelope key (db/190): the kernel signs as "coordinator" for its own agents and for decisions it relays.';

-- --------------------------------------------------------------------------
-- 3. Tasks: durable, idempotent on (envelope id, hop), leased to the agent's node through its inbox
-- --------------------------------------------------------------------------
CREATE TABLE estate_tasks (
    id                    text PRIMARY KEY CHECK (id ~ '^t_[0-9a-f]{12,32}$'),
    envelope_id           text NOT NULL,
    hop                   integer NOT NULL DEFAULT 1 CHECK (hop >= 1),
    agent_id              bigint NOT NULL REFERENCES estate_agents(id) ON DELETE CASCADE,
    location_id           bigint REFERENCES locations(id) ON DELETE CASCADE,  -- the agent's node; null = the coordinator
    originator_principal  text NOT NULL,
    originator_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    sender_principal      text NOT NULL,
    sender_node           text NOT NULL,                                       -- desk:ID, server:ID, inference:ID, coordinator
    envelope              jsonb NOT NULL,
    message               jsonb NOT NULL,                                      -- the tasks/send message (parts)
    state                 text NOT NULL DEFAULT 'queued'
                              CHECK (state IN ('queued', 'leased', 'running', 'pending_approval', 'completed', 'failed', 'refused')),
    lease_until           timestamptz,
    leases                integer NOT NULL DEFAULT 0,
    result                jsonb,                                               -- the task record from the node (output, provenance, usage)
    reason                text,                                                -- the refusal's reason, or the failure's
    created_at            timestamptz NOT NULL DEFAULT now(),
    started_at            timestamptz,
    done_at               timestamptz
);
CREATE UNIQUE INDEX estate_tasks_envelope_idx ON estate_tasks (envelope_id, hop);
CREATE INDEX estate_tasks_inbox_idx ON estate_tasks (location_id, state) WHERE state IN ('queued', 'leased');
CREATE INDEX estate_tasks_recent_idx ON estate_tasks (created_at DESC);
CREATE INDEX estate_tasks_originator_idx ON estate_tasks (originator_member_id, created_at DESC);
COMMENT ON TABLE estate_tasks IS 'Tasks sent to estate agents (db/190): queued for the agent''s node, leased 120 s when its inbox poll takes them, completed/failed/refused with the result and its provenance.';

-- --------------------------------------------------------------------------
-- 4. Remote actions on a node (restart_agent, start_agent, stop_agent, apply_updates, reboot)
-- --------------------------------------------------------------------------
CREATE TABLE estate_actions (
    id                     text PRIMARY KEY CHECK (id ~ '^a_[0-9a-f]{12,32}$'),
    location_id            bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    action                 text NOT NULL CHECK (action IN ('restart_agent', 'start_agent', 'stop_agent', 'apply_updates', 'reboot')),
    agent                  text,                                                -- the agent's name for the agent actions
    envelope               jsonb NOT NULL,
    requested_by_member_id bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    state                  text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'leased', 'completed', 'failed', 'refused')),
    lease_until            timestamptz,
    leases                 integer NOT NULL DEFAULT 0,
    result                 jsonb,
    reason                 text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    done_at                timestamptz
);
CREATE INDEX estate_actions_inbox_idx ON estate_actions (location_id, state) WHERE state IN ('queued', 'leased');
CREATE INDEX estate_actions_recent_idx ON estate_actions (created_at DESC);
COMMENT ON TABLE estate_actions IS 'A system manager''s actions on remote nodes (db/190), queued to the node''s inbox; the node runs only what its own actions.allow permits.';

-- --------------------------------------------------------------------------
-- 5. The person's estate inbox: questions, decisions, results and notes from estate agents, read by their desk
-- --------------------------------------------------------------------------
CREATE TABLE estate_inbox (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind              text NOT NULL CHECK (kind IN ('question', 'decision_needed', 'result', 'fyi')),
    subject           text NOT NULL CHECK (btrim(subject) <> '' AND length(subject) <= 300),
    body              text NOT NULL DEFAULT '' CHECK (length(body) <= 20000),
    from_principal    text NOT NULL,                                           -- agent:helpdesk, coordinator
    from_node         text NOT NULL,                                           -- server:57, coordinator
    task_id           text REFERENCES estate_tasks(id) ON DELETE SET NULL,
    options           text[],                                                  -- a decision's choices (approve, deny by default)
    status            text NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read', 'done')),
    decision          text,
    decision_note     text,
    reply             text,
    answer_envelope   jsonb,                                                   -- the desk's signed reply or decision
    created_at        timestamptz NOT NULL DEFAULT now(),
    read_at           timestamptz,
    done_at           timestamptz
);
CREATE INDEX estate_inbox_member_idx ON estate_inbox (member_id, status, created_at DESC);
CREATE INDEX estate_inbox_task_idx ON estate_inbox (task_id) WHERE task_id IS NOT NULL;
COMMENT ON TABLE estate_inbox IS 'A person''s estate inbox (db/190): what estate agents ask or tell them; their desk long-polls it and answers with its signed envelope.';

-- --------------------------------------------------------------------------
-- 6. Replay memory at the kernel: one nonce per signing key for the envelope's lifetime
-- --------------------------------------------------------------------------
CREATE TABLE estate_nonces (
    key_node    text NOT NULL,
    nonce       text NOT NULL,
    expires_at  timestamptz NOT NULL,
    PRIMARY KEY (key_node, nonce)
);
CREATE INDEX estate_nonces_expiry_idx ON estate_nonces (expires_at);

-- --------------------------------------------------------------------------
-- 7. Desks get a key too (decision 3): locations.public_key (db/188) now carries a desk's ssh-ed25519 key as well
-- --------------------------------------------------------------------------
COMMENT ON COLUMN locations.public_key IS 'server, inference: the node key''s public half (ssh-ed25519), from the join; desk: the desk key, registered at enrol or by POST /api/v1/desks/key. Envelopes are verified with it (db/190).';

-- --------------------------------------------------------------------------
-- 8. Rights: the application role reads and writes all of it; row security is on with an allow-all policy
-- --------------------------------------------------------------------------
ALTER TABLE estate_agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_agents_app_rw ON estate_agents FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_agents TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_agents_id_seq TO app_rw;
ALTER TABLE estate_coordinator ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_coordinator_app_rw ON estate_coordinator FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT ON estate_coordinator TO app_rw;
ALTER TABLE estate_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_tasks_app_rw ON estate_tasks FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_tasks TO app_rw;
ALTER TABLE estate_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_actions_app_rw ON estate_actions FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_actions TO app_rw;
ALTER TABLE estate_inbox ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_inbox_app_rw ON estate_inbox FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_inbox TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_inbox_id_seq TO app_rw;
ALTER TABLE estate_nonces ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_nonces_app_rw ON estate_nonces FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, DELETE ON estate_nonces TO app_rw;

COMMIT;
