-- 032_projects_tasks.sql
-- Projects & tasks (new tables; the cert-study study_plans/plan_items stay untouched).
-- Assignees are members, so a task can be assigned to a human or an agent.
-- Questions: P1–P13, DB2, DB5. tasks.ticket_id FK is added in 034_tickets.sql.

BEGIN;

CREATE TABLE projects (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code               text NOT NULL UNIQUE,                       -- next_document_number('project')
    name               text NOT NULL,
    description        text,
    organization_id    bigint REFERENCES organizations(id) ON DELETE SET NULL,   -- the customer
    deal_id            bigint REFERENCES deals(id) ON DELETE SET NULL,
    department_id      bigint REFERENCES departments(id) ON DELETE SET NULL,
    owner_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,
    status             text NOT NULL DEFAULT 'planning'
                           CHECK (status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')),
    start_date         date,
    due_date           date,
    completed_at       timestamptz,
    billing_type       text NOT NULL DEFAULT 'hourly'
                           CHECK (billing_type IN ('fixed', 'hourly', 'non_billable')),
    hourly_rate        numeric(12,2) CHECK (hourly_rate >= 0),
    budget_hours       numeric(10,2) CHECK (budget_hours >= 0),      -- P6, P8, W6
    budget_amount      numeric(14,2) CHECK (budget_amount >= 0),     -- P8 (expenses + hours + AI spend)
    currency           char(3) NOT NULL,
    archived_at        timestamptz,
    search_tsv         tsvector,
    created_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX projects_status_idx     ON projects (status) WHERE archived_at IS NULL;
CREATE INDEX projects_org_idx        ON projects (organization_id);
CREATE INDEX projects_department_idx ON projects (department_id);
CREATE INDEX projects_owner_idx      ON projects (owner_member_id);
CREATE INDEX projects_search_idx     ON projects USING gin (search_tsv);

CREATE TABLE project_members (
    project_id  bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    role        text,                                                -- 'lead', 'contributor', ...
    added_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, member_id)
);
CREATE INDEX project_members_member_idx ON project_members (member_id);

CREATE TABLE milestones (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id    bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name          text NOT NULL,
    due_date      date,
    completed_at  timestamptz,
    sort_order    integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX milestones_due_idx ON milestones (due_date) WHERE completed_at IS NULL;   -- P9

CREATE TABLE tasks (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id          bigint REFERENCES projects(id) ON DELETE CASCADE,       -- null = standalone task
    milestone_id        bigint REFERENCES milestones(id) ON DELETE SET NULL,
    parent_task_id      bigint REFERENCES tasks(id) ON DELETE CASCADE,
    organization_id     bigint REFERENCES organizations(id) ON DELETE SET NULL, -- customer work without a project
    ticket_id           bigint,                                                  -- FK in 034
    title               text NOT NULL,
    description         text,
    task_type           text,                                                    -- P11 grouping
    assignee_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,       -- human or agent (P7)
    department_id       bigint REFERENCES departments(id) ON DELETE SET NULL,
    status              text NOT NULL DEFAULT 'todo'
                            CHECK (status IN ('todo', 'in_progress', 'blocked', 'done', 'cancelled')),
    blocked_reason      text,                                                    -- P5
    priority            text NOT NULL DEFAULT 'normal'
                            CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    start_date          date,
    due_date            date,
    estimate_hours      numeric(8,2) CHECK (estimate_hours >= 0),
    completed_at        timestamptz,
    sort_order          integer NOT NULL DEFAULT 0,
    search_tsv          tsvector,
    created_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tasks_assignee_due_idx ON tasks (assignee_member_id, due_date)
    WHERE status NOT IN ('done', 'cancelled');                                   -- P2, P3
CREATE INDEX tasks_project_idx      ON tasks (project_id, status);
CREATE INDEX tasks_due_idx          ON tasks (due_date) WHERE status NOT IN ('done', 'cancelled');
CREATE INDEX tasks_department_idx   ON tasks (department_id);
CREATE INDEX tasks_parent_idx       ON tasks (parent_task_id);
CREATE INDEX tasks_search_idx       ON tasks USING gin (search_tsv);

CREATE TABLE task_dependencies (
    task_id             bigint NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id  bigint NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id)
);
CREATE INDEX task_dependencies_on_idx ON task_dependencies (depends_on_task_id);

CREATE TABLE task_checklist_items (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id     bigint NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    body        text NOT NULL,
    done_at     timestamptz,
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX task_checklist_task_idx ON task_checklist_items (task_id, sort_order);

CREATE OR REPLACE FUNCTION projects_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.code, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER projects_tsv_trg BEFORE INSERT OR UPDATE OF code, name, description
    ON projects FOR EACH ROW EXECUTE FUNCTION projects_tsv_update();

CREATE OR REPLACE FUNCTION tasks_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER tasks_tsv_trg BEFORE INSERT OR UPDATE OF title, description
    ON tasks FOR EACH ROW EXECUTE FUNCTION tasks_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX projects_deal_idx ON projects (deal_id);
CREATE INDEX milestones_project_idx ON milestones (project_id, sort_order);
CREATE INDEX tasks_milestone_idx ON tasks (milestone_id);
CREATE INDEX tasks_org_idx ON tasks (organization_id);

COMMIT;
