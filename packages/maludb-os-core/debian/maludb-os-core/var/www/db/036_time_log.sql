-- 036_time_log.sql
-- Time & work log (new table; cert-study study_sessions stays untouched).
-- Human hours only: agent effort is measured by agent_runs + the prompt ledger (045).
-- Questions: W1–W7, P6, P8, E7, SM11. invoice_line_id FK is added in 037; campaign_id FK in 040.

BEGIN;

CREATE TABLE time_entries (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    entry_date        date   NOT NULL,
    started_at        timestamptz,
    ended_at          timestamptz,
    minutes           integer NOT NULL CHECK (minutes > 0),
    project_id        bigint REFERENCES projects(id) ON DELETE SET NULL,
    task_id           bigint REFERENCES tasks(id) ON DELETE SET NULL,
    organization_id   bigint REFERENCES organizations(id) ON DELETE SET NULL,
    ticket_id         bigint REFERENCES tickets(id) ON DELETE SET NULL,
    appointment_id    bigint REFERENCES appointments(id) ON DELETE SET NULL,
    campaign_id       bigint,                                            -- FK in 040
    department_id     bigint REFERENCES departments(id) ON DELETE SET NULL,
    description       text,
    billable          boolean NOT NULL DEFAULT true,
    hourly_rate       numeric(12,2) CHECK (hourly_rate >= 0),            -- snapshot at entry time
    currency          char(3),
    status            text NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    approved_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    approved_at       timestamptz,
    locked_at         timestamptz,                                       -- set when approved or invoiced (W7)
    invoice_line_id   bigint,                                            -- FK in 037 (W3)
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at > started_at)
);
CREATE INDEX time_entries_member_date_idx ON time_entries (member_id, entry_date);
CREATE INDEX time_entries_project_idx     ON time_entries (project_id, entry_date);
CREATE INDEX time_entries_org_idx         ON time_entries (organization_id, entry_date);
CREATE INDEX time_entries_unbilled_idx    ON time_entries (organization_id)
    WHERE billable AND invoice_line_id IS NULL;

-- Foreign-key lookup indexes
CREATE INDEX time_entries_task_idx ON time_entries (task_id);
CREATE INDEX time_entries_ticket_idx ON time_entries (ticket_id);
CREATE INDEX time_entries_appointment_idx ON time_entries (appointment_id);

COMMIT;
