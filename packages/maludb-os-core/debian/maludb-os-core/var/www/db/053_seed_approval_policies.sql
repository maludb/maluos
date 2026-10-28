-- 053_seed_approval_policies.sql
-- Proposed default approval policies for AI agents, matching the action manifest
-- (docs/business-os-action-manifest.md). The requirements' open question on thresholds is
-- still open: these are the proposed defaults (money out, deletions, external sends),
-- active from the start because no agent is hired yet, and editable in Settings.
--
-- action_pattern matches the activity log event of a manifest action ('entity.verb'):
-- an exact event, 'entity.*', or '*.verb'. Amount thresholds compare after->>'amount'.
-- Idempotent: a policy is inserted only if no policy with the same name exists.

BEGIN;

INSERT INTO approval_policies (name, category, action_pattern, applies_to, amount_threshold, currency)
SELECT v.name, v.category, v.pattern, 'agents', v.threshold,
       CASE WHEN v.threshold IS NOT NULL THEN (SELECT base_currency FROM business_settings) END
FROM (VALUES
    -- Money out
    ('Agents: any refund',                 'money_out',     'refund.create',            NULL::numeric),
    ('Agents: any credit note',            'money_out',     'credit_note.issue',        NULL),
    ('Agents: any write-off',              'money_out',     'invoice.write_off',        NULL),
    ('Agents: marking a bill paid',        'money_out',     'expense.mark_paid',        NULL),
    ('Agents: expenses over 250',          'money_out',     'expense.create',           250),
    ('Agents: recurring expenses',         'money_out',     'recurring_expense.create', NULL),
    -- Deletions
    ('Agents: any deletion',               'deletion',      '*.delete',                 NULL),
    ('Agents: voiding an invoice',         'deletion',      'invoice.void',             NULL),
    -- External sends
    ('Agents: sending an invoice',         'external_send', 'invoice.send',             NULL),
    ('Agents: invoice reminders',          'external_send', 'invoice.send_reminder',    NULL),
    ('Agents: sending a quote',            'external_send', 'quote.send',               NULL),
    ('Agents: sending a statement',        'external_send', 'statement.send',           NULL),
    ('Agents: payment links',              'external_send', 'payment_link.create',      NULL),
    ('Agents: publishing content',         'external_send', 'content_variant.publish',  NULL),
    ('Agents: scheduling content',         'external_send', 'content_variant.schedule', NULL),
    ('Agents: customer ticket replies',    'external_send', 'ticket.reply',             NULL),
    ('Agents: sharing with outsiders',     'external_send', 'record_share.create',      NULL),
    ('Agents: invitations',                'external_send', 'invitation.send',          NULL)
) AS v(name, category, pattern, threshold)
WHERE NOT EXISTS (SELECT 1 FROM approval_policies p WHERE p.name = v.name);

COMMIT;
