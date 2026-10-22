-- 187: desk enrolment, the kernel half (docs/build-specs/desk-enrolment.md, stage D2; the owner approved
-- 2026-10-22). A MaluOS desktop joins the estate as a desk (db/043's location kind) through four endpoints
-- under /api/v1/desks/ with a DESK TOKEN: an mcp_access_tokens row of the new scope 'desk', bound to the
-- desk's location row — one live token per desk — and the owner's own reach, nothing more. A person mints a
-- one-time ENROLMENT CODE for themselves (Settings, or bin/mint_desk_code.php); the desk exchanges it for the
-- token, so neither side ever sees the other's password. locations gains machine_id (what the desk reports
-- about itself, hashed) so a re-enrolment of the same machine retires the old row. db/185 is the forge's
-- K61 (reserved), db/186 K65. Additive; mcp_locations is recreated with machine_id appended last.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/187_desk_enrolment.sql
BEGIN;

-- --------------------------------------------------------------------------
-- 1. The desk token: scope 'desk', bound to its location, one live per desk
-- --------------------------------------------------------------------------
ALTER TABLE mcp_access_tokens DROP CONSTRAINT mcp_access_tokens_scope_check;
ALTER TABLE mcp_access_tokens ADD CONSTRAINT mcp_access_tokens_scope_check
    CHECK (scope IN ('mcp', 'api', 'application', 'desk'));
ALTER TABLE mcp_access_tokens ADD COLUMN location_id bigint REFERENCES locations(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX mcp_access_tokens_desk_live_idx ON mcp_access_tokens (location_id)
    WHERE scope = 'desk' AND revoked_at IS NULL;
COMMENT ON COLUMN mcp_access_tokens.location_id IS
    'scope = desk: the desk (locations.kind = desk) this token enrols. Revoked when the desk leaves or is retired.';

-- --------------------------------------------------------------------------
-- 2. The one-time enrolment code a person mints for themselves
-- --------------------------------------------------------------------------
CREATE TABLE desk_enrollment_codes (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id     bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,     -- who the desk will belong to
    code_hash     text NOT NULL UNIQUE,                                          -- sha256 of the shown-once code
    desk_name     text,                                                          -- optional, chosen when minting
    expires_at    timestamptz NOT NULL,                                          -- 15 minutes from minting
    used_at       timestamptz,
    location_id   bigint REFERENCES locations(id) ON DELETE SET NULL,            -- the desk it made
    created_by    bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,     -- the person, or an operator for them
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX desk_enrollment_codes_member_idx ON desk_enrollment_codes (member_id) WHERE used_at IS NULL;
COMMENT ON TABLE desk_enrollment_codes IS
    'One-time codes a MaluOS desktop exchanges for a desk token (POST /api/v1/desks/enroll). Minting again replaces a person''s live code.';

ALTER TABLE desk_enrollment_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY desk_enrollment_codes_app_rw ON desk_enrollment_codes FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON desk_enrollment_codes TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE desk_enrollment_codes_id_seq TO app_rw;

-- --------------------------------------------------------------------------
-- 3. What the desk says it is
-- --------------------------------------------------------------------------
ALTER TABLE locations ADD COLUMN machine_id text;
COMMENT ON COLUMN locations.machine_id IS
    'desk: the companion''s own machine identity (a sha256 prefix of /etc/machine-id); a re-enrolment with the same value retires the old row.';
CREATE INDEX locations_desk_machine_idx ON locations (owner_member_id, machine_id) WHERE kind = 'desk' AND status = 'active';

-- --------------------------------------------------------------------------
-- 4. The view carries it, appended last (db/069's rule).
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW mcp_locations AS
 SELECT l.id AS location_id,
    l.name,
    l.kind,
    l.parent_location_id,
    pl.name AS parent_location_name,
    l.description,
    l.owner_member_id,
    om.display_name AS owner_name,
    l.office_manager_member_id,
    l.status,
    l.presence,
    l.last_seen_at,
    l.siting,
    location_allows_resident(l.id, 'agent'::text) AS allows_agents,
    location_allows_resident(l.id, 'human'::text) AS allows_humans,
    l.platform,
    l.operating_system,
    l.os_version,
    l.ssh_access,
    l.root_access,
    l.external_ref,
    l.hostname,
    host(l.ip_address) AS ip_address,
    l.cpu_cores,
    l.memory_mb,
    l.storage_gb,
    l.is_always_on,
    l.app_version,
    l.os_platform,
    l.mcp_surface_version,
    l.enrolled_at,
    l.retired_at,
    ( SELECT count(*) AS count
           FROM locations c
          WHERE ((c.parent_location_id = l.id) AND (c.status = 'active'::text))) AS child_count,
    ( SELECT count(*) AS count
           FROM location_residents r
          WHERE ((r.location_id = l.id) AND (r.removed_at IS NULL))) AS resident_count,
    ( SELECT count(*) AS count
           FROM departments d
          WHERE ((d.home_location_id = l.id) AND (d.archived_at IS NULL))) AS department_count,
    l.address,
    l.timezone,
    ( SELECT count(*) AS count
           FROM application_scopes s
          WHERE ((s.location_id = l.id) AND (s.removed_at IS NULL))) AS serving_application_count,
    l.machine_id
   FROM ((locations l
     LEFT JOIN members om ON ((om.id = l.owner_member_id)))
     LEFT JOIN locations pl ON ((pl.id = l.parent_location_id)))
  WHERE app_is_insider();

COMMIT;
