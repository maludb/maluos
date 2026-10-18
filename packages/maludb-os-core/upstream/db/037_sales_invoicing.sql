-- 037_sales_invoicing.sql
-- Sales & invoicing: tax rates, catalog, quotes, invoices, manual payments + allocations,
-- credit notes. Online collection (provider payments, links, refunds, payouts) is in 038.
-- Questions: S1–S14, S19, S20, DB1, DB3, K7, W3, E8.
-- Money: numeric(14,2) in the document's currency; no FX conversion in v1.
-- Totals are stored (written by the app when lines change) so reports stay cheap.

BEGIN;

CREATE TABLE tax_rates (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,                           -- 'Sales tax 8.25%'
    rate         numeric(7,4) NOT NULL CHECK (rate >= 0 AND rate < 100),   -- percent
    is_default   boolean NOT NULL DEFAULT false,
    archived_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tax_rates_one_default_idx ON tax_rates ((true)) WHERE is_default AND archived_at IS NULL;

CREATE TABLE catalog_items (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL,
    description   text,
    unit          text,                                           -- 'hour', 'each', 'month'
    unit_price    numeric(14,2) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    currency      char(3) NOT NULL,
    tax_rate_id   bigint REFERENCES tax_rates(id) ON DELETE SET NULL,
    archived_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_items_name_trgm ON catalog_items USING gin (name gin_trgm_ops);

-- --------------------------------------------------------------------------
-- Quotes
-- --------------------------------------------------------------------------
CREATE TABLE quotes (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number                text NOT NULL UNIQUE,
    organization_id       bigint REFERENCES organizations(id) ON DELETE RESTRICT,
    contact_id            bigint REFERENCES contacts(id) ON DELETE SET NULL,
    deal_id               bigint REFERENCES deals(id) ON DELETE SET NULL,
    project_id            bigint REFERENCES projects(id) ON DELETE SET NULL,
    status                text NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'sent', 'accepted', 'declined', 'expired', 'converted')),
    issue_date            date NOT NULL DEFAULT current_date,
    valid_until           date,                                    -- S5
    currency              char(3) NOT NULL,
    subtotal              numeric(14,2) NOT NULL DEFAULT 0,
    tax_total             numeric(14,2) NOT NULL DEFAULT 0,
    total                 numeric(14,2) NOT NULL DEFAULT 0,
    notes                 text,
    terms                 text,
    sent_at               timestamptz,
    accepted_at           timestamptz,
    declined_at           timestamptz,
    converted_invoice_id  bigint,                                  -- FK below (S6)
    owner_member_id       bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id         bigint REFERENCES departments(id) ON DELETE SET NULL,
    created_by            bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quotes_status_idx ON quotes (status, valid_until);
CREATE INDEX quotes_org_idx    ON quotes (organization_id);

CREATE TABLE quote_lines (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quote_id         bigint NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    sort_order       integer NOT NULL DEFAULT 0,
    catalog_item_id  bigint REFERENCES catalog_items(id) ON DELETE SET NULL,
    description      text NOT NULL,
    quantity         numeric(12,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price       numeric(14,2) NOT NULL CHECK (unit_price >= 0),
    tax_rate_id      bigint REFERENCES tax_rates(id) ON DELETE SET NULL,
    line_subtotal    numeric(14,2) NOT NULL,
    line_tax         numeric(14,2) NOT NULL DEFAULT 0,
    line_total       numeric(14,2) NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quote_lines_quote_idx ON quote_lines (quote_id, sort_order);

-- --------------------------------------------------------------------------
-- Invoices
-- --------------------------------------------------------------------------
CREATE TABLE invoices (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number                  text NOT NULL UNIQUE,
    organization_id         bigint REFERENCES organizations(id) ON DELETE RESTRICT,
    contact_id              bigint REFERENCES contacts(id) ON DELETE SET NULL,
    deal_id                 bigint REFERENCES deals(id) ON DELETE SET NULL,
    project_id              bigint REFERENCES projects(id) ON DELETE SET NULL,   -- S10
    quote_id                bigint REFERENCES quotes(id) ON DELETE SET NULL,
    status                  text NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'sent', 'viewed', 'partially_paid', 'paid',
                                                  'void', 'written_off')),
    issue_date              date NOT NULL DEFAULT current_date,
    due_date                date NOT NULL,                                        -- S2 aging
    currency                char(3) NOT NULL,
    subtotal                numeric(14,2) NOT NULL DEFAULT 0,
    tax_total               numeric(14,2) NOT NULL DEFAULT 0,                     -- S9
    total                   numeric(14,2) NOT NULL DEFAULT 0,
    amount_paid             numeric(14,2) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    amount_credited         numeric(14,2) NOT NULL DEFAULT 0 CHECK (amount_credited >= 0),
    balance_due             numeric(14,2) GENERATED ALWAYS AS (total - amount_paid - amount_credited) STORED,
    online_payment_enabled  boolean NOT NULL DEFAULT true,
    sent_at                 timestamptz,
    first_viewed_at         timestamptz,
    paid_at                 timestamptz,                                          -- S11
    voided_at               timestamptz,
    void_reason             text,
    last_reminder_at        timestamptz,
    reminder_count          integer NOT NULL DEFAULT 0 CHECK (reminder_count >= 0),
    notes                   text,
    terms                   text,
    owner_member_id         bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id           bigint REFERENCES departments(id) ON DELETE SET NULL,
    created_by              bigint REFERENCES members(id) ON DELETE SET NULL,     -- S14 (member_kind)
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invoices_status_due_idx ON invoices (status, due_date);
CREATE INDEX invoices_open_idx       ON invoices (due_date)
    WHERE status IN ('sent', 'viewed', 'partially_paid');
CREATE INDEX invoices_org_idx        ON invoices (organization_id, issue_date);
CREATE INDEX invoices_issue_idx      ON invoices (issue_date);
CREATE INDEX invoices_project_idx    ON invoices (project_id);

ALTER TABLE quotes
    ADD CONSTRAINT quotes_converted_invoice_fk
    FOREIGN KEY (converted_invoice_id) REFERENCES invoices(id) ON DELETE SET NULL;

CREATE TABLE invoice_lines (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id       bigint NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    sort_order       integer NOT NULL DEFAULT 0,
    catalog_item_id  bigint REFERENCES catalog_items(id) ON DELETE SET NULL,
    appointment_id   bigint REFERENCES appointments(id) ON DELETE SET NULL,   -- K7
    description      text NOT NULL,
    quantity         numeric(12,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price       numeric(14,2) NOT NULL CHECK (unit_price >= 0),
    tax_rate_id      bigint REFERENCES tax_rates(id) ON DELETE SET NULL,
    line_subtotal    numeric(14,2) NOT NULL,
    line_tax         numeric(14,2) NOT NULL DEFAULT 0,
    line_total       numeric(14,2) NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invoice_lines_invoice_idx     ON invoice_lines (invoice_id, sort_order);
CREATE INDEX invoice_lines_appointment_idx ON invoice_lines (appointment_id);

ALTER TABLE time_entries
    ADD CONSTRAINT time_entries_invoice_line_fk
    FOREIGN KEY (invoice_line_id) REFERENCES invoice_lines(id) ON DELETE SET NULL;

-- --------------------------------------------------------------------------
-- Payments (every payment, manual or online) + allocation to invoices
-- --------------------------------------------------------------------------
CREATE TABLE payments (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      bigint REFERENCES organizations(id) ON DELETE RESTRICT,
    contact_id           bigint REFERENCES contacts(id) ON DELETE SET NULL,
    received_on          date NOT NULL,
    amount               numeric(14,2) NOT NULL CHECK (amount > 0),
    currency             char(3) NOT NULL,
    method               text NOT NULL CHECK (method IN ('cash', 'check', 'bank_transfer', 'card',
                                                         'online', 'other')),
    source               text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'online')),  -- S20
    provider_payment_id  bigint,                                         -- FK in 038
    reference            text,                                           -- check no., bank ref
    notes                text,
    recorded_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (source = 'manual' OR provider_payment_id IS NOT NULL)
);
CREATE INDEX payments_received_idx ON payments (received_on);            -- S4
CREATE INDEX payments_org_idx      ON payments (organization_id, received_on);

CREATE TABLE payment_allocations (
    payment_id  bigint NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    invoice_id  bigint NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    amount      numeric(14,2) NOT NULL CHECK (amount > 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (payment_id, invoice_id)
);
CREATE INDEX payment_allocations_invoice_idx ON payment_allocations (invoice_id);

CREATE TABLE credit_notes (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number           text NOT NULL UNIQUE,
    invoice_id       bigint REFERENCES invoices(id) ON DELETE RESTRICT,
    organization_id  bigint REFERENCES organizations(id) ON DELETE RESTRICT,
    issue_date       date NOT NULL DEFAULT current_date,
    amount           numeric(14,2) NOT NULL CHECK (amount > 0),
    currency         char(3) NOT NULL,
    reason           text,
    status           text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'issued', 'void')),
    created_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX credit_notes_invoice_idx ON credit_notes (invoice_id);

-- Foreign-key lookup indexes
CREATE INDEX time_entries_invoice_line_idx ON time_entries (invoice_line_id);
CREATE INDEX quotes_deal_idx ON quotes (deal_id);
CREATE INDEX quotes_project_idx ON quotes (project_id);
CREATE INDEX invoices_quote_idx ON invoices (quote_id);
CREATE INDEX invoices_deal_idx ON invoices (deal_id);
CREATE INDEX credit_notes_org_idx ON credit_notes (organization_id);

COMMIT;
