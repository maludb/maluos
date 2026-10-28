-- 056_general_ledger.sql
-- Bookkeeping proper, for the Accounting department: a chart of accounts, fiscal periods,
-- double-entry journal entries, bank accounts with imported transactions and
-- reconciliation, and the posting rules that turn invoices, payments, expenses, AI usage,
-- payroll and stock movements into journal entries.
--
-- The subledgers stay where they are (invoices, payments, expenses, prompt ledger); this is
-- the general ledger they roll into. Statutory filing is out of scope: the books are kept
-- here, the accountant files from them.
-- Questions: GL1-GL14. Module grant: 'books'.

BEGIN;

CREATE TABLE gl_accounts (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           text NOT NULL UNIQUE,                      -- '1200'
    name           text NOT NULL,
    account_type   text NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity',
                                                         'income', 'expense')),
    subtype        text,                                      -- 'bank', 'receivable', 'payable', 'cogs'
    parent_id      bigint REFERENCES gl_accounts(id) ON DELETE RESTRICT,
    currency       char(3),                                   -- null = the base currency
    is_bank        boolean NOT NULL DEFAULT false,
    is_system      boolean NOT NULL DEFAULT false,            -- seeded; renameable, not deletable
    description    text,
    archived_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gl_accounts_type_idx   ON gl_accounts (account_type) WHERE archived_at IS NULL;
CREATE INDEX gl_accounts_parent_idx ON gl_accounts (parent_id);

CREATE TABLE fiscal_periods (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,                        -- '2026-09'
    start_date   date NOT NULL,
    end_date     date NOT NULL,
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'locked')),
    closed_at    timestamptz,
    closed_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    EXCLUDE USING gist (daterange(start_date, end_date, '[]') WITH &&)
);
CREATE INDEX fiscal_periods_range_idx ON fiscal_periods (start_date, end_date);
CREATE INDEX fiscal_periods_closed_by_idx ON fiscal_periods (closed_by);

CREATE TABLE journal_entries (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_no           text UNIQUE,                            -- next_document_number('journal_entry')
    entry_date         date NOT NULL,
    period_id          bigint REFERENCES fiscal_periods(id) ON DELETE RESTRICT,
    memo               text,
    source             text NOT NULL DEFAULT 'manual'
                           CHECK (source IN ('manual', 'invoice', 'payment', 'credit_note',
                                             'expense', 'ai_usage', 'payroll', 'inventory',
                                             'bank', 'opening', 'closing')),
    source_entity_type text,
    source_entity_id   bigint,
    department_id      bigint REFERENCES departments(id) ON DELETE SET NULL,
    currency           char(3) NOT NULL DEFAULT 'USD',
    total_debit        numeric(16,2) NOT NULL DEFAULT 0 CHECK (total_debit >= 0),
    total_credit       numeric(16,2) NOT NULL DEFAULT 0 CHECK (total_credit >= 0),
    status             text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'posted', 'void')),
    posted_at          timestamptz,
    posted_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    reverses_entry_id  bigint REFERENCES journal_entries(id) ON DELETE SET NULL,
    created_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX journal_entries_date_idx    ON journal_entries (entry_date DESC);
CREATE INDEX journal_entries_period_idx  ON journal_entries (period_id, status);
CREATE INDEX journal_entries_source_idx  ON journal_entries (source, source_entity_type, source_entity_id);
CREATE INDEX journal_entries_dept_idx    ON journal_entries (department_id);
CREATE INDEX journal_entries_reverse_idx ON journal_entries (reverses_entry_id);
CREATE INDEX journal_entries_posted_by_idx ON journal_entries (posted_by);
CREATE INDEX journal_entries_created_by_idx ON journal_entries (created_by);

