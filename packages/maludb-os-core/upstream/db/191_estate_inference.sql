-- 191: shared inference across the estate, the kernel half of Phase 13 slice 3 (maluos:
-- docs/phase13-slice3-inference.md). A GPU host that joins the estate is, without any pairing by hand, a backend
-- of every desk and server the estate's policy allows: its heartbeat carries its INFERENCE FACTS (the models it
-- serves, the lanes, the queue, the expected wait, the sharing switch and the contribution rule); the kernel keeps
-- them beside the directory and publishes, per member, the backends that member may use (endpoints.inference)
-- and, per serving host, the members allowed to call it (the peers). The kernel never routes a model call: each
-- member's own gateway makes a rung per backend and ranks it with its local and cloud rungs. The member's
-- INFERENCE KEY (a bearer secret minted at join or enrol, kept beside the node token; only its SHA-256 here) is the
-- estate's inference credential: the serving host verifies it against the peers list, so no key crosses the
-- estate by hand. Who may use what is the estate's POLICY (estate_inference_policy); the default lets every active
-- member use every shared backend, and a desk's contribution is used by servers and the coordinator only, never by
-- other desks (decision 4). With the `scheduler` entitlement (Phase 9; a flag here until the contracts service
-- sets it) the kernel also answers PLACEMENT (POST .../inference/place) from the live queue.
--
-- Additive: two tables, one single-row settings table, three columns on locations.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/191_estate_inference.sql
BEGIN;

-- --------------------------------------------------------------------------
-- 1. The inference facts, one row per member that reported them (a node, or a desk that shares)
-- --------------------------------------------------------------------------
CREATE TABLE estate_inference (
    location_id      bigint PRIMARY KEY REFERENCES locations(id) ON DELETE CASCADE,
    models           jsonb NOT NULL DEFAULT '[]',          -- [{name, family, size, loaded, backend}]
    lanes            jsonb NOT NULL DEFAULT '{}',          -- the gateway's lanes (capacity, running, queued, paused, per class expected wait)
    queue            jsonb NOT NULL DEFAULT '{}',          -- {queued, running}
    expected_wait_s  jsonb NOT NULL DEFAULT '{}',          -- {class: seconds}
    share            boolean NOT NULL DEFAULT false,       -- the sharing switch as the host resolves it (the chassis rule, the idle rule)
    contribution     text NOT NULL DEFAULT 'always' CHECK (contribution IN ('always', 'idle')),
    port             integer NOT NULL DEFAULT 11435 CHECK (port BETWEEN 1 AND 65535),
    api_version      integer NOT NULL DEFAULT 1,
    signature        text NOT NULL DEFAULT '',             -- what the published view depends on (models, share, contribution, port): a change bumps the version
    updated_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE estate_inference IS 'The inference facts each member reports with its heartbeat (db/191): what its gateway serves, its queue and wait, its sharing switch. The published backends are the shared ones with an overlay address.';

-- --------------------------------------------------------------------------
-- 2. The policy: who may use which backends (the most specific subject wins; a deny beats an allow at the same depth)
-- --------------------------------------------------------------------------
CREATE TABLE estate_inference_policy (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject              text NOT NULL CHECK (subject = 'org' OR subject ~ '^(dept:[0-9]+|kind:(desk|server|inference)|node:[0-9]+)$'),
    backend_location_id  bigint REFERENCES locations(id) ON DELETE CASCADE,   -- null = any backend
    allow                boolean NOT NULL DEFAULT true,
    max_class            text CHECK (max_class IN ('interactive', 'agent', 'batch')),   -- the gateway class ceiling on the serving host; null = the host's default
    max_classification   text CHECK (max_classification IN ('public', 'internal', 'restricted', 'prohibited')),  -- null = internal
    priority             integer NOT NULL DEFAULT 0,        -- higher places first (the scheduler), ranks the rung on the caller
    note                 text,
    created_by_member_id bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX estate_inference_policy_subject_idx ON estate_inference_policy (subject);
COMMENT ON TABLE estate_inference_policy IS 'Who may use which shared backends (db/191): subject org | dept:N | kind:desk|server|inference | node:ID, one backend or any. Empty = every active member may use every shared backend; a desk''s contribution is never used by other desks whatever the rules say.';

-- --------------------------------------------------------------------------
-- 3. The versions every member polls against, and the entitlement
-- --------------------------------------------------------------------------
CREATE TABLE estate_inference_settings (
    id             smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version        bigint NOT NULL DEFAULT 1,               -- the backends as callers see them: bumped when a backend's facts, the policy or the membership change
    peers_version  bigint NOT NULL DEFAULT 1,               -- the peers as serving hosts see them: bumped when a key, the policy or the membership change
    scheduler      boolean NOT NULL DEFAULT false,          -- the `scheduler` entitlement of Phase 9 (the contracts service will set it; a super-admin flips it meanwhile)
    lease_s        integer NOT NULL DEFAULT 30 CHECK (lease_s BETWEEN 5 AND 600),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
INSERT INTO estate_inference_settings (id) VALUES (1);
COMMENT ON TABLE estate_inference_settings IS 'One row (db/191): the backend and peer versions heartbeats say inference_changed / peers_changed against, and the scheduler entitlement.';

-- --------------------------------------------------------------------------
-- 4. Every member's inference key (its SHA-256 only) and the versions it last heard
-- --------------------------------------------------------------------------
ALTER TABLE locations ADD COLUMN inference_key_hash text;
ALTER TABLE locations ADD COLUMN inference_seen_version bigint NOT NULL DEFAULT 0;
ALTER TABLE locations ADD COLUMN peers_seen_version bigint NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX locations_inference_key_idx ON locations (inference_key_hash) WHERE inference_key_hash IS NOT NULL;
COMMENT ON COLUMN locations.inference_key_hash IS 'desk, server, inference: SHA-256 of the member''s inference key (db/191), minted at join or enrol and shown once; a serving host checks a presented key against the peers answer.';
COMMENT ON COLUMN locations.inference_seen_version IS 'The estate_inference_settings.version this member last heard (inference_changed).';
COMMENT ON COLUMN locations.peers_seen_version IS 'The estate_inference_settings.peers_version this member last heard (peers_changed).';

-- --------------------------------------------------------------------------
-- 5. Row-level security and grants, as the other estate tables
-- --------------------------------------------------------------------------
ALTER TABLE estate_inference ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_inference_app_rw ON estate_inference FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_inference TO app_rw;
ALTER TABLE estate_inference_policy ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_inference_policy_app_rw ON estate_inference_policy FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON estate_inference_policy TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_inference_policy_id_seq TO app_rw;
ALTER TABLE estate_inference_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_inference_settings_app_rw ON estate_inference_settings FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, UPDATE ON estate_inference_settings TO app_rw;

COMMIT;
