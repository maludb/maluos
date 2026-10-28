-- 096_hired_means_active.sql
-- A hired agent is an active agent.
--
-- Decided 2026-09-18 (owner). An agent arrived as a `candidate` with its first configuration
-- version unactivated, and became `active` only when somebody found the Activate button inside
-- the Job tab. Two problems with that, in the owner's words: the second step could not be
-- found, and it should not have existed.
--
-- The eval gate was the reason for it, and the reason does not hold at hire: a version created
-- seconds ago cannot have a passing eval run against it, so the gate could only ever refuse
-- every hire, or be skipped for every hire. It keeps its real job — change control on version 2
-- and after, where there is a previous version to compare against.
--
-- `candidate` stays in the status vocabulary. It is still the honest word for an agent whose
-- activation was refused or undone, and removing a value from a CHECK would rewrite history
-- that says an agent was once a candidate.
--
-- This migration carries the agents already sitting in that status across, exactly as the
-- Activate button would have: latest version stamped activated, profile pointed at it, and an
-- `onboard` event recording that the platform did it rather than a person.

BEGIN;

WITH latest AS (
    SELECT DISTINCT ON (agent_member_id) id, agent_member_id
      FROM agent_config_versions
     ORDER BY agent_member_id, version_no DESC
)
UPDATE agent_config_versions v
   SET activated_at = coalesce(v.activated_at, now()),
       activated_by = coalesce(v.activated_by, (SELECT hired_by FROM agent_profiles p
                                                 WHERE p.member_id = v.agent_member_id))
  FROM latest l, agent_profiles p
 WHERE v.id = l.id AND p.member_id = l.agent_member_id AND p.status = 'candidate';

INSERT INTO hr_events (member_id, event_type, config_version_id, actor_member_id, note)
SELECT p.member_id, 'onboard', l.id, p.hired_by,
       'Activated by db/096: hiring now activates, and this agent was still waiting for a step that no longer exists.'
  FROM agent_profiles p
  JOIN (SELECT DISTINCT ON (agent_member_id) id, agent_member_id
          FROM agent_config_versions ORDER BY agent_member_id, version_no DESC) l
    ON l.agent_member_id = p.member_id
 WHERE p.status = 'candidate';

UPDATE agent_profiles p
   SET status = 'active',
       current_config_version_id = coalesce(
           p.current_config_version_id,
           (SELECT id FROM agent_config_versions v
             WHERE v.agent_member_id = p.member_id ORDER BY version_no DESC LIMIT 1)),
       updated_at = now()
 WHERE p.status = 'candidate';

COMMENT ON COLUMN agent_profiles.status IS
    'candidate = hired but not yet activated; active = working; suspended = paused; offboarded '
    '= finished. Since db/096 a hire lands on active directly — candidate remains for an agent '
    'whose activation was refused or undone, and for the history of those that had it.';

COMMIT;
