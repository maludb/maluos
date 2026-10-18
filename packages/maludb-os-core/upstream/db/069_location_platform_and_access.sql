-- 069_location_platform_and_access.sql
-- The estate records what a machine IS and how we get into it.
--
-- Decided 2026-09-18, two changes asked for after the Estate slice shipped:
--
--   1. The platform vocabulary was written from the hypervisor's point of view (proxmox, kvm,
--      lxc, bare_metal, cloud, workstation, other) — a mix of products and categories that did
--      not answer the question an operator actually asks, which is "what kind of machine is
--      this?". Replaced with five kinds that do.
--   2. Four facts were missing that anyone maintaining an estate needs: what operating system
--      it runs, which version, whether we have SSH to it, and whether we have root on it.
--
-- Mapping of the old vocabulary, applied to existing rows:
--     proxmox, kvm, lxc -> physical_hypervisor   (a physical host running guests)
--     bare_metal        -> physical_os           (a physical host running an OS directly)
--     cloud             -> vps                   (somebody else's hypervisor)
--     workstation       -> desktop
--     other             -> NULL                  (the new vocabulary has no "other"; platform
--                                                 is nullable, so "not recorded" is honest
--                                                 where "other" was not)
-- Only one row carried a platform at all (`MaluDB Hosting`, proxmox), so this is a rename in
-- practice rather than a reclassification.

BEGIN;

-- --------------------------------------------------------------------------
-- 1. The platform vocabulary
-- --------------------------------------------------------------------------
ALTER TABLE locations DROP CONSTRAINT locations_platform_check;

UPDATE locations SET platform = CASE platform
    WHEN 'proxmox'     THEN 'physical_hypervisor'
    WHEN 'kvm'         THEN 'physical_hypervisor'
    WHEN 'lxc'         THEN 'physical_hypervisor'
    WHEN 'bare_metal'  THEN 'physical_os'
    WHEN 'cloud'       THEN 'vps'
    WHEN 'workstation' THEN 'desktop'
    WHEN 'other'       THEN NULL
    ELSE platform
END
WHERE platform IS NOT NULL;

ALTER TABLE locations ADD CONSTRAINT locations_platform_check CHECK (
    platform IN ('physical_hypervisor', 'physical_os', 'vps', 'desktop', 'laptop')
);

COMMENT ON COLUMN locations.platform IS
    'What kind of machine this is: physical_hypervisor (a physical server running guests), '
    'physical_os (a physical server running an OS directly), vps (a virtual private server on '
    'somebody else''s hypervisor), desktop, laptop. NULL = not recorded.';

-- --------------------------------------------------------------------------
-- 2. What it runs, and how we get in
-- --------------------------------------------------------------------------
ALTER TABLE locations
    ADD COLUMN operating_system text,
    ADD COLUMN os_version       text,
    ADD COLUMN ssh_access       boolean,
    ADD COLUMN root_access      boolean;

COMMENT ON COLUMN locations.operating_system IS
    'The OS as recorded by whoever maintains the estate, e.g. "Ubuntu", "Windows 11". Distinct '
    'from os_platform, which the desktop companion reports about itself at enrolment (phase 6): '
    'this one is what we know, that one is what the machine says.';
COMMENT ON COLUMN locations.os_version IS 'e.g. "24.04 LTS". NULL = not recorded.';
COMMENT ON COLUMN locations.ssh_access IS
    'Do we have SSH to this machine? NULL = not recorded, which is not the same as no. The form '
    'offers Yes / No / not recorded so an unanswered question is never stored as a denial.';
COMMENT ON COLUMN locations.root_access IS
    'Do we have root (or administrator) on this machine? NULL = not recorded.';

-- --------------------------------------------------------------------------
-- 3. The view carries them. New columns are appended, so CREATE OR REPLACE is
--    enough and the view's grants and security_barrier survive untouched —
--    unlike db/067, which inserted columns mid-list and had to drop and rebuild.
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
    l.control,
    location_effective_control(l.id) AS effective_control,
    l.siting,
    location_allows_resident(l.id, 'agent') AS allows_agents,
    location_allows_resident(l.id, 'human') AS allows_humans,
    l.platform,
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
    ( SELECT count(*) FROM locations c
       WHERE c.parent_location_id = l.id AND c.status = 'active') AS child_count,
    ( SELECT count(*) FROM location_residents r
       WHERE r.location_id = l.id AND r.removed_at IS NULL) AS resident_count,
    ( SELECT count(*) FROM departments d
       WHERE d.home_location_id = l.id AND d.archived_at IS NULL) AS department_count,
    l.operating_system,
    l.os_version,
    l.ssh_access,
    l.root_access
   FROM locations l
     LEFT JOIN members om ON om.id = l.owner_member_id
     LEFT JOIN locations pl ON pl.id = l.parent_location_id
  WHERE app_is_insider();

COMMIT;