CREATE TABLE journal_lines (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id        bigint NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    line_no         integer NOT NULL,
    account_id      bigint NOT NULL REFERENCES gl_accounts(id) ON DELETE RESTRICT,
    description     text,
    debit           numeric(16,2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit          numeric(16,2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    department_id   bigint REFERENCES departments(id) ON DELETE SET NULL,
    organization_id bigint REFERENCES organizations(id) ON DELETE SET NULL,   -- counterparty
    project_id      bigint REFERENCES projects(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entry_id, line_no),
    CHECK ((debit > 0) <> (credit > 0))                       -- exactly one side per line
);
CREATE INDEX journal_lines_account_idx ON journal_lines (account_id);
CREATE INDEX journal_lines_org_idx     ON journal_lines (organization_id);
CREATE INDEX journal_lines_project_idx ON journal_lines (project_id);
CREATE INDEX journal_lines_dept_idx    ON journal_lines (department_id);

-- An entry may only be posted when it balances and its period is open (GL5, GL13).
CREATE OR REPLACE FUNCTION gl_check_posting() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE d numeric(16,2); c numeric(16,2); p text;
BEGIN
    IF NEW.status = 'posted' AND OLD.status IS DISTINCT FROM 'posted' THEN
        SELECT coalesce(sum(debit), 0), coalesce(sum(credit), 0)
          INTO d, c FROM journal_lines WHERE entry_id = NEW.id;
        IF d = 0 AND c = 0 THEN
            RAISE EXCEPTION 'Journal entry % has no lines', coalesce(NEW.entry_no, NEW.id::text);
        END IF;
        IF d <> c THEN
            RAISE EXCEPTION 'Journal entry % does not balance: debits %, credits %',
                coalesce(NEW.entry_no, NEW.id::text), d, c;
        END IF;
        SELECT status INTO p FROM fiscal_periods WHERE id = NEW.period_id;
        IF p IS NOT NULL AND p <> 'open' THEN
            RAISE EXCEPTION 'Period for entry % is %, not open', coalesce(NEW.entry_no, NEW.id::text), p;
        END IF;
        NEW.total_debit := d;
        NEW.total_credit := c;
        NEW.posted_at := coalesce(NEW.posted_at, now());
    END IF;
    IF OLD.status = 'posted' AND NEW.status = 'draft' THEN
        RAISE EXCEPTION 'A posted entry cannot return to draft; reverse it instead';
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER journal_entries_check_posting
    BEFORE UPDATE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION gl_check_posting();

-- Lines never change once the entry is posted (GL13).
CREATE OR REPLACE FUNCTION gl_lines_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
    SELECT status INTO s FROM journal_entries
     WHERE id = coalesce(NEW.entry_id, OLD.entry_id);
    IF s = 'posted' THEN
        RAISE EXCEPTION 'Lines of a posted journal entry cannot be changed';
    END IF;
    RETURN coalesce(NEW, OLD);
END$$;

CREATE TRIGGER journal_lines_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION gl_lines_immutable();

-- What posts where. One row per source and match key; the app reads these when it books a
-- document, so an owner can re-map without a code change (GL9).
CREATE TABLE gl_posting_rules (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source            text NOT NULL CHECK (source IN ('invoice', 'payment', 'credit_note',
                                                      'expense', 'ai_usage', 'payroll',
                                                      'inventory', 'bank_fee')),
    match_key         text,                                   -- category id, product kind, null = default
    debit_account_id  bigint REFERENCES gl_accounts(id) ON DELETE RESTRICT,
    credit_account_id bigint REFERENCES gl_accounts(id) ON DELETE RESTRICT,
    note              text,
    active            boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, match_key)
);
CREATE INDEX gl_posting_rules_debit_idx  ON gl_posting_rules (debit_account_id);
CREATE INDEX gl_posting_rules_credit_idx ON gl_posting_rules (credit_account_id);

CREATE TABLE bank_accounts (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              text NOT NULL UNIQUE,
    gl_account_id     bigint NOT NULL REFERENCES gl_accounts(id) ON DELETE RESTRICT,
    institution       text,
    account_last4     text,
    currency          char(3) NOT NULL DEFAULT 'USD',
    kind              text NOT NULL DEFAULT 'checking'
                          CHECK (kind IN ('checking', 'savings', 'credit_card', 'cash', 'other')),
    opening_balance   numeric(16,2) NOT NULL DEFAULT 0,
    opening_date      date,
    feed_provider     text,                                   -- null = file import only
    feed_secret_id    bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    last_synced_at    timestamptz,
    is_active         boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bank_accounts_gl_idx     ON bank_accounts (gl_account_id);
CREATE INDEX bank_accounts_secret_idx ON bank_accounts (feed_secret_id);

CREATE TABLE bank_transactions (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id     bigint NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    txn_date            date NOT NULL,
    description         text NOT NULL,
    counterparty        text,
    amount              numeric(16,2) NOT NULL,                -- signed: + in, - out
    currency            char(3) NOT NULL DEFAULT 'USD',
    balance_after       numeric(16,2),
    external_ref        text,                                  -- bank's own id
    import_batch        text,
    status              text NOT NULL DEFAULT 'unmatched'
                            CHECK (status IN ('unmatched', 'matched', 'ignored')),
    matched_payment_id  bigint REFERENCES payments(id) ON DELETE SET NULL,
    matched_expense_id  bigint REFERENCES expenses(id) ON DELETE SET NULL,
    matched_entry_id    bigint REFERENCES journal_entries(id) ON DELETE SET NULL,
    matched_at          timestamptz,
    matched_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    imported_at         timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX bank_transactions_external_idx
    ON bank_transactions (bank_account_id, external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX bank_transactions_open_idx    ON bank_transactions (bank_account_id, txn_date DESC)
    WHERE status = 'unmatched';
CREATE INDEX bank_transactions_payment_idx ON bank_transactions (matched_payment_id);
CREATE INDEX bank_transactions_expense_idx ON bank_transactions (matched_expense_id);
CREATE INDEX bank_transactions_entry_idx   ON bank_transactions (matched_entry_id);
CREATE INDEX bank_transactions_matched_by_idx ON bank_transactions (matched_by);

CREATE TABLE bank_reconciliations (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_account_id    bigint NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    period_start       date NOT NULL,
    period_end         date NOT NULL,
    statement_balance  numeric(16,2) NOT NULL,
    cleared_balance    numeric(16,2) NOT NULL DEFAULT 0,
    difference         numeric(16,2) NOT NULL DEFAULT 0,
    status             text NOT NULL DEFAULT 'in_progress'
                           CHECK (status IN ('in_progress', 'completed', 'abandoned')),
    completed_at       timestamptz,
    completed_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    note               text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);
CREATE INDEX bank_reconciliations_account_idx ON bank_reconciliations (bank_account_id, period_end DESC);
CREATE INDEX bank_reconciliations_by_idx ON bank_reconciliations (completed_by);

-- Link the AI spend posting to the journal entry it produced (E15 reconciles end to end).
ALTER TABLE ai_usage_postings
    ADD COLUMN journal_entry_id bigint REFERENCES journal_entries(id) ON DELETE SET NULL;
CREATE INDEX ai_usage_postings_entry_idx ON ai_usage_postings (journal_entry_id);

-- RLS + updated_at, as in 049.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['gl_accounts', 'fiscal_periods', 'journal_entries', 'journal_lines',
                             'gl_posting_rules', 'bank_accounts', 'bank_transactions',
                             'bank_reconciliations'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['gl_accounts', 'fiscal_periods', 'journal_entries',
                             'gl_posting_rules', 'bank_accounts', 'bank_transactions',
                             'bank_reconciliations'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- Read views. The books are a whole-business record: Owner, Manager, anyone holding 'books'
-- (the bookkeeper), and the external accountant see them; no department narrowing, because
-- a trial balance with rows missing is worse than none.
CREATE OR REPLACE FUNCTION app_can_see_books() RETURNS boolean
    LANGUAGE sql STABLE AS $$ SELECT app_has_module('books'); $$;
GRANT EXECUTE ON FUNCTION app_can_see_books() TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_gl_accounts WITH (security_barrier = true) AS
SELECT id AS gl_account_id, code, name, account_type, subtype, parent_id, currency,
       is_bank, is_system, description, archived_at
FROM gl_accounts WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_fiscal_periods WITH (security_barrier = true) AS
SELECT id AS fiscal_period_id, name, start_date, end_date, status, closed_at, closed_by
FROM fiscal_periods WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_journal_entries WITH (security_barrier = true) AS
SELECT e.id AS journal_entry_id, e.entry_no, e.entry_date, e.period_id, p.name AS period_name,
       e.memo, e.source, e.source_entity_type, e.source_entity_id, e.department_id,
       d.name::text AS department_name, e.currency, e.total_debit, e.total_credit, e.status,
       e.posted_at, e.posted_by, e.reverses_entry_id, e.created_by, e.created_at
FROM journal_entries e
LEFT JOIN fiscal_periods p ON p.id = e.period_id
LEFT JOIN departments d    ON d.id = e.department_id
WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_journal_lines WITH (security_barrier = true) AS
SELECT l.id AS journal_line_id, l.entry_id, e.entry_no, e.entry_date, e.status AS entry_status,
       l.line_no, l.account_id, a.code AS account_code, a.name AS account_name, a.account_type,
       l.description, l.debit, l.credit, l.department_id, l.organization_id, l.project_id
FROM journal_lines l
JOIN journal_entries e ON e.id = l.entry_id
JOIN gl_accounts a     ON a.id = l.account_id
WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_gl_posting_rules WITH (security_barrier = true) AS
SELECT r.id AS gl_posting_rule_id, r.source, r.match_key, r.debit_account_id,
       da.code AS debit_account_code, r.credit_account_id, ca.code AS credit_account_code,
       r.note, r.active
FROM gl_posting_rules r
LEFT JOIN gl_accounts da ON da.id = r.debit_account_id
LEFT JOIN gl_accounts ca ON ca.id = r.credit_account_id
WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_bank_accounts WITH (security_barrier = true) AS
SELECT b.id AS bank_account_id, b.name, b.gl_account_id, g.code AS gl_account_code,
       b.institution, b.account_last4, b.currency, b.kind, b.opening_balance, b.opening_date,
       b.feed_provider, (b.feed_secret_id IS NOT NULL) AS has_feed_credential,
       b.last_synced_at, b.is_active
FROM bank_accounts b JOIN gl_accounts g ON g.id = b.gl_account_id
WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_bank_transactions WITH (security_barrier = true) AS
SELECT t.id AS bank_transaction_id, t.bank_account_id, b.name AS bank_account_name,
       t.txn_date, t.description, t.counterparty, t.amount, t.currency, t.balance_after,
       t.status, t.matched_payment_id, t.matched_expense_id, t.matched_entry_id,
       t.matched_at, t.matched_by, t.imported_at
FROM bank_transactions t JOIN bank_accounts b ON b.id = t.bank_account_id
WHERE app_can_see_books();

CREATE OR REPLACE VIEW mcp_bank_reconciliations WITH (security_barrier = true) AS
SELECT r.id AS bank_reconciliation_id, r.bank_account_id, b.name AS bank_account_name,
       r.period_start, r.period_end, r.statement_balance, r.cleared_balance, r.difference,
       r.status, r.completed_at, r.completed_by, r.note
FROM bank_reconciliations r JOIN bank_accounts b ON b.id = r.bank_account_id
WHERE app_can_see_books();

GRANT SELECT ON mcp_gl_accounts, mcp_fiscal_periods, mcp_journal_entries, mcp_journal_lines,
    mcp_gl_posting_rules, mcp_bank_accounts, mcp_bank_transactions, mcp_bank_reconciliations
TO app_records_ro;

-- Starter chart of accounts for a small service business. Renameable, not deletable.
INSERT INTO gl_accounts (code, name, account_type, subtype, is_bank, is_system) VALUES
    ('1000', 'Cash on hand',           'asset',     'cash',       false, true),
    ('1010', 'Business checking',      'asset',     'bank',       true,  true),
    ('1200', 'Accounts receivable',    'asset',     'receivable', false, true),
    ('1400', 'Inventory',              'asset',     'inventory',  false, true),
    ('1500', 'Fixed assets',           'asset',     'fixed',      false, true),
    ('2000', 'Accounts payable',       'liability', 'payable',    false, true),
    ('2100', 'Sales tax payable',      'liability', 'tax',        false, true),
    ('2200', 'Payroll liabilities',    'liability', 'payroll',    false, true),
    ('3000', 'Owner equity',           'equity',    NULL,         false, true),
    ('3900', 'Retained earnings',      'equity',    'retained',   false, true),
    ('4000', 'Sales revenue',          'income',    NULL,         false, true),
    ('4100', 'Service revenue',        'income',    NULL,         false, true),
    ('5000', 'Cost of goods sold',     'expense',   'cogs',       false, true),
    ('6000', 'Salaries and wages',     'expense',   'payroll',    false, true),
    ('6050', 'AI and model usage',     'expense',   NULL,         false, true),
    ('6100', 'Rent',                   'expense',   NULL,         false, true),
    ('6200', 'Software and subscriptions', 'expense', NULL,       false, true),
    ('6300', 'Professional services',  'expense',   NULL,         false, true),
    ('6400', 'Advertising and marketing', 'expense', NULL,        false, true),
    ('6500', 'Bank and payment fees',  'expense',   NULL,         false, true),
    ('6900', 'Other expenses',         'expense',   NULL,         false, true)
ON CONFLICT (code) DO NOTHING;

-- Default posting rules: the minimum set that books the documents we already have.
INSERT INTO gl_posting_rules (source, match_key, debit_account_id, credit_account_id, note)
SELECT v.source, v.match_key,
       (SELECT id FROM gl_accounts WHERE code = v.debit),
       (SELECT id FROM gl_accounts WHERE code = v.credit), v.note
FROM (VALUES
    ('invoice',  NULL, '1200', '4100', 'Invoice issued: receivable against service revenue'),
    ('payment',  NULL, '1010', '1200', 'Payment received: bank against receivable'),
    ('credit_note', NULL, '4100', '1200', 'Credit note: revenue reversed'),
    ('expense',  NULL, '6900', '2000', 'Expense recorded: cost against payable'),
    ('ai_usage', NULL, '6050', '2000', 'AI usage posted for the period'),
    ('bank_fee', NULL, '6500', '1010', 'Bank or payment-provider fee'),
    ('payroll',  NULL, '6000', '2200', 'Pay run: wages against payroll liabilities'),
    ('inventory', NULL, '5000', '1400', 'Stock sold: cost of goods sold against inventory')
) AS v(source, match_key, debit, credit, note)
WHERE NOT EXISTS (SELECT 1 FROM gl_posting_rules r
                   WHERE r.source = v.source AND r.match_key IS NOT DISTINCT FROM v.match_key);

COMMIT;
