-- 154: personal assistants and the orchestrator tree (owner-approved 2026-09-27;
-- docs/build-specs/assistants-and-messaging.md, build steps 1 and 2).
--
-- db/072 made delegation ONE level deep: the two ends of a roster row had to be opposite kinds, which
-- was also its cycle prevention. The owner reversed it: a person's assistant orchestrates department
-- leads, and in a large organisation assistants sit over assistants. So an orchestrator may now hold
-- ORCHESTRATORS as well as subagents, under three rules that keep the old guarantees:
--   * an orchestrator has at most ONE live parent (a subagent — a leaf — may still serve several
--     orchestrators, as db/072 intended; leaves cannot make a cycle);
--   * no cycles — the parent may not be among the child's descendants;
--   * depth at most 5 levels, counting the specialist at the bottom.
-- A PERSONAL ASSISTANT is an orchestrator with a principal: the one person it serves and the only
-- person it talks to. Its reach is its person's (app_agent_reach_department_ids()). Every delegation
-- records where it went and why (agent_runs.delegated_department_id, delegation_reason). Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/154_assistant_tree.sql

BEGIN;

-- 1. The principal -------------------------------------------------------------------------------------

ALTER TABLE agent_profiles ADD COLUMN principal_member_id bigint REFERENCES members(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX agent_profiles_one_assistant_per_person ON agent_profiles (principal_member_id)
    WHERE principal_member_id IS NOT NULL AND status <> 'offboarded';
COMMENT ON COLUMN agent_profiles.principal_member_id IS
    'The person this agent is the personal assistant of (db/154): the only agent that talks to them, and never reaching further than they can. NULL for every other agent.';

CREATE FUNCTION agent_principal_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k text; s text;
BEGIN
    IF NEW.principal_member_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.agent_kind <> 'orchestrator' THEN
        RAISE EXCEPTION 'A personal assistant is an orchestrator — make this agent an orchestrator first';
    END IF;
    SELECT member_kind, status INTO k, s FROM members WHERE id = NEW.principal_member_id;
    IF k IS DISTINCT FROM 'human' THEN
        RAISE EXCEPTION 'An assistant serves a person, not an agent';
    END IF;
    IF s IS DISTINCT FROM 'active' AND (TG_OP = 'INSERT' OR NEW.principal_member_id IS DISTINCT FROM OLD.principal_member_id) THEN
        RAISE EXCEPTION 'That person is not active';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER agent_profiles_principal_check BEFORE INSERT OR UPDATE OF principal_member_id, agent_kind ON agent_profiles
    FOR EACH ROW EXECUTE FUNCTION agent_principal_check();

-- 2. The tree ---------------------------------------------------------------------------------------------

-- The live parent orchestrator of an ORCHESTRATOR (at most one), or NULL.
CREATE FUNCTION agent_parent_orchestrator(p_agent bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT s.orchestrator_member_id FROM agent_subagents s
      JOIN agent_profiles c ON c.member_id = s.subagent_member_id AND c.agent_kind = 'orchestrator'
     WHERE s.subagent_member_id = p_agent AND s.removed_at IS NULL
     LIMIT 1;
$$;

-- How many levels sit at and below this agent (a subagent: 1; an orchestrator: 1 + its deepest child).
CREATE FUNCTION agent_subtree_height(p_agent bigint) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH RECURSIVE down(member_id, lvl) AS (
        SELECT p_agent, 1
        UNION ALL
        SELECT s.subagent_member_id, d.lvl + 1 FROM agent_subagents s JOIN down d ON s.orchestrator_member_id = d.member_id
         WHERE s.removed_at IS NULL AND d.lvl < 10
    )
    SELECT max(lvl) FROM down;
$$;

-- How many levels sit at and above this agent (a root: 1).
CREATE FUNCTION agent_depth(p_agent bigint) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH RECURSIVE up(member_id, lvl) AS (
        SELECT p_agent, 1
        UNION ALL
        SELECT agent_parent_orchestrator(u.member_id), u.lvl + 1 FROM up u
         WHERE agent_parent_orchestrator(u.member_id) IS NOT NULL AND u.lvl < 10
    )
    SELECT max(lvl) FROM up;
$$;

CREATE OR REPLACE FUNCTION agent_subagents_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ok text; ck text; oname text; cname text; other bigint; levels integer;
BEGIN
    IF NEW.removed_at IS NOT NULL THEN
        RETURN NEW;                                  -- removing a row never breaks the tree
    END IF;
    SELECT p.agent_kind, m.display_name INTO ok, oname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id WHERE p.member_id = NEW.orchestrator_member_id;
    SELECT p.agent_kind, m.display_name INTO ck, cname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id WHERE p.member_id = NEW.subagent_member_id;
    IF ok <> 'orchestrator' THEN
        RAISE EXCEPTION '% is a subagent, so it cannot manage other agents', coalesce(oname, 'That agent');
    END IF;
    IF ck = 'orchestrator' THEN
        SELECT s.orchestrator_member_id INTO other FROM agent_subagents s
         WHERE s.subagent_member_id = NEW.subagent_member_id AND s.removed_at IS NULL
           AND s.id IS DISTINCT FROM NEW.id LIMIT 1;
        IF other IS NOT NULL THEN
            RAISE EXCEPTION '% already reports to another orchestrator — an orchestrator has one parent', coalesce(cname, 'That agent');
        END IF;
        -- No cycle: the new parent may not be the child or sit anywhere below it.
        IF NEW.orchestrator_member_id = NEW.subagent_member_id OR EXISTS (
            WITH RECURSIVE down(member_id, lvl) AS (
                SELECT NEW.subagent_member_id, 1
                UNION ALL
                SELECT s.subagent_member_id, d.lvl + 1 FROM agent_subagents s JOIN down d ON s.orchestrator_member_id = d.member_id
                 WHERE s.removed_at IS NULL AND d.lvl < 10)
            SELECT 1 FROM down WHERE member_id = NEW.orchestrator_member_id) THEN
            RAISE EXCEPTION '% already sits above %, so it cannot also sit below it', coalesce(cname, 'That agent'), coalesce(oname, 'that orchestrator');
        END IF;
    END IF;
    levels := agent_depth(NEW.orchestrator_member_id) + agent_subtree_height(NEW.subagent_member_id);
    IF levels > 5 THEN
        RAISE EXCEPTION 'That would make a chain of % levels — the tree is at most 5 deep', levels;
    END IF;
    RETURN NEW;
END$$;

-- Changing an agent's kind must not orphan or invalidate the tree.
CREATE OR REPLACE FUNCTION agent_kind_change_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    IF NEW.agent_kind = OLD.agent_kind THEN
        RETURN NEW;
    END IF;
    IF OLD.agent_kind = 'orchestrator' THEN
        SELECT count(*) INTO n FROM agent_subagents WHERE orchestrator_member_id = NEW.member_id AND removed_at IS NULL;
        IF n > 0 THEN
            RAISE EXCEPTION 'This orchestrator still manages % agent(s); remove them from its roster first', n;
        END IF;
    ELSE
        -- A subagent becoming an orchestrator: it may keep ONE parent (the tree's rule), not several.
        SELECT count(*) INTO n FROM agent_subagents WHERE subagent_member_id = NEW.member_id AND removed_at IS NULL;
        IF n > 1 THEN
            RAISE EXCEPTION 'This subagent serves % orchestrators; an orchestrator has one parent — remove it from all but one first', n;
        END IF;
    END IF;
    RETURN NEW;
END$$;

-- 3. Reach: an assistant never reaches further than its person ---------------------------------------------

-- The departments an agent may hand work into: its principal's — every department for a super-admin,
-- else the ones the person administers or manages. NULL = the agent has no principal (no reach rule).
CREATE FUNCTION app_agent_reach_department_ids(p_agent bigint) RETURNS bigint[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT CASE
        WHEN p.principal_member_id IS NULL THEN NULL
        WHEN m.business_role = 'super_admin' AND m.status = 'active' THEN (SELECT array_agg(id) FROM departments)
        ELSE (SELECT coalesce(array_agg(DISTINCT d), '{}') FROM (
                SELECT dm.department_id AS d FROM department_members dm
                 WHERE dm.member_id = p.principal_member_id AND dm.is_admin AND dm.left_at IS NULL
                UNION SELECT id FROM departments WHERE manager_member_id = p.principal_member_id AND archived_at IS NULL) x)
    END
      FROM agent_profiles p LEFT JOIN members m ON m.id = p.principal_member_id
     WHERE p.member_id = p_agent;
$$;

GRANT EXECUTE ON FUNCTION agent_parent_orchestrator(bigint), agent_subtree_height(bigint), agent_depth(bigint),
    app_agent_reach_department_ids(bigint) TO app_rw, app_records_ro, app_runner;

-- 4. Routing records -------------------------------------------------------------------------------------

ALTER TABLE agent_runs ADD COLUMN delegated_department_id bigint REFERENCES departments(id) ON DELETE SET NULL;
ALTER TABLE agent_runs ADD COLUMN delegation_reason text CHECK (delegation_reason IS NULL OR length(delegation_reason) <= 2000);
COMMENT ON COLUMN agent_runs.delegation_reason IS 'Why the delegating orchestrator chose this agent (db/154) — required of a personal assistant.';

COMMIT;
