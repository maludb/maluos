-- 132: depreciation of assets, posted to the books ON DEMAND by a person — never automatically
-- (docs/build-specs/assets.md, "Depreciation"; the owner's decision 3, 2026-09-21).
--
-- Straight line: (purchase_cost - salvage_value) over useful_life_months, from the month of
-- purchase. Posting a month brings every asset up to what it should have accumulated by the end of
-- that month, so a register begun late catches up in one entry and a month posted twice posts
-- nothing. One journal entry per currency: debit 6600 Depreciation (a line per department),
-- credit 1510 Accumulated depreciation.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/132_asset_depreciation.sql

BEGIN;

INSERT INTO gl_accounts (code, name, account_type, subtype, is_system, description) VALUES
    ('1510', 'Accumulated depreciation', 'asset',   'fixed', true, 'Contra to 1500 Fixed assets: what the assets have lost in value so far'),
    ('6600', 'Depreciation',             'expense', NULL,    true, 'The period''s share of what the assets cost')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE journal_entries DROP CONSTRAINT journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check CHECK (source = ANY (ARRAY[
    'manual', 'invoice', 'payment', 'credit_note', 'expense', 'ai_usage', 'payroll', 'inventory', 'bank',
    'opening', 'closing', 'depreciation']));

CREATE TABLE asset_depreciation (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id          bigint NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    period_month      date NOT NULL CHECK (period_month = date_trunc('month', period_month)::date),
    amount            numeric(14,2) NOT NULL CHECK (amount > 0),
    currency          char(3) NOT NULL,
    journal_entry_id  bigint NOT NULL REFERENCES journal_entries(id) ON DELETE RESTRICT,
    posted_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (asset_id, period_month)
);
CREATE INDEX asset_depreciation_entry_idx  ON asset_depreciation (journal_entry_id);
CREATE INDEX asset_depreciation_month_idx  ON asset_depreciation (period_month);
CREATE INDEX asset_depreciation_by_idx     ON asset_depreciation (posted_by);

ALTER TABLE asset_depreciation ENABLE ROW LEVEL SECURITY;
CREATE POLICY asset_depreciation_app_rw ON asset_depreciation FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT ON asset_depreciation TO app_rw;

-- Money: only for whoever may manage the asset.
CREATE VIEW mcp_asset_depreciation WITH (security_barrier = true) AS
 SELECT d.id AS asset_depreciation_id, d.asset_id, a.asset_tag, a.name AS asset_name, d.period_month, d.amount,
        d.currency, d.journal_entry_id, je.entry_no, d.posted_by, m.display_name AS posted_by_name, d.created_at
   FROM asset_depreciation d
   JOIN assets a ON a.id = d.asset_id
   JOIN journal_entries je ON je.id = d.journal_entry_id
   LEFT JOIN members m ON m.id = d.posted_by
  WHERE app_can_manage_asset(a.department_id);
GRANT SELECT ON mcp_asset_depreciation TO app_rw, app_records_ro;

-- Posting to the ledger is an agent's to ask, a person's to approve.
INSERT INTO approval_policies (name, category, action_pattern, applies_to)
VALUES ('Agents: posting depreciation', 'other', 'asset_depreciation.post', 'agents');

COMMIT;
