-- 072_agent_orchestration.sql
-- An agent is an orchestrator or a subagent, and an orchestrator has a roster.
--
-- Decided 2026-09-18. Three choices, all taken deliberately:
--
-- 1. UNIFIED with the office manager rather than sitting beside it. The requirements already
--    defined an orchestrator — "each location has exactly one office-manager agent, its
--    orchestrator: it receives task requests addressed to the location and routes them to the
--    right resident agent". Rather than add a second delegation concept, `is_office_manager`
--    now means "this orchestrator is its location's default entry point", and a CHECK makes an
--    office manager necessarily an orchestrator. Two overlapping concepts is how the same
--    action ends up behaving differently depending which door it came through.
--
-- 2. A JOIN TABLE, not a parent pointer, so one specialist subagent can serve several
--    orchestrators without being cloned — and clones drift. It is also where per-pair limits
--    (which duties may be delegated, a spend cap) will hang when the runtime needs them.
--
-- 3. ONE LEVEL, enforced. A subagent never re-delegates and an orchestrator is never someone's
--    subagent. Note what this buys: because the roster's two ends are constrained to opposite
--    kinds, a cycle is structurally impossible and no recursive cycle-check is needed. Runaway
--    delegation stops being a budget problem discovered after the fact.

BEGIN;

ALTER TABLE agent_profiles
    ADD COLUMN agent_kind text NOT NULL DEFAULT 'subagent'
        CHECK (agent_kind IN ('orchestrator', 'subagent'));

COMMENT ON COLUMN agent_profiles.agent_kind IS
    'orchestrator = may hold a roster of subagents and delegate to them; subagent = does the '
    'work and never re-delegates. Default subagent: most agents do a job rather than hand it on.';

-- An office manager orchestrates its location by definition.
ALTER TABLE agent_profiles ADD CONSTRAINT agent_office_manager_is_orchestrator CHECK (
    NOT is_office_manager OR agent_kind = 'orchestrator'
);

COMMENT ON COLUMN agent_profiles.is_office_manager IS
    'This orchestrator is its location''s default entry point: task requests addressed to the '
    'location arrive here and are routed to resident agents. Implies agent_kind = orchestrator.';

-- --------------------------------------------------------------------------
-- The roster
-- --------------------------------------------------------------------------
CREATE TABLE agent_subagents (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    orchestrator_member_id bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    subagent_member_id     bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    note                   text,
    added_by               bigint REFERENCES members(id) ON DELETE SET NULL,
    added_at               timestamptz NOT NULL DEFAULT now(),
    removed_at             timestamptz,
    CHECK (orchestrator_member_id <> subagent_member_id)
);

-- Live membership is unique; history is kept by removed_at, the same shape agent_tool_grants
-- uses for revoked_at — a roster you cannot reconstruct is a roster you cannot audit.
CREATE UNIQUE INDEX agent_subagents_live_idx
    ON agent_subagents (orchestrator_member_id, subagent_member_id) WHERE removed_at IS NULL;
CREATE INDEX agent_subagents_subagent_idx ON agent_subagents (subagent_member_id)
    WHERE removed_at IS NULL;

COMMENT ON TABLE agent_subagents IS
    'Which subagents an orchestrator may delegate to. Many-to-many on purpose: one specialist '
    'can serve several orchestrators without being duplicated.';

-- --------------------------------------------------------------------------
-- One level, enforced at both ends. This is also the whole cycle prevention:
-- the two ends must be opposite kinds, so no chain longer than one can form.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION agent_subagents_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE ok text; sk text; oname text; sname text;
BEGIN
    SELECT p.agent_kind, m.display_name INTO ok, oname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id
     WHERE p.member_id = NEW.orchestrator_member_id;
    SELECT p.agent_kind, m.display_name INTO sk, sname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id
     WHERE p.member_id = NEW.subagent_member_id;

    IF ok <> 'orchestrator' THEN
        RAISE EXCEPTION '% is a subagent, so it cannot manage other agents', coalesce(oname, 'That agent');
    END IF;
    IF sk <> 'subagent' THEN
        RAISE EXCEPTION
            '% is an orchestrator, so it cannot be managed by another one — delegation is one level deep',
            coalesce(sname, 'That agent');
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER agent_subagents_one_level
    BEFORE INSERT OR UPDATE OF orchestrator_member_id, subagent_member_id ON agent_subagents
    FOR EACH ROW EXECUTE FUNCTION agent_subagents_check();

-- Changing an agent's kind must not orphan or invalidate a live roster.
CREATE OR REPLACE FUNCTION agent_kind_change_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    IF NEW.agent_kind = OLD.agent_kind THEN
        RETURN NEW;
    END IF;
    IF OLD.agent_kind = 'orchestrator' THEN
        SELECT count(*) INTO n FROM agent_subagents
         WHERE orchestrator_member_id = NEW.member_id AND removed_at IS NULL;
        IF n > 0 THEN
            RAISE EXCEPTION
                'This orchestrator still manages % subagent(s); remove them from its roster first', n;
        END IF;
    ELSE
        SELECT count(*) INTO n FROM agent_subagents
         WHERE subagent_member_id = NEW.member_id AND removed_at IS NULL;
        IF n > 0 THEN
            RAISE EXCEPTION
                'This subagent is on % orchestrator roster(s); remove it from them first', n;
        END IF;
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER agent_profiles_kind_change
    BEFORE UPDATE OF agent_kind ON agent_profiles
    FOR EACH ROW EXECUTE FUNCTION agent_kind_change_check();

-- --------------------------------------------------------------------------
-- Read surface
-- --------------------------------------------------------------------------
CREATE VIEW mcp_agent_subagents AS
 SELECT s.id AS agent_subagent_id,
        s.orchestrator_member_id, om.display_name AS orchestrator_name,
        s.subagent_member_id,     sm.display_name AS subagent_name,
        sp.status AS subagent_status, sp.role_key AS subagent_role_key,
        s.note, s.added_by, s.added_at, s.removed_at
   FROM agent_subagents s
   JOIN members om ON om.id = s.orchestrator_member_id
   JOIN members sm ON sm.id = s.subagent_member_id
   JOIN agent_profiles sp ON sp.member_id = s.subagent_member_id
  WHERE app_is_insider();

ALTER VIEW mcp_agent_subagents SET (security_barrier = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agent_subagents TO app_rw;
GRANT SELECT ON mcp_agent_subagents TO app_records_ro;

COMMIT;
