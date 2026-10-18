-- 058_people_payroll.sql
-- Human HR beside the agent HR of 042: employment records for people, compensation history,
-- pay runs with their line detail, and leave (types, balances, requests).
--
-- Scope: this keeps the records and pays what the business decides to pay. Statutory tax
-- calculation and filing are NOT in scope -- the accountant or a payroll provider computes
-- them, and the pay run records the result. Onboarding checklists are ordinary tasks in the
-- Projects module, not a second task system. HR paperwork lives in Documents, linked to the
-- member. Questions: PE1-PE13. Module grant: 'people'.

BEGIN;

CREATE TABLE employment_profiles (
    member_id            bigint PRIMARY KEY REFERENCES members(id) ON DELETE RESTRICT,
    employee_no          text UNIQUE,
    employment_type      text NOT NULL DEFAULT 'employee'
                             CHECK (employment_type IN ('employee', 'contractor', 'intern')),
    job_title            text,
    department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    manager_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,
    work_location_id     bigint REFERENCES locations(id) ON DELETE SET NULL,   -- office or desk
    start_date           date,
    end_date             date,
    status               text NOT NULL DEFAULT 'active'
                             CHECK (status IN ('candidate', 'active', 'on_leave', 'ended')),
    personal_email       citext,
    phone                text,
    address              text,
    birth_date           date,
    national_id_last4    text,
    emergency_contact    text,
    pay_type             text CHECK (pay_type IN ('salary', 'hourly', 'daily', 'per_invoice')),
    pay_rate             numeric(14,2) CHECK (pay_rate >= 0),
    pay_currency         char(3) NOT NULL DEFAULT 'USD',
    pay_schedule         text CHECK (pay_schedule IN ('weekly', 'biweekly', 'semimonthly', 'monthly')),
    weekly_hours         numeric(5,2) CHECK (weekly_hours > 0),
    payment_secret_id    bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,  -- bank details
    notes                text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX employment_profiles_dept_idx    ON employment_profiles (department_id);
CREATE INDEX employment_profiles_manager_idx ON employment_profiles (manager_member_id);
CREATE INDEX employment_profiles_status_idx  ON employment_profiles (status);
CREATE INDEX employment_profiles_location_idx ON employment_profiles (work_location_id);
CREATE INDEX employment_profiles_secret_idx  ON employment_profiles (payment_secret_id);

-- Every change to what someone is paid, kept forever (PE5).
CREATE TABLE compensation_changes (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    effective_date  date NOT NULL,
    pay_type        text NOT NULL CHECK (pay_type IN ('salary', 'hourly', 'daily', 'per_invoice')),
    pay_rate        numeric(14,2) NOT NULL CHECK (pay_rate >= 0),
    currency        char(3) NOT NULL DEFAULT 'USD',
    reason          text,
    approved_by     bigint REFERENCES members(id) ON DELETE SET NULL,
    created_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (member_id, effective_date)
);
CREATE INDEX compensation_changes_member_idx ON compensation_changes (member_id, effective_date DESC);
CREATE INDEX compensation_changes_approved_by_idx ON compensation_changes (approved_by);
CREATE INDEX compensation_changes_created_by_idx ON compensation_changes (created_by);

CREATE TABLE pay_runs (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_no            text UNIQUE,                             -- next_document_number('pay_run')
    period_start      date NOT NULL,
    period_end        date NOT NULL,
    pay_date          date NOT NULL,
    currency          char(3) NOT NULL DEFAULT 'USD',
    status            text NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'approved', 'paid', 'void')),
    gross_total       numeric(16,2) NOT NULL DEFAULT 0 CHECK (gross_total >= 0),
    deductions_total  numeric(16,2) NOT NULL DEFAULT 0 CHECK (deductions_total >= 0),
    employer_cost     numeric(16,2) NOT NULL DEFAULT 0 CHECK (employer_cost >= 0),
    net_total         numeric(16,2) NOT NULL DEFAULT 0 CHECK (net_total >= 0),
    journal_entry_id  bigint REFERENCES journal_entries(id) ON DELETE SET NULL,
    approved_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    approved_at       timestamptz,
    paid_at           timestamptz,
    note              text,
    created_by        bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);
CREATE INDEX pay_runs_period_idx ON pay_runs (period_end DESC);
CREATE INDEX pay_runs_entry_idx  ON pay_runs (journal_entry_id);
CREATE INDEX pay_runs_approved_by_idx ON pay_runs (approved_by);
CREATE INDEX pay_runs_created_by_idx ON pay_runs (created_by);

