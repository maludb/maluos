-- 067_location_control_siting.sql
-- A location's type decides who may live there.
--
-- Decided 2026-09-18. Two facts were missing from the estate model:
--
--   1. CONTROL — is this location under the system's control, i.e. does the host itself run the
--      Business OS? A tenant renting a VM in MaluDb hosting has an office, but no agents run
--      there unless we control the host. Agents are the thing control gates: a machine we do
--      not run is a machine we cannot put an agent on.
--   2. SITING — does this office run on a VM inside our host (onsite), or is it reached over
--      the internet (offsite)?
--
-- Control is set on the BUILDING and inherited down the parent chain; an office or desk may
-- override it. Siting is stored per location and set on the form, because the parent link does
-- not reliably tell you: the minimum platform is one office with no building recorded, and it
-- is emphatically onsite, while a parent building can belong to somebody else.
--
-- The rule lives in SQL, in one place, so a screen and an agent can never disagree about who
-- may live where — and a trigger enforces it, so it is not merely advice to the UI.

BEGIN;

ALTER TABLE locations
    ADD COLUMN control text CHECK (control IN ('managed', 'unmanaged')),
    ADD COLUMN siting  text CHECK (siting  IN ('onsite', 'offsite'));

COMMENT ON COLUMN locations.control IS
    'managed = the host runs the Business OS and may carry agents. NULL = inherit from the '
    'parent location (see location_effective_control). Buildings must state it.';
COMMENT ON COLUMN locations.siting IS
    'onsite = a VM inside our own host; offsite = reached over the internet. Offices and desks '
    'only; a building is the host and has no siting of its own.';

-- Backfill what is already here, stating the reasoning rather than guessing silently:
--  - the platform's own office is this VM, so it is onsite;
--  - a desk is someone's workstation reached over the network, so it is offsite;
--  - nothing existing is claimed as managed except by the owner, so control starts unmanaged
--    on buildings and NULL (inherit) below them. The estate screen is where it gets set.
UPDATE locations SET siting = 'onsite'  WHERE kind = 'office' AND siting IS NULL;
UPDATE locations SET siting = 'offsite' WHERE kind = 'desk'   AND siting IS NULL;
UPDATE locations SET siting = NULL      WHERE kind = 'building';
UPDATE locations SET control = 'unmanaged' WHERE kind = 'building' AND control IS NULL;

ALTER TABLE locations ADD CONSTRAINT locations_siting_by_kind CHECK (
    (kind = 'building' AND siting IS NULL) OR (kind <> 'building' AND siting IS NOT NULL)
);
-- A building is the root of a control chain, so it cannot inherit from anything.
ALTER TABLE locations ADD CONSTRAINT locations_building_states_control CHECK (
    kind <> 'building' OR control IS NOT NULL
);

-- --------------------------------------------------------------------------
-- Effective control: this location's own answer, else the nearest ancestor's.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION location_effective_control(p_location_id bigint)
RETURNS text
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE chain AS (
        SELECT id, parent_location_id, control, 0 AS depth
          FROM locations WHERE id = p_location_id
        UNION ALL
        SELECT l.id, l.parent_location_id, l.control, c.depth + 1
          FROM locations l JOIN chain c ON l.id = c.parent_location_id
         WHERE c.control IS NULL AND c.depth < 10      -- depth guard: the tree is 2 deep today
    )
    SELECT coalesce((SELECT control FROM chain WHERE control IS NOT NULL ORDER BY depth LIMIT 1),
                    'unmanaged');
$$;

COMMENT ON FUNCTION location_effective_control(bigint) IS
    'The location''s own control, else the nearest ancestor that states one, else unmanaged.';

-- --------------------------------------------------------------------------
-- The one residency rule. Screens and agents both read this; the trigger below
-- enforces it, so it is not advice.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION location_allows_resident(p_location_id bigint, p_member_kind text)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT CASE
        -- Nobody lives in a building. A building is the host; its offices and desks are where
        -- work happens, which is what the office metaphor in the requirements says.
        WHEN (SELECT kind FROM locations WHERE id = p_location_id) = 'building' THEN false
        WHEN p_member_kind = 'human' THEN true
        WHEN p_member_kind = 'agent'
            THEN location_effective_control(p_location_id) = 'managed'
        ELSE false
    END;
$$;

COMMENT ON FUNCTION location_allows_resident(bigint, text) IS
    'Who may reside at a location: humans at any office or desk; agents only where the '
    'effective control is managed, because an agent cannot run on a host we do not control.';

CREATE OR REPLACE FUNCTION location_residents_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE k text; loc text; ctl text;
BEGIN
    SELECT member_kind INTO k FROM members WHERE id = NEW.member_id;
    IF NOT location_allows_resident(NEW.location_id, k) THEN
        SELECT name INTO loc FROM locations WHERE id = NEW.location_id;
        ctl := location_effective_control(NEW.location_id);
        IF k = 'agent' THEN
            RAISE EXCEPTION
                'An agent cannot live at %: the location is % — agents need a host the system controls',
                loc, ctl;
        ELSE
            RAISE EXCEPTION 'A % cannot live at %', k, loc;
        END IF;
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER location_residents_allowed
    BEFORE INSERT OR UPDATE OF location_id, member_id ON location_residents
    FOR EACH ROW EXECUTE FUNCTION location_residents_check();

-- An office manager is an agent, so the same rule governs it.
CREATE OR REPLACE FUNCTION locations_office_manager_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.office_manager_member_id IS NOT NULL
       AND location_effective_control(NEW.id) <> 'managed' THEN
        RAISE EXCEPTION
            'An office manager is an agent, so % needs a host the system controls', NEW.name;
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER locations_office_manager_allowed
    BEFORE UPDATE OF office_manager_member_id ON locations
    FOR EACH ROW EXECUTE FUNCTION locations_office_manager_check();

-- --------------------------------------------------------------------------
-- The view carries both facts plus the derived answer, so no caller re-derives it.
-- --------------------------------------------------------------------------
-- CREATE OR REPLACE cannot insert a column mid-list, so the view is dropped and rebuilt.
-- Checked first: nothing else depends on it. Its grants are restored below, exactly as db/063
-- left them (app_rw read/write, app_records_ro read).
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
       WHERE d.home_location_id = l.id AND d.archived_at IS NULL) AS department_count
   FROM locations l
     LEFT JOIN members om ON om.id = l.owner_member_id
     LEFT JOIN locations pl ON pl.id = l.parent_location_id
  WHERE app_is_insider();

ALTER VIEW mcp_locations SET (security_barrier = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_locations TO app_rw;
GRANT SELECT ON mcp_locations TO app_records_ro;

COMMIT;
