-- 094_agents_may_live_anywhere.sql
-- Control stops being a gate and goes back to being a fact.
--
-- Reversed 2026-09-18 by the owner, same day it shipped. db/067 made "agents may only live
-- where the effective control is managed" a trigger: an agent whose home was an unmanaged
-- office or desk was refused at INSERT. In use that is untenable — hiring an agent failed with
-- a Postgres exception because of how a location happened to be recorded, and the person
-- hiring could do nothing about it from the screen they were on.
--
-- What was right about the rule survives: the estate still records whether we control a host,
-- still inherits it down the tree, and the screens still show it. What goes is the refusal.
-- A business that wants an agent on a rented box is making a decision the platform records
-- rather than one it vetoes.
--
-- The building rule stays. Nobody resides in a building — it is the host, and its offices and
-- desks are where work happens — and no screen offers a building as a home, so it refuses only
-- a caller that went around the UI.

BEGIN;

-- --------------------------------------------------------------------------
-- 1. Residency: an agent may live wherever a human may.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION location_allows_resident(p_location_id bigint, p_member_kind text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT CASE
        WHEN (SELECT kind FROM locations WHERE id = p_location_id) = 'building' THEN false
        WHEN p_member_kind IN ('human', 'agent') THEN true
        ELSE false
    END;
$$;

COMMENT ON FUNCTION location_allows_resident(bigint, text) IS
    'Who may reside at a location: humans and agents at any office or desk, nobody in a '
    'building. Control is NOT part of this any more (db/094 reversed db/067): whether we run '
    'the host is recorded and shown, never enforced.';

CREATE OR REPLACE FUNCTION location_residents_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE k text; loc text;
BEGIN
    SELECT member_kind INTO k FROM members WHERE id = NEW.member_id;
    IF NOT location_allows_resident(NEW.location_id, k) THEN
        SELECT name INTO loc FROM locations WHERE id = NEW.location_id;
        RAISE EXCEPTION
            'Nobody resides in a building: % hosts offices and desks, and people and agents live in those',
            loc;
    END IF;
    RETURN NEW;
END$$;

-- --------------------------------------------------------------------------
-- 2. An office manager is an agent, so the same reversal applies: assigning one to an
--    unmanaged office is now allowed, and the trigger that refused it goes.
-- --------------------------------------------------------------------------
DROP TRIGGER IF EXISTS locations_office_manager_allowed ON locations;
DROP FUNCTION IF EXISTS locations_office_manager_check();

COMMENT ON COLUMN locations.control IS
    'managed = the system runs this host; unmanaged = it does not. Stated on a building and '
    'inherited by the offices and desks beneath it, which may override it. Since db/094 this '
    'is information the screens show, not a rule that refuses anything.';

COMMIT;
