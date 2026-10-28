-- 062_reporting.sql
-- Reporting and dashboards: saved report definitions (a named question with parameters),
-- their runs, scheduled delivery, and the dashboards that pin them.
--
-- A report definition names an MCP tool and its parameters rather than carrying SQL, so a
-- report is answerable by the assistant and by a screen from one definition, and no report
-- can widen visibility -- it runs as the member who runs it, over the same mcp_* views.
-- Questions: RP1-RP9. Module grant: 'reports'.

BEGIN;

CREATE TABLE report_definitions (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key             text NOT NULL UNIQUE,
    name            text NOT NULL,
    description     text,
    category        text NOT NULL DEFAULT 'general'
                        CHECK (category IN ('money', 'sales', 'work', 'people', 'ai', 'ops',
                                            'general')),
    module          text NOT NULL,                             -- the module grant that gates it
    server          text NOT NULL DEFAULT 'records'
                        CHECK (server IN ('records', 'activity')),
    tool_name       text NOT NULL,                             -- the MCP tool it calls
    params          jsonb NOT NULL DEFAULT '{}',               -- fixed params; the rest are prompted
    prompt_params   text[] NOT NULL DEFAULT '{}',              -- params the user supplies (period, …)
    visualization   text NOT NULL DEFAULT 'table'
                        CHECK (visualization IN ('table', 'number', 'bar', 'line', 'pie', 'list')),
    is_system       boolean NOT NULL DEFAULT false,
    owner_member_id bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id   bigint REFERENCES departments(id) ON DELETE SET NULL,
    is_shared       boolean NOT NULL DEFAULT true,
    archived_at     timestamptz,
    created_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX report_definitions_category_idx ON report_definitions (category) WHERE archived_at IS NULL;
CREATE INDEX report_definitions_owner_idx    ON report_definitions (owner_member_id);
CREATE INDEX report_definitions_dept_idx     ON report_definitions (department_id);
CREATE INDEX report_definitions_created_by_idx ON report_definitions (created_by);

CREATE TABLE report_runs (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id      bigint NOT NULL REFERENCES report_definitions(id) ON DELETE CASCADE,
    run_by         bigint REFERENCES members(id) ON DELETE SET NULL,   -- human or agent
    schedule_id    bigint,                                    -- FK below
    params         jsonb NOT NULL DEFAULT '{}',
    status         text NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'succeeded', 'failed')),
    row_count      integer CHECK (row_count >= 0),
    duration_ms    integer CHECK (duration_ms >= 0),
    error          text,
    export_document_id bigint REFERENCES documents(id) ON DELETE SET NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);
CREATE INDEX report_runs_report_idx ON report_runs (report_id, started_at DESC);
CREATE INDEX report_runs_by_idx     ON report_runs (run_by, started_at DESC);
CREATE INDEX report_runs_doc_idx    ON report_runs (export_document_id);

