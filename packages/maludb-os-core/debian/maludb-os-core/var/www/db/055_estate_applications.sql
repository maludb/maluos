-- 055_estate_applications.sql
-- The estate's second half, and the three standing departments.
--
--   * Applications: the systems a business runs — accounting, calendar, CRM, mail, the
--     platform itself — each residing at a location (an office/VM, or a desk), owned by a
--     department, reachable by any member (human or agent) holding a live access grant.
--     Credentials are references into tenant_secrets and never appear in any view.
--   * HR / Accounting / Audit: seeded in every tenant and protected from deletion.
--   * AI usage postings: the bridge from the prompt ledger (the AI-spend subledger) into
--     the books, so token spend is bookkeeping, not a separate universe.
--   * Eval schedules and alerts: the Audit department's standing watch for agents whose
--     accuracy is degrading.
--
-- Questions: L11–L14, AC1–AC6, E14–E15, EV9–EV12, H14–H15. Depends on 030–054.

BEGIN;

-- ---------------------------------------------------------------------------
-- Applications (the systems that reside at a location)
-- ---------------------------------------------------------------------------

CREATE TABLE applications (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                   text NOT NULL UNIQUE,
    app_key                text NOT NULL UNIQUE,                 -- 'books', 'crm', 'calendar'
    category               text NOT NULL CHECK (category IN ('platform', 'accounting', 'crm',
                               'calendar', 'email', 'documents', 'storage', 'database',
                               'communication', 'automation', 'development', 'security', 'other')),
    description            text,
    vendor                 text,
    is_self_hosted         boolean NOT NULL DEFAULT true,
    is_builtin             boolean NOT NULL DEFAULT false,      -- a module of this platform
    module                 text,                                -- the module grant it maps to
    location_id            bigint REFERENCES locations(id) ON DELETE SET NULL,   -- the office/VM it runs on
    owner_department_id    bigint REFERENCES departments(id) ON DELETE SET NULL,
    owner_member_id        bigint REFERENCES members(id) ON DELETE SET NULL,     -- the human accountable
    url                    text,
    version                text,
    criticality            text NOT NULL DEFAULT 'normal'
                               CHECK (criticality IN ('low', 'normal', 'high', 'critical')),
    status                 text NOT NULL DEFAULT 'active'
                               CHECK (status IN ('planned', 'active', 'degraded', 'retired')),
    health_status          text NOT NULL DEFAULT 'unknown'
                               CHECK (health_status IN ('up', 'degraded', 'down', 'unknown')),
    last_health_check_at   timestamptz,
    recurring_expense_id   bigint REFERENCES recurring_expenses(id) ON DELETE SET NULL,  -- what it costs
    notes                  text,
    retired_at             timestamptz,
    created_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX applications_location_idx   ON applications (location_id);
CREATE INDEX applications_department_idx ON applications (owner_department_id);
CREATE INDEX applications_status_idx     ON applications (status, category);
CREATE INDEX applications_expense_idx    ON applications (recurring_expense_id);
CREATE INDEX applications_owner_idx      ON applications (owner_member_id);
CREATE INDEX applications_created_by_idx ON applications (created_by);

-- How an application is reached. One application can offer several surfaces (a UI for
-- humans, an MCP endpoint and a read-only database role for agents).
CREATE TABLE application_endpoints (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id      bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    name                text NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('mcp', 'http_api', 'database', 'filesystem',
                                                      'smtp', 'imap', 'ssh', 'ui', 'webhook')),
    url                 text,                                  -- endpoint URL / DSN without the secret
    auth_kind           text NOT NULL DEFAULT 'none'
                            CHECK (auth_kind IN ('none', 'bearer', 'oauth', 'basic', 'api_key',
                                                 'os_credential', 'mtls')),
    secret_id           bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,   -- never shown
    agent_reachable     boolean NOT NULL DEFAULT true,          -- false = humans only (a UI, say)
    mcp_surface_version text,
    status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, name)
);
CREATE INDEX application_endpoints_secret_idx ON application_endpoints (secret_id);

