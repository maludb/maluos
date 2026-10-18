-- 149: IT, the fifth standing department (owner, 2026-09-27) — created on install, undeletable,
-- renameable: the machines, the platform and the applications on it. The Sysadmin (system_one,
-- db/145) already sits there; the application installation agent is hired there by
-- bin/hire_installation_agent.php (part of the install). An IT department a person already
-- created by hand is promoted in place — members, manager, admins and history kept; otherwise
-- one is seeded under the Front Office at its home office, as the other four are.
BEGIN;

ALTER TABLE departments DROP CONSTRAINT departments_system_key_check;
ALTER TABLE departments ADD CONSTRAINT departments_system_key_check CHECK (
    system_key IN ('front_office', 'hr', 'accounting', 'audit', 'it')
);
COMMENT ON COLUMN departments.system_key IS
    'The five standing departments every tenant has: front_office (root of the org chart), hr, accounting, audit, it. '
    'Seeded, renameable, never deleted (db/030, db/074, db/149).';

UPDATE departments
   SET is_system = true, system_key = 'it',
       description = CASE WHEN coalesce(description, '') IN ('', 'Information Technology')
                          THEN 'The machines, the platform and the applications on it — installed, integrated and watched'
                          ELSE description END,
       updated_at = now()
 WHERE id = (SELECT d.id FROM departments d
              WHERE NOT d.is_system AND d.archived_at IS NULL AND lower(d.name) IN ('it', 'information technology', 'i.t.')
              ORDER BY d.id LIMIT 1)
   AND NOT EXISTS (SELECT 1 FROM departments WHERE system_key = 'it');

INSERT INTO departments (name, description, is_system, system_key, parent_id, home_location_id)
SELECT 'IT', 'The machines, the platform and the applications on it — installed, integrated and watched',
       true, 'it', fo.id, fo.home_location_id
  FROM departments fo
 WHERE fo.system_key = 'front_office'
   AND NOT EXISTS (SELECT 1 FROM departments WHERE system_key = 'it');

-- The installation agent plans, a person approves, it applies: an agent's registration of an
-- application, its endpoints or its scopes pauses for its approver (the nearest human manager,
-- for an agent in IT the department's manager). Minting the application's token stays a person's
-- act on the application's Overview — no agent holds it.
INSERT INTO approval_policies (name, category, action_pattern, applies_to, expires_after_hours, active)
SELECT v.name, 'other', v.pattern, 'agents', 72, true
  FROM (VALUES ('Agents: registering or changing an application', 'application.*'),
               ('Agents: an application''s endpoints', 'application_endpoint.*'),
               ('Agents: an application''s scopes', 'application_scope.*')) AS v(name, pattern)
 WHERE NOT EXISTS (SELECT 1 FROM approval_policies p WHERE p.action_pattern = v.pattern AND p.applies_to = 'agents');

COMMIT;
