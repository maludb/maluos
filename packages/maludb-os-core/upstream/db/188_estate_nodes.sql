-- 188: the estate's nodes, the kernel half of Phase 13 slice 1 (maluos: docs/phase13-slice1-nodes.md; the owner
-- approved 2026-10-28). A MaluOS server or inference host joins the estate the way a desk does (db/187): a
-- one-time code an operator mints, exchanged at POST /api/v1/estate/join for a NODE TOKEN (mcp_access_tokens,
-- scope 'node', bound to the node's location row, never resolved by the MCP servers), then heartbeats with its
-- facts and, every report_s, the report an operator needs; the kernel applies fixed health rules to the report
-- and keeps the estate's alerts. Desks whose owner is an operator read the estate (GET /api/v1/desks/estate).
-- Additive: two location kinds, five columns, one scope, a kind on the codes, two tables, a resolver that
-- skips node tokens. The mcp_locations view is unchanged (nothing reads the new columns through it yet).
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/188_estate_nodes.sql
BEGIN;

-- --------------------------------------------------------------------------
-- 1. Node kinds and what a node carries
-- --------------------------------------------------------------------------
ALTER TABLE locations DROP CONSTRAINT locations_kind_check;
ALTER TABLE locations ADD CONSTRAINT locations_kind_check
    CHECK (kind IN ('building', 'office', 'desk', 'site', 'server', 'inference'));
ALTER TABLE locations ADD COLUMN report jsonb;
ALTER TABLE locations ADD COLUMN last_report_at timestamptz;
ALTER TABLE locations ADD COLUMN public_key text;
ALTER TABLE locations ADD COLUMN enrolled_by_member_id bigint REFERENCES members(id) ON DELETE SET NULL;
ALTER TABLE locations ADD COLUMN components text[];
COMMENT ON COLUMN locations.report IS 'server, inference: the node''s last report (units, agents, gateway, vault alerts, updates, disk, memory, load), under 32 KB.';
COMMENT ON COLUMN locations.last_report_at IS 'server, inference: when the last report arrived; heartbeats between reports carry presence and facts only.';
COMMENT ON COLUMN locations.public_key IS 'server, inference: the node key''s public half (ssh-ed25519), from the join; slice 2 verifies envelopes with it.';
COMMENT ON COLUMN locations.enrolled_by_member_id IS 'server, inference: the operator whose code the node joined with; the node token''s member.';
COMMENT ON COLUMN locations.components IS 'server, inference: what the host''s provisioning record says it runs (postgresql-18, vault, gateway, …).';
CREATE INDEX locations_node_machine_idx ON locations (machine_id) WHERE kind IN ('server', 'inference') AND status = 'active';

-- --------------------------------------------------------------------------
-- 2. The node token: scope 'node', bound to its location, one live per node, never a person for the MCP servers
-- --------------------------------------------------------------------------
ALTER TABLE mcp_access_tokens DROP CONSTRAINT mcp_access_tokens_scope_check;
ALTER TABLE mcp_access_tokens ADD CONSTRAINT mcp_access_tokens_scope_check
    CHECK (scope IN ('mcp', 'api', 'application', 'desk', 'node'));
CREATE UNIQUE INDEX mcp_access_tokens_node_live_idx ON mcp_access_tokens (location_id)
    WHERE scope = 'node' AND revoked_at IS NULL;

-- db/014's resolver maps any live token to its member for records and activity; a node token is a machine's,
-- held in its vault, and must never read as the operator who enrolled it. The estate endpoints resolve it themselves.
CREATE OR REPLACE FUNCTION mcp_resolve_token(p_hash text)
RETURNS TABLE(member_id bigint, member_role text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE mcp_access_tokens
       SET last_used_at = now()
     WHERE token_hash = p_hash AND revoked_at IS NULL AND scope <> 'node'
       AND (expires_at IS NULL OR expires_at > now());

    RETURN QUERY
        SELECT m.id, m.role
        FROM mcp_access_tokens t
        JOIN members m ON m.id = t.member_id
        WHERE t.token_hash = p_hash AND t.revoked_at IS NULL AND t.scope <> 'node'
          AND (t.expires_at IS NULL OR t.expires_at > now())
          AND m.status = 'active';
END$$;

-- --------------------------------------------------------------------------
-- 3. A code is minted for a kind: a desk code enrols only a desk, a node code only a node of its kind
-- --------------------------------------------------------------------------
ALTER TABLE desk_enrollment_codes ADD COLUMN kind text NOT NULL DEFAULT 'desk'
    CHECK (kind IN ('desk', 'server', 'inference'));
COMMENT ON COLUMN desk_enrollment_codes.kind IS 'desk (the person''s own desk) or server/inference (an operator''s code for a node; member_id is then the operator).';

-- --------------------------------------------------------------------------
-- 4. The reports kept (24 per node, trimmed by the sweep) and the estate's alerts
-- --------------------------------------------------------------------------
CREATE TABLE estate_node_reports (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id   bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    ts            timestamptz NOT NULL DEFAULT now(),
    report        jsonb NOT NULL
);
CREATE INDEX estate_node_reports_node_idx ON estate_node_reports (location_id, ts DESC);
COMMENT ON TABLE estate_node_reports IS 'The last reports of each node (db/188); the presence sweep keeps 24 per node.';

CREATE TABLE estate_alerts (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id   bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    kind          text NOT NULL CHECK (kind IN ('unit_down', 'agent_down', 'vault_alert', 'reboot_required', 'disk_full', 'memory_low', 'node_offline', 'manual')),
    key           text NOT NULL,                    -- the subject: the unit, the agent, the mount, the vault alert id, 'presence'
    severity      text NOT NULL CHECK (severity IN ('warning', 'critical')),
    title         text NOT NULL,
    raised_at     timestamptz NOT NULL DEFAULT now(),
    cleared_at    timestamptz,
    report_ts     text                              -- the report's own ts that raised or last confirmed it
);
CREATE UNIQUE INDEX estate_alerts_open_idx ON estate_alerts (location_id, kind, key) WHERE cleared_at IS NULL;
CREATE INDEX estate_alerts_recent_idx ON estate_alerts (cleared_at, raised_at);
COMMENT ON TABLE estate_alerts IS 'What the kernel''s fixed health rules found in a node''s report, one open row per (node, kind, subject); node_offline from presence. Cleared when the next report no longer shows the cause.';

ALTER TABLE estate_node_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_node_reports_app_rw ON estate_node_reports FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, DELETE ON estate_node_reports TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_node_reports_id_seq TO app_rw;
ALTER TABLE estate_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_alerts_app_rw ON estate_alerts FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON estate_alerts TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_alerts_id_seq TO app_rw;

-- --------------------------------------------------------------------------
-- 5. A node's join and leave are logged with their own source
-- --------------------------------------------------------------------------
ALTER TABLE activity_log DROP CONSTRAINT activity_log_source_check;
ALTER TABLE activity_log ADD CONSTRAINT activity_log_source_check
    CHECK (source IN ('web', 'assistant', 'mcp', 'cron', 'agent', 'desk', 'webhook', 'portal', 'api', 'application', 'node'));

COMMIT;