CREATE TABLE pay_run_items (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pay_run_id    bigint NOT NULL REFERENCES pay_runs(id) ON DELETE CASCADE,
    member_id     bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    hours         numeric(8,2) CHECK (hours >= 0),
    gross_amount  numeric(14,2) NOT NULL DEFAULT 0 CHECK (gross_amount >= 0),
    deductions    numeric(14,2) NOT NULL DEFAULT 0 CHECK (deductions >= 0),
    net_amount    numeric(14,2) NOT NULL DEFAULT 0 CHECK (net_amount >= 0),
    currency      char(3) NOT NULL DEFAULT 'USD',
    payment_id    bigint REFERENCES payments(id) ON DELETE SET NULL,
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pay_run_id, member_id)
);
CREATE INDEX pay_run_items_member_idx  ON pay_run_items (member_id);
CREATE INDEX pay_run_items_payment_idx ON pay_run_items (payment_id);

CREATE TABLE pay_run_lines (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pay_run_item_id   bigint NOT NULL REFERENCES pay_run_items(id) ON DELETE CASCADE,
    kind              text NOT NULL CHECK (kind IN ('earning', 'deduction', 'employer_cost',
                                                    'reimbursement')),
    code              text NOT NULL,                           -- 'base', 'overtime', 'tax', 'pension'
    description       text,
    quantity          numeric(10,2),
    rate              numeric(14,4),
    amount            numeric(14,2) NOT NULL CHECK (amount >= 0),
    gl_account_id     bigint REFERENCES gl_accounts(id) ON DELETE SET NULL,
    time_entry_ids    bigint[],                                -- hourly pay traced to the time log
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pay_run_lines_item_idx    ON pay_run_lines (pay_run_item_id);
CREATE INDEX pay_run_lines_account_idx ON pay_run_lines (gl_account_id);

CREATE TABLE leave_types (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                    text NOT NULL UNIQUE,
    is_paid                 boolean NOT NULL DEFAULT true,
    accrual_days_per_year   numeric(5,2) CHECK (accrual_days_per_year >= 0),
    carry_over_days         numeric(5,2) NOT NULL DEFAULT 0 CHECK (carry_over_days >= 0),
    requires_approval       boolean NOT NULL DEFAULT true,
    archived_at             timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE leave_balances (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id      bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    leave_type_id  bigint NOT NULL REFERENCES leave_types(id) ON DELETE CASCADE,
    year           integer NOT NULL CHECK (year BETWEEN 2000 AND 2200),
    accrued_days   numeric(6,2) NOT NULL DEFAULT 0 CHECK (accrued_days >= 0),
    carried_days   numeric(6,2) NOT NULL DEFAULT 0 CHECK (carried_days >= 0),
    used_days      numeric(6,2) NOT NULL DEFAULT 0 CHECK (used_days >= 0),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (member_id, leave_type_id, year)
);
CREATE INDEX leave_balances_type_idx ON leave_balances (leave_type_id);

CREATE TABLE leave_requests (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id             bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    leave_type_id         bigint NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
    start_date            date NOT NULL,
    end_date              date NOT NULL,
    days                  numeric(6,2) NOT NULL CHECK (days > 0),
    half_day              boolean NOT NULL DEFAULT false,
    reason                text,
    status                text NOT NULL DEFAULT 'requested'
                              CHECK (status IN ('requested', 'approved', 'rejected', 'cancelled')),
    decided_by            bigint REFERENCES members(id) ON DELETE SET NULL,
    decided_at            timestamptz,
    decision_note         text,
    availability_block_id bigint REFERENCES availability_blocks(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);
CREATE INDEX leave_requests_member_idx  ON leave_requests (member_id, start_date DESC);
CREATE INDEX leave_requests_pending_idx ON leave_requests (status, start_date) WHERE status = 'requested';
CREATE INDEX leave_requests_type_idx    ON leave_requests (leave_type_id);
CREATE INDEX leave_requests_decided_by_idx ON leave_requests (decided_by);
CREATE INDEX leave_requests_block_idx   ON leave_requests (availability_block_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['employment_profiles', 'compensation_changes', 'pay_runs',
                             'pay_run_items', 'pay_run_lines', 'leave_types', 'leave_balances',
                             'leave_requests'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['employment_profiles', 'pay_runs', 'pay_run_items', 'leave_types',
                             'leave_balances', 'leave_requests'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- Visibility: pay is the tightest data in the system. Your own record always; your reports'
-- records if you manage them; everything only with the 'people' module (HR) or Owner.
-- Managers do NOT see pay outside their own reporting line, and agents never see any of it.
CREATE OR REPLACE FUNCTION app_can_see_person(p_member_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_member_kind() = 'human'
       AND (p_member_id = app_current_member_id()
            OR app_is_super_admin()
            OR (app_has_module('people') AND app_can_admin_member(p_member_id))
            OR EXISTS (SELECT 1 FROM employment_profiles e
                        WHERE e.member_id = p_member_id
                          AND e.manager_member_id = app_current_member_id()));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_person(bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_employment_profiles WITH (security_barrier = true) AS
SELECT e.member_id, m.display_name, e.employee_no, e.employment_type, e.job_title,
       e.department_id, d.name::text AS department_name, e.manager_member_id,
       mg.display_name AS manager_name, e.work_location_id, l.name AS work_location_name,
       e.start_date, e.end_date, e.status, e.phone, e.pay_type, e.pay_rate, e.pay_currency,
       e.pay_schedule, e.weekly_hours, e.notes
FROM employment_profiles e
JOIN members m            ON m.id = e.member_id
LEFT JOIN departments d   ON d.id = e.department_id
LEFT JOIN members mg      ON mg.id = e.manager_member_id
LEFT JOIN locations l     ON l.id = e.work_location_id
WHERE app_can_see_person(e.member_id);

CREATE OR REPLACE VIEW mcp_compensation_changes WITH (security_barrier = true) AS
SELECT c.id AS compensation_change_id, c.member_id, m.display_name, c.effective_date,
       c.pay_type, c.pay_rate, c.currency, c.reason, c.approved_by, c.created_at
FROM compensation_changes c JOIN members m ON m.id = c.member_id
WHERE app_can_see_person(c.member_id);

CREATE OR REPLACE VIEW mcp_pay_runs WITH (security_barrier = true) AS
SELECT r.id AS pay_run_id, r.run_no, r.period_start, r.period_end, r.pay_date, r.currency,
       r.status, r.gross_total, r.deductions_total, r.employer_cost, r.net_total,
       r.journal_entry_id, r.approved_by, r.approved_at, r.paid_at, r.note,
       (SELECT count(*) FROM pay_run_items i WHERE i.pay_run_id = r.id) AS people_paid
FROM pay_runs r
WHERE app_member_kind() = 'human' AND (app_has_module('people') OR app_is_super_admin());

CREATE OR REPLACE VIEW mcp_pay_run_items WITH (security_barrier = true) AS
SELECT i.id AS pay_run_item_id, i.pay_run_id, r.run_no, r.pay_date, r.period_start, r.period_end,
       i.member_id, m.display_name, i.hours, i.gross_amount, i.deductions, i.net_amount,
       i.currency, i.payment_id, i.note
FROM pay_run_items i
JOIN pay_runs r ON r.id = i.pay_run_id
JOIN members m  ON m.id = i.member_id
WHERE app_can_see_person(i.member_id);

CREATE OR REPLACE VIEW mcp_pay_run_lines WITH (security_barrier = true) AS
SELECT pl.id AS pay_run_line_id, pl.pay_run_item_id, i.pay_run_id, i.member_id, pl.kind,
       pl.code, pl.description, pl.quantity, pl.rate, pl.amount, pl.gl_account_id
FROM pay_run_lines pl
JOIN pay_run_items i ON i.id = pl.pay_run_item_id
WHERE app_can_see_person(i.member_id);

CREATE OR REPLACE VIEW mcp_leave_types WITH (security_barrier = true) AS
SELECT id AS leave_type_id, name, is_paid, accrual_days_per_year, carry_over_days,
       requires_approval, archived_at
FROM leave_types WHERE app_is_insider() AND app_member_kind() = 'human';

CREATE OR REPLACE VIEW mcp_leave_balances WITH (security_barrier = true) AS
SELECT b.id AS leave_balance_id, b.member_id, m.display_name, b.leave_type_id,
       lt.name AS leave_type, b.year, b.accrued_days, b.carried_days, b.used_days,
       (b.accrued_days + b.carried_days - b.used_days) AS remaining_days
FROM leave_balances b
JOIN members m     ON m.id = b.member_id
JOIN leave_types lt ON lt.id = b.leave_type_id
WHERE app_can_see_person(b.member_id);

CREATE OR REPLACE VIEW mcp_leave_requests WITH (security_barrier = true) AS
SELECT lr.id AS leave_request_id, lr.member_id, m.display_name, lr.leave_type_id,
       lt.name AS leave_type, lr.start_date, lr.end_date, lr.days, lr.half_day, lr.reason,
       lr.status, lr.decided_by, lr.decided_at, lr.decision_note, lr.created_at
FROM leave_requests lr
JOIN members m      ON m.id = lr.member_id
JOIN leave_types lt ON lt.id = lr.leave_type_id
WHERE app_can_see_person(lr.member_id)
   OR (app_can_admin_member(lr.member_id) AND app_member_kind() = 'human');  -- who is off (PE11)

GRANT SELECT ON mcp_employment_profiles, mcp_compensation_changes, mcp_pay_runs,
    mcp_pay_run_items, mcp_pay_run_lines, mcp_leave_types, mcp_leave_balances, mcp_leave_requests
TO app_records_ro;

INSERT INTO leave_types (name, is_paid, accrual_days_per_year, requires_approval) VALUES
    ('Paid time off', true, 20, true),
    ('Sick leave',    true, 10, false),
    ('Unpaid leave',  false, NULL, true),
    ('Public holiday', true, NULL, false)
ON CONFLICT (name) DO NOTHING;

COMMIT;