CREATE TABLE report_schedules (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id         bigint NOT NULL REFERENCES report_definitions(id) ON DELETE CASCADE,
    name              text,
    cadence           text NOT NULL CHECK (cadence IN ('daily', 'weekly', 'monthly', 'quarterly')),
    day_of_week       smallint CHECK (day_of_week BETWEEN 0 AND 6),
    day_of_month      smallint CHECK (day_of_month BETWEEN 1 AND 28),
    send_hour         smallint NOT NULL DEFAULT 7 CHECK (send_hour BETWEEN 0 AND 23),
    params            jsonb NOT NULL DEFAULT '{}',
    recipient_member_ids bigint[] NOT NULL DEFAULT '{}',
    recipient_emails  citext[] NOT NULL DEFAULT '{}',
    format            text NOT NULL DEFAULT 'html' CHECK (format IN ('html', 'csv', 'pdf')),
    active            boolean NOT NULL DEFAULT true,
    next_run_at       timestamptz,
    last_run_at       timestamptz,
    last_run_id       bigint REFERENCES report_runs(id) ON DELETE SET NULL,
    created_by        bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX report_schedules_due_idx    ON report_schedules (next_run_at) WHERE active;
CREATE INDEX report_schedules_report_idx ON report_schedules (report_id);
CREATE INDEX report_schedules_run_idx    ON report_schedules (last_run_id);
CREATE INDEX report_schedules_by_idx     ON report_schedules (created_by);

ALTER TABLE report_runs
    ADD CONSTRAINT report_runs_schedule_fk
    FOREIGN KEY (schedule_id) REFERENCES report_schedules(id) ON DELETE SET NULL;
CREATE INDEX report_runs_schedule_idx ON report_runs (schedule_id);

CREATE TABLE dashboards (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text NOT NULL,
    slug             text UNIQUE,
    owner_member_id  bigint REFERENCES members(id) ON DELETE CASCADE,
    department_id    bigint REFERENCES departments(id) ON DELETE SET NULL,
    is_shared        boolean NOT NULL DEFAULT false,
    is_default       boolean NOT NULL DEFAULT false,
    layout           jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX dashboards_default_idx ON dashboards ((true)) WHERE is_default;
CREATE INDEX dashboards_owner_idx ON dashboards (owner_member_id);
CREATE INDEX dashboards_dept_idx  ON dashboards (department_id);

CREATE TABLE dashboard_widgets (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dashboard_id   bigint NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    report_id      bigint REFERENCES report_definitions(id) ON DELETE SET NULL,
    kind           text NOT NULL DEFAULT 'report'
                       CHECK (kind IN ('report', 'metric', 'list', 'text')),
    title          text NOT NULL,
    params         jsonb NOT NULL DEFAULT '{}',
    position       integer NOT NULL DEFAULT 0,
    width          smallint NOT NULL DEFAULT 6 CHECK (width BETWEEN 1 AND 12),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dashboard_widgets_dash_idx   ON dashboard_widgets (dashboard_id, position);
CREATE INDEX dashboard_widgets_report_idx ON dashboard_widgets (report_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['report_definitions', 'report_runs', 'report_schedules',
                             'dashboards', 'dashboard_widgets'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['report_definitions', 'report_schedules', 'dashboards',
                             'dashboard_widgets'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- A report is visible when you hold the module it reads, and it is shared or yours. Running
-- it is still scoped by that module's own views, so a shared report shows each person their
-- own slice rather than someone else's rows.
CREATE OR REPLACE VIEW mcp_report_definitions WITH (security_barrier = true) AS
SELECT r.id AS report_id, r.key, r.name, r.description, r.category, r.module, r.server,
       r.tool_name, r.params, r.prompt_params, r.visualization, r.is_system, r.owner_member_id,
       r.department_id, r.is_shared, r.archived_at,
       (SELECT max(started_at) FROM report_runs rr WHERE rr.report_id = r.id) AS last_run_at
FROM report_definitions r
WHERE app_is_insider()
  AND app_has_module(r.module)
  AND (r.is_shared OR r.owner_member_id = app_current_member_id());

CREATE OR REPLACE VIEW mcp_report_runs WITH (security_barrier = true) AS
SELECT rr.id AS report_run_id, rr.report_id, r.name AS report_name, rr.run_by, rr.schedule_id,
       rr.params, rr.status, rr.row_count, rr.duration_ms, rr.error, rr.export_document_id,
       rr.started_at, rr.finished_at
FROM report_runs rr JOIN report_definitions r ON r.id = rr.report_id
WHERE app_is_insider() AND app_has_module(r.module)
  AND (rr.run_by = app_current_member_id() OR app_is_super_admin() OR app_has_module('reports'));

CREATE OR REPLACE VIEW mcp_report_schedules WITH (security_barrier = true) AS
SELECT s.id AS report_schedule_id, s.report_id, r.name AS report_name, s.name, s.cadence,
       s.day_of_week, s.day_of_month, s.send_hour, s.params, s.recipient_member_ids,
       s.format, s.active, s.next_run_at, s.last_run_at
FROM report_schedules s JOIN report_definitions r ON r.id = s.report_id
WHERE app_is_insider() AND app_has_module(r.module);

CREATE OR REPLACE VIEW mcp_dashboards WITH (security_barrier = true) AS
SELECT d.id AS dashboard_id, d.name, d.slug, d.owner_member_id, d.department_id, d.is_shared,
       d.is_default, d.layout,
       (SELECT count(*) FROM dashboard_widgets w WHERE w.dashboard_id = d.id) AS widget_count
FROM dashboards d
WHERE app_is_insider()
  AND (d.owner_member_id = app_current_member_id() OR d.is_shared OR d.is_default
       OR (d.department_id IS NOT NULL AND d.department_id = ANY (app_my_department_ids())));

CREATE OR REPLACE VIEW mcp_dashboard_widgets WITH (security_barrier = true) AS
SELECT w.id AS dashboard_widget_id, w.dashboard_id, w.report_id, w.kind, w.title, w.params,
       w.position, w.width
FROM dashboard_widgets w JOIN dashboards d ON d.id = w.dashboard_id
WHERE app_is_insider()
  AND (d.owner_member_id = app_current_member_id() OR d.is_shared OR d.is_default
       OR (d.department_id IS NOT NULL AND d.department_id = ANY (app_my_department_ids())));

GRANT SELECT ON mcp_report_definitions, mcp_report_runs, mcp_report_schedules, mcp_dashboards,
    mcp_dashboard_widgets
TO app_records_ro;

-- A starter set, each one a tool this design already has.
INSERT INTO report_definitions (key, name, description, category, module, tool_name,
                                prompt_params, visualization, is_system)
VALUES
    ('receivables_aging', 'Receivables aging', 'Who owes us, by age bucket', 'money', 'sales',
     'receivables', '{period}', 'table', true),
    ('profit_and_loss', 'Profit and loss', 'Income and expense by account for a period', 'money',
     'books', 'financial_statement', '{period}', 'table', true),
    ('ai_spend_by_department', 'AI spend by department', 'What the agent workforce cost, by department',
     'ai', 'ledger', 'ai_spend', '{period}', 'bar', true),
    ('time_by_project', 'Time by project', 'Where the hours went', 'work', 'time',
     'time_summary', '{period}', 'bar', true),
    ('open_tickets_by_age', 'Open tickets by age', 'Tickets still open, oldest first', 'work',
     'tickets', 'find_tickets', '{}', 'list', true)
ON CONFLICT (key) DO NOTHING;

COMMIT;
