-- 034_tickets.sql
-- Tickets & requests (new tables; cert-study study_issues/replies stay untouched).
-- Questions: T1–T11, DB2. SLA due times are stamped on the ticket at creation/priority
-- change from its policy, so breach checks (T3) are plain indexed comparisons.

BEGIN;

CREATE TABLE ticket_categories (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           text NOT NULL UNIQUE,
    department_id  bigint REFERENCES departments(id) ON DELETE SET NULL,
    archived_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sla_policies (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                     text NOT NULL,
    priority                 text NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    department_id            bigint REFERENCES departments(id) ON DELETE CASCADE,   -- null = all departments
    first_response_minutes   integer NOT NULL CHECK (first_response_minutes > 0),
    resolution_minutes       integer NOT NULL CHECK (resolution_minutes > 0),
    business_hours_only      boolean NOT NULL DEFAULT true,
    archived_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX sla_policies_live_idx ON sla_policies (priority, COALESCE(department_id, 0))
    WHERE archived_at IS NULL;

CREATE TABLE tickets (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    number                   text NOT NULL UNIQUE,                  -- next_document_number('ticket')
    subject                  text NOT NULL,
    description              text,
    origin                   text NOT NULL DEFAULT 'internal'
                                 CHECK (origin IN ('internal', 'portal', 'email', 'phone', 'agent')),
    requester_contact_id     bigint REFERENCES contacts(id) ON DELETE SET NULL,
    requester_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,   -- staff or External (T9)
    organization_id          bigint REFERENCES organizations(id) ON DELETE SET NULL,
    project_id               bigint REFERENCES projects(id) ON DELETE SET NULL,
    department_id            bigint REFERENCES departments(id) ON DELETE SET NULL,
    category_id              bigint REFERENCES ticket_categories(id) ON DELETE SET NULL,  -- T7
    assignee_member_id       bigint REFERENCES members(id) ON DELETE SET NULL,   -- human or agent
    priority                 text NOT NULL DEFAULT 'normal'
                                 CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status                   text NOT NULL DEFAULT 'new'
                                 CHECK (status IN ('new', 'open', 'pending', 'on_hold', 'resolved', 'closed')),
    sla_policy_id            bigint REFERENCES sla_policies(id) ON DELETE SET NULL,
    first_response_due_at    timestamptz,                                          -- T3
    resolution_due_at        timestamptz,
    first_responded_at       timestamptz,                                          -- T5, T8
    resolved_at              timestamptz,
    resolved_by_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,    -- T11
    closed_at                timestamptz,
    reopened_count           integer NOT NULL DEFAULT 0 CHECK (reopened_count >= 0),  -- T11
    resolution_summary       text,                                                 -- T6
    satisfaction_score       smallint CHECK (satisfaction_score BETWEEN 1 AND 5),
    search_tsv               tsvector,
    created_by               bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tickets_open_idx         ON tickets (status, priority) WHERE status NOT IN ('resolved', 'closed');
CREATE INDEX tickets_assignee_idx     ON tickets (assignee_member_id) WHERE status NOT IN ('resolved', 'closed');
CREATE INDEX tickets_department_idx   ON tickets (department_id);
CREATE INDEX tickets_org_idx          ON tickets (organization_id, created_at DESC);
CREATE INDEX tickets_response_due_idx ON tickets (first_response_due_at) WHERE first_responded_at IS NULL;
CREATE INDEX tickets_resolve_due_idx  ON tickets (resolution_due_at) WHERE resolved_at IS NULL;
CREATE INDEX tickets_search_idx       ON tickets USING gin (search_tsv);

-- Public replies and internal notes. External members never see internal notes.
CREATE TABLE ticket_messages (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id          bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    kind               text NOT NULL CHECK (kind IN ('reply', 'internal_note', 'system')),
    author_member_id   bigint REFERENCES members(id) ON DELETE SET NULL,
    author_contact_id  bigint REFERENCES contacts(id) ON DELETE SET NULL,    -- email-in replies
    body               text NOT NULL,
    search_tsv         tsvector,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ticket_messages_ticket_idx ON ticket_messages (ticket_id, created_at);
CREATE INDEX ticket_messages_search_idx ON ticket_messages USING gin (search_tsv);

ALTER TABLE tasks
    ADD CONSTRAINT tasks_ticket_fk FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE SET NULL;
CREATE INDEX tasks_ticket_idx ON tasks (ticket_id);

CREATE OR REPLACE FUNCTION tickets_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.resolution_summary, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER tickets_tsv_trg BEFORE INSERT OR UPDATE OF number, subject, description, resolution_summary
    ON tickets FOR EACH ROW EXECUTE FUNCTION tickets_tsv_update();

CREATE OR REPLACE FUNCTION ticket_messages_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv := to_tsvector('english', coalesce(NEW.body, ''));
    RETURN NEW;
END$$;
CREATE TRIGGER ticket_messages_tsv_trg BEFORE INSERT OR UPDATE OF body
    ON ticket_messages FOR EACH ROW EXECUTE FUNCTION ticket_messages_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX tickets_project_idx ON tickets (project_id);
CREATE INDEX tickets_requester_member_idx ON tickets (requester_member_id);
CREATE INDEX tickets_requester_contact_idx ON tickets (requester_contact_id);
CREATE INDEX tickets_category_idx ON tickets (category_id, created_at);
CREATE INDEX tickets_resolved_by_idx ON tickets (resolved_by_member_id);

COMMIT;
