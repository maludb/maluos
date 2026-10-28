-- 189: the overlay, the kernel half of Phase 13 slice 1b (maluos: docs/phase13-slice1b-overlay.md; the owner
-- approved 2026-10-28). Every node of the estate (server, inference, desk) gets an address on the estate's
-- private WireGuard network and a name; the hub is the coordinator's host; the kernel allocates the addresses,
-- keeps the public keys and publishes the hub, the peers and the names (GET /api/v1/estate/overlay,
-- /api/v1/desks/overlay). Additive: one settings row, four columns on locations.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/189_estate_overlay.sql
BEGIN;

CREATE TABLE estate_overlay (
    id               smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),      -- one row: the estate's network
    enabled          boolean NOT NULL DEFAULT true,
    range            cidr NOT NULL DEFAULT '100.100.0.0/16',             -- the CGNAT block: no LAN uses it
    hub_location_id  bigint REFERENCES locations(id) ON DELETE SET NULL,  -- the coordinator's host, joined with --hub
    hub_endpoint     text,                                                -- host:port the spokes dial (UDP 51820 by default)
    hub_public_key   text,
    version          bigint NOT NULL DEFAULT 1,                           -- bumped on any change; heartbeats say overlay_changed
    updated_at       timestamptz NOT NULL DEFAULT now()
);
INSERT INTO estate_overlay (id) VALUES (1);
COMMENT ON TABLE estate_overlay IS 'The estate''s overlay network (db/189): the range, the hub, a version every member polls against.';

ALTER TABLE locations ADD COLUMN overlay_public_key text;
ALTER TABLE locations ADD COLUMN overlay_address inet;
ALTER TABLE locations ADD COLUMN overlay_address_freed_at timestamptz;
ALTER TABLE locations ADD COLUMN overlay_seen_version bigint NOT NULL DEFAULT 0;
COMMENT ON COLUMN locations.overlay_public_key IS 'The member''s WireGuard public key (base64), from join/enroll or a rotation; the private half never leaves its vault.';
COMMENT ON COLUMN locations.overlay_address IS 'The member''s address on the overlay, given at join and kept for its life; freed_at set on retirement and reused after 30 days.';
COMMENT ON COLUMN locations.overlay_seen_version IS 'The estate_overlay.version this member last heard of in a heartbeat answer (overlay_changed).';
CREATE UNIQUE INDEX locations_overlay_address_live_idx ON locations (overlay_address) WHERE overlay_address IS NOT NULL AND overlay_address_freed_at IS NULL;

ALTER TABLE estate_overlay ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_overlay_app_rw ON estate_overlay FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, UPDATE ON estate_overlay TO app_rw;

COMMIT;
