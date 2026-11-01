-- 192: federated memory, the kernel half of Phase 13 slice 4 (maluos: docs/phase13-slice4-memory.md). Every MaluOS
-- host is a memory host (its own MaluDB tenant, the principals and scopes of its agents); this slice gives each host a
-- MEMORY FACE that answers scoped queries for the estate. The host's heartbeat carries its MEMORY FACTS (the
-- departmental and enterprise scopes it holds, how much, how fresh, which of them it shares, its ceiling, its port);
-- the kernel keeps them beside the inference facts and publishes, per member, the HOLDERS it may ask for each scope
-- (endpoints.memory) and, per holder, the PEERS allowed to ask it. The kernel never relays a query: the member's own
-- face asks the holders over the overlay with the slice 2 envelope as the credential (the keys are at /estate/keys);
-- the office's own memory (the agent-memory stage H4) is one holder more, answered at .../memory/query. Who may read
-- what is the estate's POLICY (estate_memory_policy): by default every active member reads `org`, a desk reads the
-- `dept:N` scopes of its owner's departments, a server or inference node reads every department, the ceiling is
-- `internal`; a desk holder serves servers and the coordinator only, never another desk (the plan's decision 5).
-- A rule may also mark a scope's summaries for replication to the subject.
--
-- Additive: two tables, one single-row settings table, two columns on locations.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/192_estate_memory.sql
BEGIN;

-- --------------------------------------------------------------------------
-- 1. The memory facts, one row per member that reported them
-- --------------------------------------------------------------------------
CREATE TABLE estate_memory (
    location_id         bigint PRIMARY KEY REFERENCES locations(id) ON DELETE CASCADE,
    scopes              jsonb NOT NULL DEFAULT '[]',          -- [{scope, count, updated_at, kinds}] the departmental and enterprise scopes the host holds (never personal ones)
    shared              jsonb NOT NULL DEFAULT '[]',          -- the scopes the host serves to the estate (`maluctl memory share`)
    max_classification  text NOT NULL DEFAULT 'internal' CHECK (max_classification IN ('public', 'internal', 'restricted', 'prohibited')),  -- the host's own ceiling
    port                integer NOT NULL DEFAULT 11437 CHECK (port BETWEEN 1 AND 65535),
    api_version         integer NOT NULL DEFAULT 1,
    signature           text NOT NULL DEFAULT '',             -- what the published view depends on (the scopes held and shared, the ceiling, the port): a change bumps the version
    updated_at          timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE estate_memory IS 'The memory facts each member reports with its heartbeat (db/192): the scopes its face holds and shares, its ceiling, its port. The published holders are the sharing members with an overlay address.';

-- --------------------------------------------------------------------------
-- 2. The policy: who may read which scope from which holder (the most specific subject wins; a rule naming one holder
--    beats one for any; a rule naming one scope beats one for any; a deny beats an allow at the same depth)
-- --------------------------------------------------------------------------
CREATE TABLE estate_memory_policy (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject              text NOT NULL CHECK (subject = 'org' OR subject ~ '^(dept:[0-9]+|kind:(desk|server|inference)|node:[0-9]+)$'),
    scope                text NOT NULL DEFAULT '*' CHECK (scope = '*' OR scope = 'org' OR scope ~ '^dept:[0-9]+$'),   -- * = any scope
    holder_location_id   bigint REFERENCES locations(id) ON DELETE CASCADE,   -- null = any holder, the office included
    allow                boolean NOT NULL DEFAULT true,
    max_classification   text CHECK (max_classification IN ('public', 'internal', 'restricted', 'prohibited')),  -- null = internal
    replicate            boolean NOT NULL DEFAULT false,     -- the subject may copy the holder's summaries of the scope
    priority             integer NOT NULL DEFAULT 0,         -- ranks the holder on the caller
    note                 text,
    created_by_member_id bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX estate_memory_policy_subject_idx ON estate_memory_policy (subject);
COMMENT ON TABLE estate_memory_policy IS 'Who may read which memory scope from which holder (db/192): subject org | dept:N | kind:desk|server|inference | node:ID, scope org | dept:N | *, one holder or any. Empty = the defaults (org for everyone, a desk its owner''s departments, a server every department, internal); a desk holder never serves another desk whatever the rules say.';

-- --------------------------------------------------------------------------
-- 3. The versions every member polls against, and the limits
-- --------------------------------------------------------------------------
CREATE TABLE estate_memory_settings (
    id             smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version        bigint NOT NULL DEFAULT 1,               -- the holders as callers see them: bumped when a holder's view, the policy or the membership change
    peers_version  bigint NOT NULL DEFAULT 1,               -- the peers as holders see them: bumped when the policy or the membership change
    fanout_max     integer NOT NULL DEFAULT 8 CHECK (fanout_max BETWEEN 1 AND 32),      -- how many holders a caller asks at once
    rate_per_min   integer NOT NULL DEFAULT 30 CHECK (rate_per_min BETWEEN 1 AND 1000), -- the office's own answers, per member
    updated_at     timestamptz NOT NULL DEFAULT now()
);
INSERT INTO estate_memory_settings (id) VALUES (1);
COMMENT ON TABLE estate_memory_settings IS 'One row (db/192): the holder and peer versions heartbeats say memory_changed / memory_peers_changed against, the fan-out and the office''s rate.';

-- --------------------------------------------------------------------------
-- 4. The versions each member last heard
-- --------------------------------------------------------------------------
ALTER TABLE locations ADD COLUMN memory_seen_version bigint NOT NULL DEFAULT 0;
ALTER TABLE locations ADD COLUMN memory_peers_seen_version bigint NOT NULL DEFAULT 0;
COMMENT ON COLUMN locations.memory_seen_version IS 'The estate_memory_settings.version this member last heard (memory_changed).';
COMMENT ON COLUMN locations.memory_peers_seen_version IS 'The estate_memory_settings.peers_version this member last heard (memory_peers_changed).';

-- --------------------------------------------------------------------------
-- 5. Row-level security and grants, as the other estate tables
-- --------------------------------------------------------------------------
ALTER TABLE estate_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_memory_app_rw ON estate_memory FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_memory TO app_rw;
ALTER TABLE estate_memory_policy ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_memory_policy_app_rw ON estate_memory_policy FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_memory_policy TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_memory_policy_id_seq TO app_rw;
ALTER TABLE estate_memory_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_memory_settings_app_rw ON estate_memory_settings FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, UPDATE ON estate_memory_settings TO app_rw;

COMMIT;
