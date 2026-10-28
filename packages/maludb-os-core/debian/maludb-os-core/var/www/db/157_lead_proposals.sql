-- 157: proposed department leads, and the screens' places in the menu (owner-approved 2026-09-27;
-- docs/build-specs/assistants-and-messaging.md §7 and §9, build step 7).
--
-- A department with agents in it (or a standing department) and no lead orchestrator gets a PROPOSED
-- lead: an orchestrator named for it, its job drawn from the department handbook, its roster the
-- department's specialists, placed under the personal assistant whose person runs the department. The
-- proposal is a row, not an agent: a super-admin confirms it in one click (the hire happens then, logged
-- as any hire) or declines it. Nothing is hired unconfirmed. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/157_lead_proposals.sql

BEGIN;

CREATE TABLE agent_lead_proposals (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    department_id      bigint NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name               text NOT NULL,
    job_description    text NOT NULL,
    roster_member_ids  bigint[] NOT NULL DEFAULT '{}',
    parent_member_id   bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL,   -- the assistant it goes under
    model_id           bigint REFERENCES model_registry(id),
    status             text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'hired', 'declined')),
    hired_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,
    proposed_at        timestamptz NOT NULL DEFAULT now(),
    decided_by         bigint REFERENCES members(id),
    decided_at         timestamptz,
    decision_note      text
);
CREATE UNIQUE INDEX agent_lead_proposals_one_open ON agent_lead_proposals (department_id) WHERE status = 'proposed';
COMMENT ON TABLE agent_lead_proposals IS 'A lead orchestrator the OS proposes for a department that has none (db/157); hired only when a super-admin confirms.';

ALTER TABLE agent_lead_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY agent_lead_proposals_app_rw ON agent_lead_proposals TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON agent_lead_proposals TO app_rw;

-- The menu: "My assistant" for everyone (the page says so when a person has none), and "Organisation"
-- — the orchestrator tree — beside the Agent Workforce.
INSERT INTO nav_items (item_key, group_id, sort_order, label, icon, url, audience, active_patterns)
SELECT 'my_assistant', (SELECT group_id FROM nav_items WHERE item_key = 'dashboard'), 15, 'My assistant', 'feather-message-circle', '/assistant', 'internal', '{/assistant}'
 WHERE NOT EXISTS (SELECT 1 FROM nav_items WHERE item_key = 'my_assistant');
INSERT INTO nav_items (item_key, group_id, sort_order, label, icon, url, audience, active_patterns)
SELECT 'organisation', (SELECT id FROM nav_groups WHERE name = 'Human Resources'), 22, 'Organisation', 'feather-git-merge',
       '/agents/org', 'admin', '{/agents/org}'
 WHERE NOT EXISTS (SELECT 1 FROM nav_items WHERE item_key = 'organisation');

COMMIT;
