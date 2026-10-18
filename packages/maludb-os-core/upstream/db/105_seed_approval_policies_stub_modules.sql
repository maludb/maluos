-- 105_seed_approval_policies_stub_modules.sql
-- The action manifest marks these actions `send` or `money` — an agent must pause for a person —
-- but db/053 seeded policies only for the modules that existed then. Without a policy
-- check_approval() finds nothing to apply and an agent would send mail, approve a pay run or
-- write stock off on its own. Found by the stub-module inventory, 2026-09-19
-- (docs/build-specs/stub-modules-decisions.md, shared gap 2).
--
-- Same shape and defaults as db/053: applies to agents, 72-hour expiry, active, editable in
-- Settings. action_pattern is the activity event of the manifest action. Idempotent by name.
-- (The skill.* actions are not here on purpose: the manifest makes them "never delegable to
-- agents", which is a gate, not a policy.)

BEGIN;

INSERT INTO approval_policies (name, category, action_pattern, applies_to)
SELECT v.name, v.category, v.pattern, 'agents'
FROM (VALUES
    -- External sends
    ('Agents: sending mail from a shared mailbox', 'external_send', 'mail_message.send'),
    ('Agents: sending a signature request',        'external_send', 'signature_request.send'),
    ('Agents: signature reminders',                'external_send', 'signature_request.remind'),
    ('Agents: sending a purchase order',           'external_send', 'purchase_order.send'),
    ('Agents: scheduling a report delivery',       'external_send', 'report_schedule.save'),
    ('Agents: inviting a contact to the portal',   'external_send', 'contact.enable_portal'),
    -- Money
    ('Agents: approving a pay run',                'money_out',     'pay_run.approve'),
    ('Agents: marking a pay run paid',             'money_out',     'pay_run.pay'),
    ('Agents: changing someone''s pay',            'money_out',     'compensation_change.create'),
    ('Agents: writing stock off',                  'money_out',     'stock_movement.write_off'),
    ('Agents: posting AI usage to the books',      'money_out',     'ai_usage_posting.post'),
    ('Agents: voiding an AI usage posting',        'money_out',     'ai_usage_posting.void')
) AS v(name, category, pattern)
WHERE NOT EXISTS (SELECT 1 FROM approval_policies p WHERE p.name = v.name);

COMMIT;
