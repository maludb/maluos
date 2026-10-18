-- 051_seed_business_defaults.sql
-- Starting data every tenant gets. Idempotent: safe to re-run.
-- *** The owner edits the business name, currency and timezone in Settings. ***
-- Not seeded here, on purpose:
--   * approval_policies — patterns must match action keys from the action manifest (1.6),
--     and the default thresholds are still an open question.
--   * model_registry — model ids and per-token prices are verified against the provider's
--     current docs when the agent runner is built (Phase 5).
--   * tax_rates — jurisdiction-specific; the owner adds them.

BEGIN;

-- Business settings: one row, name carried over from the fork's community name.
INSERT INTO business_settings (business_name, timezone)
SELECT community_name, timezone FROM community_settings LIMIT 1
ON CONFLICT (id) DO NOTHING;
INSERT INTO business_settings (business_name) VALUES ('My Business')
ON CONFLICT (id) DO NOTHING;

-- Business roles for existing members: member #1 is the first organizer (the project owner)
-- and becomes the super-admin. Everyone else starts as a plain user: a dept-admin is made
-- deliberately, by naming the departments they administer, so nobody gains administrative
-- reach by migration. Only rows still on the column default are touched, so re-running never
-- overrides a later change.
UPDATE members SET business_role = 'super_admin'
 WHERE id = 1 AND business_role = 'user' AND member_kind = 'human';

-- Document numbering.
INSERT INTO document_sequences (kind, prefix) VALUES
    ('quote',       'Q-'),
    ('invoice',     'INV-'),
    ('credit_note', 'CN-'),
    ('ticket',      'T-'),
    ('project',     'P-'),
    ('expense',     'EXP-'),
    ('journal_entry', 'JE-'),
    ('purchase_order', 'PO-'),
    ('pay_run',     'PR-')
ON CONFLICT (kind) DO NOTHING;

-- Default sales pipeline.
INSERT INTO pipelines (name, is_default) VALUES ('Sales', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO deal_stages (pipeline_id, name, stage_kind, probability, sort_order)
SELECT p.id, s.name, s.stage_kind, s.probability, s.sort_order
FROM pipelines p
CROSS JOIN (VALUES
    ('Lead',        'open',  10, 1),
    ('Qualified',   'open',  25, 2),
    ('Proposal',    'open',  50, 3),
    ('Negotiation', 'open',  75, 4),
    ('Won',         'won',  100, 5),
    ('Lost',        'lost',   0, 6)
) AS s(name, stage_kind, probability, sort_order)
WHERE p.name = 'Sales'
ON CONFLICT (pipeline_id, name) DO NOTHING;

-- Starter expense categories (flat, per the 2026-09-17 decision).
INSERT INTO expense_categories (name) VALUES
    ('Advertising & marketing'), ('AI & model usage'), ('Bank & payment fees'),
    ('Contractors'), ('Equipment'), ('Insurance'), ('Meals'), ('Office supplies'),
    ('Professional services'), ('Rent'), ('Software & subscriptions'), ('Travel'),
    ('Utilities'), ('Other')
ON CONFLICT (name) DO NOTHING;

-- Proposed default SLAs (minutes); the owner tunes these.
INSERT INTO sla_policies (name, priority, first_response_minutes, resolution_minutes)
SELECT v.name, v.priority, v.first_response, v.resolution
FROM (VALUES
    ('Urgent', 'urgent',   60,   480),
    ('High',   'high',    240,  1440),
    ('Normal', 'normal',  480,  2880),
    ('Low',    'low',    1440,  7200)
) AS v(name, priority, first_response, resolution)
WHERE NOT EXISTS (SELECT 1 FROM sla_policies sp
                   WHERE sp.priority = v.priority AND sp.department_id IS NULL
                     AND sp.archived_at IS NULL);

-- The minimum estate is ONE office: a single VM running PostgreSQL 17 + MaluDB and this
-- platform. That is what a tenant is provisioned with. Everything else is optional and
-- added by the owner as the business grows: a building above it once the host runs several
-- offices, more offices (VMs) when a department or application wants its own machine, and
-- one desk per enrolled desktop. The Office's office manager is assigned at first hire.
INSERT INTO locations (name, kind, description, presence, is_always_on, platform)
SELECT 'Office', 'office', 'The always-on server: app, record memory, activity memory, MCP services',
       'online', true, 'kvm'
WHERE NOT EXISTS (SELECT 1 FROM locations WHERE kind = 'office' AND status = 'active');

COMMIT;
