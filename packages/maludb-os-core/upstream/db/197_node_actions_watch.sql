-- 197: node actions for the watching agents (MaluOS Phase 14 slice 4d; maluos docs/phase14-watching-agents.md).
--
-- Three more verbs a node may run for the office, each a fixed verb with checked arguments, each only if the node's
-- own actions.allow permits it: restart_unit (a unit from the node's own list), postgres_cancel and
-- postgres_terminate (one backend by pid, as the node's monitoring role). An action carries its arguments in
-- `args`. Until now only an operator's desk queued an action; now a super-admin or an agent may ask through the
-- kernel action estate_node_action (html/estate/node-action.php), and an agent's request pauses for its approver:
-- the policy below. Additive.

ALTER TABLE estate_actions DROP CONSTRAINT estate_actions_action_check;
ALTER TABLE estate_actions ADD CONSTRAINT estate_actions_action_check
    CHECK (action IN ('restart_agent', 'start_agent', 'stop_agent', 'apply_updates', 'reboot',
                      'restart_unit', 'postgres_cancel', 'postgres_terminate'));
ALTER TABLE estate_actions ADD COLUMN args jsonb;
COMMENT ON COLUMN estate_actions.args IS
    'The action''s arguments (db/197): {"unit": "apache2.service"} for restart_unit, {"pid": 4242} for postgres_cancel and postgres_terminate; NULL for the others.';
ALTER TABLE estate_actions ADD COLUMN approval_request_id bigint;
COMMENT ON COLUMN estate_actions.approval_request_id IS
    'The approval that let an agent''s request through (db/197); NULL for an operator''s or a super-admin''s own action.';

INSERT INTO approval_policies (name, category, action_pattern, applies_to, expires_after_hours, active)
SELECT 'Agents: an action on a node of the estate', 'other', 'estate.node_action', 'agents', 24, true
 WHERE NOT EXISTS (SELECT 1 FROM approval_policies p WHERE p.action_pattern = 'estate.node_action' AND p.applies_to = 'agents');
