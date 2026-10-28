-- 095_drop_location_control.sql
-- Managed / unmanaged leaves the product.
--
-- Decided 2026-09-18 (owner), completing db/094. That migration stopped control from refusing
-- anything and left it on screen as a fact. The owner's answer to "shall the concept stay as
-- information?" was to remove it entirely: a business running this platform does not need the
-- platform's opinion about which machines it runs, and a field nobody acts on is a field
-- everybody has to read past.
--
-- So `locations.control` goes, with the inheritance function that derived it and the two
-- columns the view exposed. `siting` (onsite/offsite) is untouched — it answers a different
-- question, and the Front Office seed (db/074) relies on it.
--
-- What is lost: which hosts were marked managed. One row carried a value here (a building,
-- `unmanaged`), and it governed nothing after db/094, so nothing that answers a question today
-- goes with it.

BEGIN;

-- The view reads the column and the function, so it is rebuilt first, without them.
DROP VIEW mcp_locations;

CREATE VIEW mcp_locations AS
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
    -- Who may reside here: anyone at an office or a desk, nobody in a building. Both columns
    -- survive db/095 because callers ask them by name; since db/094 they answer the same
    -- question, which is now only about the kind of location.
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
    (SELECT count(*) FROM locations c
      WHERE c.parent_location_id = l.id AND c.status = 'active') AS child_count,
    (SELECT count(*) FROM location_residents r
      WHERE r.location_id = l.id AND r.removed_at IS NULL) AS resident_count,
    (SELECT count(*) FROM departments d
      WHERE d.home_location_id = l.id AND d.archived_at IS NULL) AS department_count
   FROM locations l
   LEFT JOIN members om ON om.id = l.owner_member_id
   LEFT JOIN locations pl ON pl.id = l.parent_location_id
  WHERE app_is_insider();

GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_locations TO app_rw;
GRANT SELECT ON mcp_locations TO app_records_ro;

DROP FUNCTION IF EXISTS location_effective_control(bigint);
ALTER TABLE locations DROP COLUMN control;

COMMIT;