-- Who may use an application: a member (human or agent) or a whole department. An agent
-- needs a live grant here as well as its tool grants before a harness will attach the
-- application's endpoints.
CREATE TABLE application_access (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    member_id       bigint REFERENCES members(id) ON DELETE CASCADE,
    department_id   bigint REFERENCES departments(id) ON DELETE CASCADE,
    capability      text NOT NULL DEFAULT 'read' CHECK (capability IN ('read', 'write', 'admin')),
    granted_by      bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    granted_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,
    revoked_at      timestamptz,
    revoked_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    note            text,
    CONSTRAINT application_access_one_grantee CHECK ((member_id IS NULL) <> (department_id IS NULL))
);
CREATE UNIQUE INDEX application_access_member_live_idx
    ON application_access (application_id, member_id) WHERE revoked_at IS NULL AND member_id IS NOT NULL;
CREATE UNIQUE INDEX application_access_dept_live_idx
    ON application_access (application_id, department_id) WHERE revoked_at IS NULL AND department_id IS NOT NULL;
CREATE INDEX application_access_member_idx ON application_access (member_id) WHERE revoked_at IS NULL;
CREATE INDEX application_access_dept_idx   ON application_access (department_id) WHERE revoked_at IS NULL;
CREATE INDEX application_access_granted_by_idx ON application_access (granted_by);

-- Does this member reach this application? Owner/Manager always. For a BUILT-IN application
-- (a module of this platform) the module grant is the answer -- there is one permission
-- system, not two: module grants say what a member may touch, and the application row exists
-- so the thing has an address, an owner, a location and endpoints. For an EXTERNAL system a
-- live access grant to the member or one of their departments is required.
CREATE OR REPLACE FUNCTION app_can_use_application(p_application_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_is_super_admin()
        OR EXISTS (SELECT 1 FROM applications ap
                    WHERE ap.id = p_application_id AND ap.is_builtin
                      AND ap.module IS NOT NULL AND app_has_module(ap.module))
        OR EXISTS (
            SELECT 1 FROM application_access a
             WHERE a.application_id = p_application_id
               AND a.revoked_at IS NULL
               AND (a.expires_at IS NULL OR a.expires_at > now())
               AND (a.member_id = app_current_member_id()
                    OR a.department_id = ANY (app_my_department_ids())));
$$;
GRANT EXECUTE ON FUNCTION app_can_use_application(bigint) TO app_rw, app_records_ro, app_activity_ro;

-- ---------------------------------------------------------------------------
-- The three standing departments
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION protect_system_departments() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_system THEN
            RAISE EXCEPTION 'Department "%" is a standing department and cannot be deleted', OLD.name;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.is_system AND (NEW.is_system IS DISTINCT FROM true
                          OR NEW.system_key IS DISTINCT FROM OLD.system_key) THEN
        RAISE EXCEPTION 'Department "%" is a standing department; its role cannot be changed', OLD.name;
    END IF;
    IF OLD.is_system AND NEW.archived_at IS NOT NULL THEN
        RAISE EXCEPTION 'Department "%" is a standing department and cannot be archived', OLD.name;
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER departments_protect_system
    BEFORE UPDATE OR DELETE ON departments
    FOR EACH ROW EXECUTE FUNCTION protect_system_departments();

-- ---------------------------------------------------------------------------
-- Accounting: the prompt ledger posted into the books
-- ---------------------------------------------------------------------------

-- A period roll-up of prompt_ledger cost, posted as one expense per provider and
-- department. The ledger stays the subledger; this is the journal line that reconciles
-- to it, so "what did the agents cost us in August" and "what did we spend in August"
-- are the same number.
CREATE TABLE ai_usage_postings (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_start        date NOT NULL,
    period_end          date NOT NULL,
    provider            text NOT NULL,
    model_id            bigint REFERENCES model_registry(id) ON DELETE SET NULL,
    department_id       bigint REFERENCES departments(id) ON DELETE SET NULL,
    agent_member_id     bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL,
    call_count          integer NOT NULL DEFAULT 0 CHECK (call_count >= 0),
    input_tokens        bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens       bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens   bigint NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_write_tokens  bigint NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    amount              numeric(14,4) NOT NULL CHECK (amount >= 0),
    currency            char(3) NOT NULL DEFAULT 'USD',
    expense_id          bigint REFERENCES expenses(id) ON DELETE SET NULL,   -- the booked expense
    status              text NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'posted', 'void')),
    posted_at           timestamptz,
    posted_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    note                text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);
