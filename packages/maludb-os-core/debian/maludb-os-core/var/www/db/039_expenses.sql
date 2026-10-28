-- 039_expenses.sql
-- Expenses & money out. Flat categories (decided: no double-entry ledger in v1) with an
-- accountant export. Bills are expenses with a due_date and payment_status 'unpaid'.
-- Questions: E1–E13, DB1, DB3, P8, SM11. approval_request_id FK added in 044,
-- campaign_id FK in 040.

BEGIN;

CREATE TABLE expense_categories (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                citext NOT NULL UNIQUE,
    accounting_code     text,                                   -- maps to the accountant's chart
    is_billable_default boolean NOT NULL DEFAULT false,
    archived_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE recurring_expenses (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_organization_id  bigint REFERENCES organizations(id) ON DELETE SET NULL,
    category_id             bigint REFERENCES expense_categories(id) ON DELETE SET NULL,
    description             text NOT NULL,
    amount                  numeric(14,2) NOT NULL CHECK (amount > 0),
    currency                char(3) NOT NULL,
    frequency               text NOT NULL CHECK (frequency IN ('weekly', 'monthly', 'quarterly', 'yearly')),
    next_due_on             date NOT NULL,
    ends_on                 date,
    active                  boolean NOT NULL DEFAULT true,       -- E6
    department_id           bigint REFERENCES departments(id) ON DELETE SET NULL,
    created_by              bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE expenses (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number                  text NOT NULL UNIQUE,                -- next_document_number('expense')
    vendor_organization_id  bigint REFERENCES organizations(id) ON DELETE SET NULL,   -- E3
    vendor_contact_id       bigint REFERENCES contacts(id) ON DELETE SET NULL,
    category_id             bigint REFERENCES expense_categories(id) ON DELETE SET NULL,
    description             text NOT NULL,
    expense_date            date NOT NULL,
    due_date                date,                                -- E4 bills
    amount                  numeric(14,2) NOT NULL CHECK (amount > 0),   -- including tax
    tax_amount              numeric(14,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    currency                char(3) NOT NULL,
    payment_status          text NOT NULL DEFAULT 'paid'
                                CHECK (payment_status IN ('unpaid', 'scheduled', 'paid')),
    paid_on                 date,
    payment_method          text CHECK (payment_method IN ('cash', 'check', 'bank_transfer', 'card',
                                                           'online', 'reimbursement', 'other')),
    status                  text NOT NULL DEFAULT 'submitted'
                                CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'reimbursed')),
    submitted_by            bigint REFERENCES members(id) ON DELETE SET NULL,           -- E10
    approved_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    approved_at             timestamptz,
    approval_request_id     bigint,                              -- FK in 044 (agent money out)
    project_id              bigint REFERENCES projects(id) ON DELETE SET NULL,           -- E7
    task_id                 bigint REFERENCES tasks(id) ON DELETE SET NULL,
    organization_id         bigint REFERENCES organizations(id) ON DELETE SET NULL,      -- customer to rebill
    campaign_id             bigint,                              -- FK in 040 (SM11)
    billable                boolean NOT NULL DEFAULT false,
    invoice_line_id         bigint REFERENCES invoice_lines(id) ON DELETE SET NULL,      -- E8
    receipt_document_id     bigint REFERENCES documents(id) ON DELETE SET NULL,          -- E5
    recurring_expense_id    bigint REFERENCES recurring_expenses(id) ON DELETE SET NULL,
    department_id           bigint REFERENCES departments(id) ON DELETE SET NULL,
    search_tsv              tsvector,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (tax_amount <= amount)
);
CREATE INDEX expenses_date_idx        ON expenses (expense_date, category_id);        -- E1, E9
CREATE INDEX expenses_vendor_idx      ON expenses (vendor_organization_id, expense_date);
CREATE INDEX expenses_due_idx         ON expenses (due_date) WHERE payment_status <> 'paid';
CREATE INDEX expenses_no_receipt_idx  ON expenses (expense_date) WHERE receipt_document_id IS NULL;
CREATE INDEX expenses_unbilled_idx    ON expenses (organization_id) WHERE billable AND invoice_line_id IS NULL;
CREATE INDEX expenses_project_idx     ON expenses (project_id);
CREATE INDEX expenses_submitter_idx   ON expenses (submitted_by, status);
CREATE INDEX expenses_search_idx      ON expenses USING gin (search_tsv);

-- Accountant export runs (E13): what went out, for which period, pulled when.
CREATE TABLE accountant_exports (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_start      date NOT NULL,
    period_end        date NOT NULL,
    format            text NOT NULL DEFAULT 'csv' CHECK (format IN ('csv', 'xlsx')),
    includes          text[] NOT NULL DEFAULT ARRAY['invoices','payments','expenses','fees']
                          CHECK (includes <@ ARRAY['invoices','payments','expenses','fees',
                                                   'refunds','credit_notes','payouts']::text[]),
    row_counts        jsonb,
    document_id       bigint REFERENCES documents(id) ON DELETE SET NULL,
    generated_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    generated_at      timestamptz NOT NULL DEFAULT now(),
    last_downloaded_at timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);
CREATE INDEX accountant_exports_period_idx ON accountant_exports (period_start, period_end);

CREATE OR REPLACE FUNCTION expenses_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'A');
    RETURN NEW;
END$$;
CREATE TRIGGER expenses_tsv_trg BEFORE INSERT OR UPDATE OF number, description
    ON expenses FOR EACH ROW EXECUTE FUNCTION expenses_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX expenses_category_idx ON expenses (category_id);
CREATE INDEX expenses_invoice_line_idx ON expenses (invoice_line_id);
CREATE INDEX expenses_task_idx ON expenses (task_id);

COMMIT;
