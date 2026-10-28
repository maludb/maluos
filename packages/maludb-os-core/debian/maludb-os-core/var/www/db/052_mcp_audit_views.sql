-- 052_mcp_audit_views.sql
-- Views the MCP tool surface (docs/business-os-mcp-tool-surface.md) needs beyond the
-- per-table views in 050: the approval audit on the activity side, which has to join the
-- activity stream to the approval policies inside one role's reach.
--
-- Logging convention this relies on (goes into every money/external-send build spec):
-- a state-changing action with a money amount writes after->>'amount' and
-- after->>'currency' in its activity_log row.

BEGIN;

-- AP8 / SM13: agent actions that match an active approval policy but ran without an
-- approval request. The healthy answer is always zero rows. Owner/Manager only.
CREATE OR REPLACE VIEW mcp_activity_unapproved_actions WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id AS agent_member_id, m.display_name AS agent_name,
       al.action, al.entity_type, al.entity_id, al.after, al.request_id, al.agent_run_id,
       p.id AS policy_id, p.name AS policy_name, p.category, p.amount_threshold, p.currency
FROM activity_log al
JOIN members m ON m.id = al.actor_member_id AND m.member_kind = 'agent'
JOIN approval_policies p
  ON p.active
 AND (al.action = p.action_pattern                                         -- 'invoice.send'
      OR (right(p.action_pattern, 2) = '.*'                                   -- 'refund.*'
          AND left(al.action, length(p.action_pattern) - 1) = left(p.action_pattern, -1))
      OR (left(p.action_pattern, 2) = '*.'                                    -- '*.delete'
          AND right(al.action, length(p.action_pattern) - 1) = right(p.action_pattern, -1)))
 AND (p.applies_to IN ('agents', 'everyone')
      OR (p.applies_to = 'agent' AND p.agent_member_id = al.actor_member_id)
      OR (p.applies_to = 'department' AND p.department_id = al.department_id))
 AND (p.amount_threshold IS NULL
      OR (al.after ? 'amount'
          AND (al.after->>'amount') ~ '^[0-9]+(\.[0-9]+)?$'
          AND (al.after->>'amount')::numeric > p.amount_threshold
          AND COALESCE(al.after->>'currency', p.currency) = p.currency))
WHERE al.approval_request_id IS NULL
  AND al.occurred_at >= p.created_at
  AND (app_is_super_admin()
       OR (app_is_dept_admin() AND al.department_id = ANY (app_admin_department_ids())));

GRANT SELECT ON mcp_activity_unapproved_actions TO app_activity_ro;

COMMIT;