CREATE UNIQUE INDEX ai_usage_postings_period_idx
    ON ai_usage_postings (period_start, period_end, provider, model_id, department_id, agent_member_id)
    NULLS NOT DISTINCT;
CREATE INDEX ai_usage_postings_expense_idx ON ai_usage_postings (expense_id);
CREATE INDEX ai_usage_postings_agent_idx   ON ai_usage_postings (agent_member_id, period_start DESC);
CREATE INDEX ai_usage_postings_model_idx   ON ai_usage_postings (model_id);
CREATE INDEX ai_usage_postings_posted_by_idx ON ai_usage_postings (posted_by);

-- ---------------------------------------------------------------------------
-- Audit: the standing eval watch
-- ---------------------------------------------------------------------------

CREATE TABLE eval_schedules (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_set_id        bigint NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    kind               text NOT NULL CHECK (kind IN ('scheduled_run', 'trace_sampling')),
    cadence            text NOT NULL CHECK (cadence IN ('daily', 'weekly', 'monthly')),
    sample_size        integer CHECK (sample_size > 0),          -- traces graded per cycle
    regression_delta   numeric(5,2) NOT NULL DEFAULT 5           -- points below baseline that raise an alert
                           CHECK (regression_delta >= 0 AND regression_delta <= 100),
    active             boolean NOT NULL DEFAULT true,
    next_run_at        timestamptz,
    last_run_at        timestamptz,
    last_eval_run_id   bigint REFERENCES eval_runs(id) ON DELETE SET NULL,
    created_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (eval_set_id, kind)
);
CREATE INDEX eval_schedules_due_idx ON eval_schedules (next_run_at) WHERE active;
CREATE INDEX eval_schedules_run_idx ON eval_schedules (last_eval_run_id);
CREATE INDEX eval_schedules_created_by_idx ON eval_schedules (created_by);

-- An agent slipping: below its set's threshold, below its own baseline, or a schedule that
-- never ran. Raised by the Audit department's watch, worked in the HR performance view.
CREATE TABLE eval_alerts (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_set_id        bigint NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    agent_member_id    bigint REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    eval_run_id        bigint REFERENCES eval_runs(id) ON DELETE SET NULL,
    schedule_id        bigint REFERENCES eval_schedules(id) ON DELETE SET NULL,
    kind               text NOT NULL CHECK (kind IN ('threshold_breach', 'regression',
                                                     'trace_drift', 'schedule_missed')),
    severity           text NOT NULL DEFAULT 'warning'
                           CHECK (severity IN ('info', 'warning', 'critical')),
    score              numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    baseline_score     numeric(5,2) CHECK (baseline_score BETWEEN 0 AND 100),
    detail             text NOT NULL,
    status             text NOT NULL DEFAULT 'open'
                           CHECK (status IN ('open', 'acknowledged', 'resolved')),
    opened_at          timestamptz NOT NULL DEFAULT now(),
    acknowledged_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    acknowledged_at    timestamptz,
    resolved_at        timestamptz,
    resolution         text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_alerts_open_idx  ON eval_alerts (status, opened_at DESC);
CREATE INDEX eval_alerts_agent_idx ON eval_alerts (agent_member_id, opened_at DESC);
CREATE INDEX eval_alerts_set_idx   ON eval_alerts (eval_set_id);
CREATE INDEX eval_alerts_run_idx   ON eval_alerts (eval_run_id);
CREATE INDEX eval_alerts_schedule_idx ON eval_alerts (schedule_id);
CREATE INDEX eval_alerts_ack_idx   ON eval_alerts (acknowledged_by);

-- ---------------------------------------------------------------------------
-- RLS + updated_at, as in 049
-- ---------------------------------------------------------------------------

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['applications', 'application_endpoints', 'application_access',
                             'ai_usage_postings', 'eval_schedules', 'eval_alerts'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['applications', 'application_endpoints', 'ai_usage_postings',
                             'eval_schedules', 'eval_alerts'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- ---------------------------------------------------------------------------
-- Read views
-- ---------------------------------------------------------------------------

-- Every insider sees what the business runs and where. Only holders of the applications
-- module (or Owner/Manager) see the plumbing; nobody sees a secret.
CREATE OR REPLACE VIEW mcp_applications WITH (security_barrier = true) AS
SELECT a.id AS application_id, a.name, a.app_key, a.category, a.description, a.vendor,
       a.is_self_hosted, a.is_builtin, a.module,
       a.location_id, l.name AS location_name, l.kind AS location_kind,
       a.owner_department_id, d.name::text AS owner_department_name,
       a.owner_member_id, om.display_name AS owner_name,
       a.url, a.version, a.criticality, a.status, a.health_status, a.last_health_check_at,
       app_can_use_application(a.id) AS i_can_use,
       CASE WHEN app_has_module('applications') OR app_is_super_admin()
            THEN a.recurring_expense_id END AS recurring_expense_id,
       a.notes, a.retired_at, a.created_at
FROM applications a
LEFT JOIN locations l   ON l.id = a.location_id
LEFT JOIN departments d ON d.id = a.owner_department_id
LEFT JOIN members om    ON om.id = a.owner_member_id
WHERE app_is_insider();

-- Endpoints: the caller must be able to use the application (or administer applications).
-- The secret itself is never selected — only whether one is configured.
CREATE OR REPLACE VIEW mcp_application_endpoints WITH (security_barrier = true) AS
SELECT e.id AS application_endpoint_id, e.application_id, a.name AS application_name,
       e.name, e.kind, e.url, e.auth_kind, (e.secret_id IS NOT NULL) AS has_credential,
       e.agent_reachable, e.mcp_surface_version, e.status, e.notes
FROM application_endpoints e
JOIN applications a ON a.id = e.application_id
WHERE app_is_insider()
  AND e.status = 'active'
  AND (app_has_module('applications') OR app_can_use_application(e.application_id))
  AND (e.agent_reachable OR app_member_kind() = 'human');

CREATE OR REPLACE VIEW mcp_application_access WITH (security_barrier = true) AS
SELECT ac.id AS application_access_id, ac.application_id, a.name AS application_name,
       ac.member_id, m.display_name AS member_name, m.member_kind,
       ac.department_id, d.name::text AS department_name,
       ac.capability, ac.granted_by, ac.granted_at, ac.expires_at, ac.note
FROM application_access ac
JOIN applications a ON a.id = ac.application_id
LEFT JOIN members m     ON m.id = ac.member_id
LEFT JOIN departments d ON d.id = ac.department_id
WHERE ac.revoked_at IS NULL
  AND app_is_insider()
  AND (app_has_module('applications') OR app_is_super_admin()
       OR ac.member_id = app_current_member_id()
       OR ac.department_id = ANY (app_my_department_ids()));

-- "What can I reach, and how?" — the question an agent asks before it starts work.
CREATE OR REPLACE VIEW mcp_my_applications WITH (security_barrier = true) AS
SELECT a.id AS application_id, a.name, a.app_key, a.category, a.is_builtin, a.module,
       a.location_id, l.name AS location_name, a.url, a.status, a.health_status,
       coalesce((SELECT max(ac.capability) FROM application_access ac
                  WHERE ac.application_id = a.id AND ac.revoked_at IS NULL
                    AND (ac.expires_at IS NULL OR ac.expires_at > now())
                    AND (ac.member_id = app_current_member_id()
                         OR ac.department_id = ANY (app_my_department_ids()))),
                CASE WHEN app_is_super_admin() THEN 'admin' END) AS capability,
       (SELECT count(*) FROM application_endpoints e
         WHERE e.application_id = a.id AND e.status = 'active' AND e.agent_reachable) AS endpoint_count
FROM applications a
LEFT JOIN locations l ON l.id = a.location_id
WHERE a.status <> 'retired' AND app_is_insider() AND app_can_use_application(a.id);

-- AI spend as the accountant sees it.
CREATE OR REPLACE VIEW mcp_ai_usage_postings WITH (security_barrier = true) AS
SELECT p.id AS ai_usage_posting_id, p.period_start, p.period_end, p.provider,
       p.model_id, mr.display_name AS model_name, p.department_id, d.name::text AS department_name,
       p.agent_member_id, m.display_name AS agent_name,
       p.call_count, p.input_tokens, p.output_tokens, p.cache_read_tokens, p.cache_write_tokens,
       p.amount, p.currency, p.expense_id, p.status, p.posted_at, p.note
FROM ai_usage_postings p
LEFT JOIN model_registry mr ON mr.id = p.model_id
LEFT JOIN departments d     ON d.id = p.department_id
LEFT JOIN members m         ON m.id = p.agent_member_id
WHERE app_is_insider() AND (app_has_module('ledger') OR app_has_module('expenses') OR app_is_super_admin());

CREATE OR REPLACE VIEW mcp_eval_schedules WITH (security_barrier = true) AS
SELECT sc.id AS eval_schedule_id, sc.eval_set_id, s.name AS eval_set_name, s.agent_member_id,
       sc.kind, sc.cadence, sc.sample_size, sc.regression_delta, sc.active,
       sc.next_run_at, sc.last_run_at, sc.last_eval_run_id
FROM eval_schedules sc
JOIN eval_sets s ON s.id = sc.eval_set_id
WHERE app_can_see_evals(s.agent_member_id);

-- An agent may read alerts raised about itself (it should know it is slipping); it still
-- cannot read the eval cases behind them.
CREATE OR REPLACE VIEW mcp_eval_alerts WITH (security_barrier = true) AS
SELECT al.id AS eval_alert_id, al.eval_set_id, s.name AS eval_set_name, al.agent_member_id,
       m.display_name AS agent_name, al.eval_run_id, al.schedule_id, al.kind, al.severity,
       al.score, al.baseline_score, al.detail, al.status, al.opened_at, al.acknowledged_by,
       al.acknowledged_at, al.resolved_at, al.resolution
FROM eval_alerts al
JOIN eval_sets s ON s.id = al.eval_set_id
LEFT JOIN members m ON m.id = al.agent_member_id
WHERE app_can_see_evals(al.agent_member_id);

GRANT SELECT ON mcp_applications, mcp_application_endpoints, mcp_application_access,
    mcp_my_applications, mcp_ai_usage_postings, mcp_eval_schedules, mcp_eval_alerts
TO app_records_ro;

-- ---------------------------------------------------------------------------
-- Seed: the standing departments and the platform's own application record
-- ---------------------------------------------------------------------------

INSERT INTO departments (name, description, is_system, system_key, home_location_id)
SELECT v.name, v.description, true, v.system_key,
       (SELECT id FROM locations WHERE kind = 'office' AND status = 'active'
         ORDER BY id LIMIT 1)
FROM (VALUES
    ('HR',
     'Tracks everyone who works here, human and agent: hiring, job descriptions, reviews, offboarding.',
     'hr'),
    ('Accounting',
     'Keeps the books and meters what the workforce costs, including model token usage.',
     'accounting'),
    ('Audit',
     'Runs the evaluations that prove agents still perform, and watches for degradation.',
     'audit')
) AS v(name, description, system_key)
WHERE NOT EXISTS (SELECT 1 FROM departments d WHERE d.system_key = v.system_key);

-- Every built-in module is registered as its own application at the Office, so an agent
-- asking "what can I reach?" gets Accounting, the CRM and the Calendar by name, access is
-- granted per application, and any one of them can later move to its own office without a
-- redesign. They share a codebase and a database today; the registry records where each one
-- runs, not how it is packaged. The module grant is what actually admits a member.
INSERT INTO applications (name, app_key, category, description, is_builtin, module,
                          is_self_hosted, location_id, url, status)
SELECT v.name, v.app_key, v.category, v.description, true, v.module, true,
       (SELECT id FROM locations WHERE kind = 'office' AND status = 'active' ORDER BY id LIMIT 1),
       v.url, 'active'
FROM (VALUES
    ('Business OS',   'platform',    'platform',      'The shell, dashboard, assistant command bar and MCP surface',      'dashboard',  '/'),
    ('CRM',           'crm',         'crm',           'Organizations, contacts, pipelines, deals and interactions',       'contacts',   '/contacts/'),
    ('Sales',         'sales',       'accounting',    'Quotes, invoices, payments and online collection',                 'sales',      '/sales/'),
    ('Books',         'books',       'accounting',    'Chart of accounts, journal, bank feeds and reconciliation',        'books',      '/books/'),
    ('Expenses',      'expenses',    'accounting',    'Vendors, expenses, bills and the accountant export',               'expenses',   '/expenses/'),
    ('Projects',      'projects',    'other',         'Projects, milestones, tasks and dependencies',                     'projects',   '/projects/'),
    ('Calendar',      'calendar',    'calendar',      'Appointments, crew, resources and availability',                   'scheduling', '/calendar/'),
    ('Time',          'time',        'other',         'Timers, time entries and billable hours',                          'time',       '/time/'),
    ('Helpdesk',      'helpdesk',    'communication', 'Tickets, SLAs and customer requests',                              'tickets',    '/tickets/'),
    ('Inbox',         'inbox',       'email',         'Shared mailboxes, threads and mail rules',                         'inbox',      '/inbox/'),
    ('Documents',     'documents',   'documents',     'Folders, documents, versions and full-text search',                'documents',  '/documents/'),
    ('Signatures',    'signatures',  'documents',     'Signature requests, signers and the audit trail',                  'signatures', '/signatures/'),
    ('Inventory',     'inventory',   'other',         'Products, stock locations, levels, movements and purchase orders', 'inventory',  '/inventory/'),
    ('People',        'people',      'other',         'Employment records, pay runs and leave',                           'people',     '/people/'),
    ('Agent HR',      'agent_hr',    'automation',    'Agent employee records, duties, grants and reviews',               'hr',         '/agents/'),
    ('Content',       'content',     'communication', 'Channels, campaigns, content items and metrics',                   'content',    '/content/'),
    ('Portal',        'portal',      'communication', 'Customer portal and public forms',                                 'portal',     '/portal/'),
    ('Reports',       'reports',     'other',         'Saved reports, schedules and dashboards',                          'reports',    '/reports/'),
    ('Estate',        'estate',      'platform',      'Buildings, offices, desks and the cross-location task queue',      'locations',  '/estate/'),
    ('Applications',  'applications','platform',      'The application registry itself: endpoints, access and health',    'applications', '/applications/'),
    ('AI Ops',        'ai_ops',      'automation',    'Prompt ledger, model registry, evals and the degradation watch',   'ledger',     '/ai/'),
    ('Approvals',     'approvals',   'automation',    'Approval policies and the manager approval queue',                 'approvals',  '/approvals/'),
    -- Team & Access is administered, not granted: there is no 'team' module grant, because
    -- who may touch it is decided by app_is_admin() and app_can_admin_member(). Its module is
    -- NULL for that reason, exactly like any application whose reach is not a module grant.
    ('Team & Access', 'team_access', 'platform',      'Members, departments, module grants, tokens and settings',         NULL,         '/team/')
) AS v(name, app_key, category, description, module, url)
WHERE NOT EXISTS (SELECT 1 FROM applications a WHERE a.app_key = v.app_key);

COMMIT;
