-- 131: Assets — one register of what the business owns and operates, physical and technical
-- (docs/build-specs/assets.md; plan approved by the owner 2026-09-21, all five defaults).
--
--   asset_categories   physical | technical, seeded and editable
--   assets             every asset belongs to a DEPARTMENT and sits at a LOCATION; it may have a
--                      custodian (a person or an agent), a parent asset (a database runs on a
--                      server), the applications row it stands behind (endpoints, access and health
--                      stay in Applications — an asset grants nothing), and the bookable resource
--                      it is booked as (booking stays in Calendar)
--   asset_movements    one row per change of department, location or custodian
--   asset_maintenance  work scheduled and work done
--
-- The 24th built-in module: application row `assets`, catalog entry, module grant `assets`, a
-- sidebar entry under Administration, and a section of app_my_work(). Its URL is /asset-register/ —
-- /assets/ is the static files directory (css, images) and can never be a screen.
-- Visibility (app_can_see_asset): mod:assets sees the register; a dept-admin their departments'
-- assets; a custodian what they hold. Money (purchase cost) only for the first two.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/131_assets.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- The module
-- ---------------------------------------------------------------------------
ALTER TABLE module_grants DROP CONSTRAINT module_grants_module_check;
ALTER TABLE module_grants ADD CONSTRAINT module_grants_module_check CHECK (module = ANY (ARRAY[
    'contacts', 'sales', 'expenses', 'projects', 'scheduling', 'tickets', 'documents', 'time', 'content', 'hr',
    'locations', 'applications', 'approvals', 'ledger', 'evals', 'books', 'inbox', 'people', 'inventory',
    'signatures', 'portal', 'reports', 'assets']));

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, category, sort_order)
SELECT 'assets', 'Assets', 'What the business owns and operates: physical and technical assets, by department and location',
       'feather-package', g.id, 'builtin', 'platform', 25
  FROM nav_groups g WHERE g.name = 'Administration';

INSERT INTO applications (name, app_key, category, description, is_self_hosted, is_builtin, module, location_id,
                          url, catalog_key, business_area_id)
SELECT 'Assets', 'assets', 'platform',
       'What the business owns and operates: physical and technical assets, by department and location',
       true, true, 'assets', (SELECT location_id FROM applications WHERE app_key = 'estate'),
       '/asset-register/', 'assets', g.id
  FROM nav_groups g WHERE g.name = 'Administration';

INSERT INTO nav_items (group_id, sort_order, item_key, label, url, icon, module, audience, phase, application_id)
SELECT g.id, 25, 'assets', 'Assets', '/asset-register/', 'feather-package', 'assets', 'everyone', 4,
       (SELECT id FROM applications WHERE app_key = 'assets')
  FROM nav_groups g WHERE g.name = 'Administration';

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
CREATE TABLE asset_categories (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_key         text NOT NULL UNIQUE,
    name                 text NOT NULL UNIQUE,
    asset_class          text NOT NULL CHECK (asset_class IN ('physical', 'technical')),
    icon                 text NOT NULL DEFAULT 'feather-package',
    useful_life_months   integer CHECK (useful_life_months > 0),     -- the default for a new asset
    sort_order           integer NOT NULL DEFAULT 0,
    archived_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE SEQUENCE asset_tag_seq;

CREATE TABLE assets (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_tag             text NOT NULL UNIQUE DEFAULT ('A-' || lpad(nextval('asset_tag_seq')::text, 4, '0')),
    name                  text NOT NULL,
    asset_class           text NOT NULL CHECK (asset_class IN ('physical', 'technical')),
    category_id           bigint NOT NULL REFERENCES asset_categories(id) ON DELETE RESTRICT,
    description           text,
    status                text NOT NULL DEFAULT 'in_service' CHECK (status IN
                              ('planned', 'in_service', 'in_repair', 'in_storage', 'retired', 'disposed', 'lost')),
    department_id         bigint NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,   -- who it belongs to
    location_id           bigint NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,     -- where it is
    custodian_member_id   bigint REFERENCES members(id) ON DELETE SET NULL,                -- a person or an agent
    parent_asset_id       bigint REFERENCES assets(id) ON DELETE SET NULL,
    application_id        bigint REFERENCES applications(id) ON DELETE SET NULL,           -- the application it stands behind
    bookable_resource_id  bigint REFERENCES bookable_resources(id) ON DELETE SET NULL,     -- how it is booked
    supplier_organization_id bigint REFERENCES organizations(id) ON DELETE SET NULL,
    manufacturer          text,                                  -- or vendor / project, for a technical asset
    model                 text,                                  -- or product / engine
    serial_number         text,                                  -- or licence key reference / account id — never a secret
    version               text,
    specs                 text,
    purchase_date         date,
    purchase_cost         numeric(14,2) CHECK (purchase_cost >= 0),
    currency              char(3),
    salvage_value         numeric(14,2) NOT NULL DEFAULT 0 CHECK (salvage_value >= 0),
    useful_life_months    integer CHECK (useful_life_months > 0),
    warranty_until        date,
    renewal_on            date,                                  -- licence, domain, certificate, subscription
    recurring_expense_id  bigint REFERENCES recurring_expenses(id) ON DELETE SET NULL,
    criticality           text NOT NULL DEFAULT 'normal' CHECK (criticality IN ('low', 'normal', 'high', 'critical')),
    last_verified_at      timestamptz,
    last_verified_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    disposed_on           date,
    disposal_note         text,
    notes                 text,
    created_by            bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (parent_asset_id IS NULL OR parent_asset_id <> id),
    CHECK (purchase_cost IS NULL OR currency IS NOT NULL)
);
CREATE INDEX assets_department_idx ON assets (department_id, status);
CREATE INDEX assets_location_idx   ON assets (location_id, status);
CREATE INDEX assets_custodian_idx  ON assets (custodian_member_id);
CREATE INDEX assets_category_idx   ON assets (category_id);
CREATE INDEX assets_parent_idx     ON assets (parent_asset_id);
CREATE INDEX assets_application_idx ON assets (application_id);
CREATE INDEX assets_resource_idx   ON assets (bookable_resource_id);
CREATE INDEX assets_supplier_idx   ON assets (supplier_organization_id);
CREATE INDEX assets_expense_idx    ON assets (recurring_expense_id);
CREATE INDEX assets_verified_by_idx ON assets (last_verified_by);
CREATE INDEX assets_created_by_idx ON assets (created_by);
CREATE INDEX assets_due_idx        ON assets (renewal_on, warranty_until);

CREATE TABLE asset_movements (
    id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id                  bigint NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    from_department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    to_department_id          bigint REFERENCES departments(id) ON DELETE SET NULL,
    from_location_id          bigint REFERENCES locations(id) ON DELETE SET NULL,
    to_location_id            bigint REFERENCES locations(id) ON DELETE SET NULL,
    from_custodian_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    to_custodian_member_id    bigint REFERENCES members(id) ON DELETE SET NULL,
    note                      text,
    moved_by                  bigint REFERENCES members(id) ON DELETE SET NULL,
    moved_at                  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX asset_movements_asset_idx ON asset_movements (asset_id, moved_at DESC);

CREATE TABLE asset_maintenance (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id      bigint NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    kind          text NOT NULL,                       -- 'service', 'backup test', 'upgrade', 'renewal', 'inspection' …
    due_on        date NOT NULL,
    done_on       date,
    cost          numeric(14,2) CHECK (cost >= 0),
    currency      char(3),
    note          text,
    done_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    created_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (cost IS NULL OR currency IS NOT NULL)
);
CREATE INDEX asset_maintenance_asset_idx ON asset_maintenance (asset_id, due_on);
CREATE INDEX asset_maintenance_open_idx  ON asset_maintenance (due_on) WHERE done_on IS NULL;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['asset_categories', 'assets', 'asset_movements', 'asset_maintenance'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)', t || '_app_rw', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['asset_categories', 'assets', 'asset_maintenance'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()', t || '_touch', t);
    END LOOP;
END$$;
GRANT USAGE ON SEQUENCE asset_tag_seq TO app_rw;

-- ---------------------------------------------------------------------------
-- Who sees an asset, and who sees what it cost
-- ---------------------------------------------------------------------------
CREATE FUNCTION app_can_see_asset(p_custodian_member_id bigint, p_department_id bigint) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN app_current_member_id() IS NULL THEN false
        WHEN NOT app_module_enabled('assets') THEN false
        WHEN app_is_external() THEN false
        WHEN app_is_super_admin() OR app_has_module('assets') THEN true
        WHEN p_department_id = ANY (app_admin_department_ids()) THEN true
        ELSE p_custodian_member_id IS NOT NULL AND p_custodian_member_id = app_current_member_id()
    END;
$$;
CREATE FUNCTION app_can_manage_asset(p_department_id bigint) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT app_module_enabled('assets') AND NOT app_is_external()
       AND (app_is_super_admin() OR app_has_module('assets') OR p_department_id = ANY (app_admin_department_ids()));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_asset(bigint, bigint), app_can_manage_asset(bigint) TO app_rw, app_records_ro;

-- ---------------------------------------------------------------------------
-- Read surface
-- ---------------------------------------------------------------------------
CREATE VIEW mcp_asset_categories WITH (security_barrier = true) AS
 SELECT c.id AS asset_category_id, c.category_key, c.name, c.asset_class, c.icon, c.useful_life_months,
        c.sort_order, c.archived_at
   FROM asset_categories c
  WHERE app_is_insider();

CREATE VIEW mcp_assets WITH (security_barrier = true) AS
 SELECT a.id AS asset_id, a.asset_tag, a.name, a.asset_class,
        a.category_id, c.name AS category_name, c.icon AS category_icon,
        a.description, a.status,
        a.department_id, d.name::text AS department_name,
        a.location_id, l.name AS location_name, l.kind AS location_kind,
        a.custodian_member_id, cm.display_name AS custodian_name, cm.member_kind AS custodian_kind,
        a.parent_asset_id, pa.name AS parent_asset_name, pa.asset_tag AS parent_asset_tag,
        a.application_id, ap.name AS application_name,
        a.bookable_resource_id, br.name AS bookable_resource_name,
        a.supplier_organization_id, o.name AS supplier_name,
        a.manufacturer, a.model, a.serial_number, a.version, a.specs,
        a.purchase_date,
        CASE WHEN app_can_manage_asset(a.department_id) THEN a.purchase_cost END AS purchase_cost,
        CASE WHEN app_can_manage_asset(a.department_id) THEN a.currency END AS currency,
        CASE WHEN app_can_manage_asset(a.department_id) THEN a.salvage_value END AS salvage_value,
        a.useful_life_months, a.warranty_until, a.renewal_on,
        CASE WHEN app_can_manage_asset(a.department_id) THEN a.recurring_expense_id END AS recurring_expense_id,
        a.criticality, a.last_verified_at, a.last_verified_by, vm.display_name AS last_verified_by_name,
        a.disposed_on, a.disposal_note, a.notes,
        app_can_manage_asset(a.department_id) AS i_can_manage,
        a.created_at, a.updated_at
   FROM assets a
   JOIN asset_categories c ON c.id = a.category_id
   JOIN departments d ON d.id = a.department_id
   JOIN locations l ON l.id = a.location_id
   LEFT JOIN members cm ON cm.id = a.custodian_member_id
   LEFT JOIN assets pa ON pa.id = a.parent_asset_id
   LEFT JOIN applications ap ON ap.id = a.application_id
   LEFT JOIN bookable_resources br ON br.id = a.bookable_resource_id
   LEFT JOIN organizations o ON o.id = a.supplier_organization_id
   LEFT JOIN members vm ON vm.id = a.last_verified_by
  WHERE app_can_see_asset(a.custodian_member_id, a.department_id);

CREATE VIEW mcp_asset_movements WITH (security_barrier = true) AS
 SELECT m.id AS asset_movement_id, m.asset_id,
        m.from_department_id, fd.name::text AS from_department_name, m.to_department_id, td.name::text AS to_department_name,
        m.from_location_id, fl.name AS from_location_name, m.to_location_id, tl.name AS to_location_name,
        m.from_custodian_member_id, fc.display_name AS from_custodian_name,
        m.to_custodian_member_id, tc.display_name AS to_custodian_name,
        m.note, m.moved_by, mb.display_name AS moved_by_name, m.moved_at
   FROM asset_movements m
   JOIN assets a ON a.id = m.asset_id
   LEFT JOIN departments fd ON fd.id = m.from_department_id
   LEFT JOIN departments td ON td.id = m.to_department_id
   LEFT JOIN locations fl ON fl.id = m.from_location_id
   LEFT JOIN locations tl ON tl.id = m.to_location_id
   LEFT JOIN members fc ON fc.id = m.from_custodian_member_id
   LEFT JOIN members tc ON tc.id = m.to_custodian_member_id
   LEFT JOIN members mb ON mb.id = m.moved_by
  WHERE app_can_see_asset(a.custodian_member_id, a.department_id);

CREATE VIEW mcp_asset_maintenance WITH (security_barrier = true) AS
 SELECT m.id AS asset_maintenance_id, m.asset_id, m.kind, m.due_on, m.done_on,
        CASE WHEN app_can_manage_asset(a.department_id) THEN m.cost END AS cost,
        CASE WHEN app_can_manage_asset(a.department_id) THEN m.currency END AS currency,
        m.note, m.done_by, db.display_name AS done_by_name, m.created_at
   FROM asset_maintenance m
   JOIN assets a ON a.id = m.asset_id
   LEFT JOIN members db ON db.id = m.done_by
  WHERE app_can_see_asset(a.custodian_member_id, a.department_id);

GRANT SELECT ON mcp_asset_categories, mcp_assets, mcp_asset_movements, mcp_asset_maintenance TO app_rw, app_records_ro;

-- ---------------------------------------------------------------------------
-- Seed: categories, and the two technical assets the platform itself stands on
-- ---------------------------------------------------------------------------
INSERT INTO asset_categories (category_key, name, asset_class, icon, useful_life_months, sort_order) VALUES
    ('computers',     'Computers & laptops',              'physical',  'feather-monitor',     36,  10),
    ('phones',        'Phones & tablets',                 'physical',  'feather-smartphone',  24,  20),
    ('servers',       'Servers & network gear',           'physical',  'feather-server',      60,  30),
    ('peripherals',   'Printers & peripherals',           'physical',  'feather-printer',     48,  40),
    ('vehicles',      'Vehicles',                         'physical',  'feather-truck',       60,  50),
    ('furniture',     'Furniture & fixtures',             'physical',  'feather-box',         84,  60),
    ('equipment',     'Tools & equipment',                'physical',  'feather-tool',        60,  70),
    ('premises',      'Rooms & premises',                 'physical',  'feather-home',        NULL, 80),
    ('databases',     'Relational databases',             'technical', 'feather-database',    NULL, 110),
    ('memory',        'Memory systems',                   'technical', 'feather-layers',      NULL, 120),
    ('mcp_apis',      'MCP servers & APIs',               'technical', 'feather-share-2',     NULL, 130),
    ('ai_models',     'AI models & provider accounts',    'technical', 'feather-cpu',         NULL, 140),
    ('domains',       'Domains & DNS',                    'technical', 'feather-globe',       NULL, 150),
    ('certificates',  'Certificates & keys',              'technical', 'feather-key',         NULL, 160),
    ('licences',      'Software licences & subscriptions','technical', 'feather-award',       NULL, 170),
    ('cloud',         'Cloud & hosting accounts',         'technical', 'feather-cloud',       NULL, 180),
    ('backups',       'Backups & storage',                'technical', 'feather-hard-drive',  NULL, 190),
    ('repositories',  'Code repositories',                'technical', 'feather-git-branch',  NULL, 200);

INSERT INTO assets (name, asset_class, category_id, description, department_id, location_id, application_id,
                    manufacturer, model, version, criticality)
SELECT v.name, 'technical', c.id, v.description,
       COALESCE((SELECT id FROM departments WHERE name = 'IT' AND archived_at IS NULL),
                (SELECT id FROM departments WHERE system_key = 'front_office')),
       COALESCE(ap.location_id, (SELECT location_id FROM applications WHERE app_key = 'estate')),
       ap.id, v.manufacturer, v.model, v.version, 'critical'
  FROM (VALUES
        ('PostgreSQL 17', 'databases', 'postgres', 'The record memory: every business record the platform keeps', 'PostgreSQL', 'PostgreSQL', '17'),
        ('MaluDB memory', 'memory',    'maludb',   'The activity memory: what happened, as episodes',            'MaluDB',     'MaluDB',     NULL)
       ) AS v(name, category_key, app_key, description, manufacturer, model, version)
  JOIN asset_categories c ON c.category_key = v.category_key
  LEFT JOIN applications ap ON ap.app_key = v.app_key;

-- Disposing of an asset is an agent's to ask, a person's to approve.
INSERT INTO approval_policies (name, category, action_pattern, applies_to)
VALUES ('Agents: disposing of an asset', 'deletion', 'asset.dispose', 'agents');

-- ---------------------------------------------------------------------------
-- My Work: what is due on the assets you hold or look after
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.app_my_work(p_horizon_days integer DEFAULT 7, p_limit integer DEFAULT 10)
 RETURNS TABLE(section text, waiting boolean, kind text, id bigint, title text, detail text, due_at timestamp with time zone, state text, href text, urgency integer, total bigint)
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'public'
AS $function$
DECLARE
    me bigint := app_current_member_id();
    horizon integer := least(greatest(coalesce(p_horizon_days, 7), 1), 60);
    lim integer := least(greatest(coalesce(p_limit, 10), 1), 50);
BEGIN
    IF me IS NULL THEN
        RETURN;
    END IF;

    BEGIN RETURN QUERY
        SELECT 'approvals_to_decide', true, 'approval_request', r.approval_request_id, r.summary,
               'asked by ' || coalesce(r.requested_by_name, 'someone'), r.expires_at, 'pending'::text,
               '/approvals/' || r.approval_request_id, 0, count(*) OVER ()
          FROM mcp_approval_requests r WHERE r.status = 'pending' AND r.approver_member_id = me
         ORDER BY r.expires_at NULLS LAST, r.created_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work approvals_to_decide: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'time_to_approve', true, 'time_week', w.member_id, w.member_name || ' — week of ' || to_char(w.week_start, 'DD Mon'),
               round(w.minutes / 60.0, 1) || ' h in ' || w.entries || ' entries', NULL::timestamptz, 'submitted'::text,
               '/time/approvals?week=' || to_char(w.week_start, 'YYYY-MM-DD'), 0, count(*) OVER ()
          FROM (SELECT te.member_id, te.member_name, date_trunc('week', te.entry_date)::date AS week_start,
                       sum(te.minutes) AS minutes, count(*) AS entries
                  FROM mcp_time_entries te
                 WHERE te.status = 'submitted' AND te.member_id <> me AND (app_is_admin() OR app_has_module('time'))
                 GROUP BY 1, 2, 3) w
         ORDER BY w.week_start, w.member_name LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work time_to_approve: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'appointments_to_answer', true, 'appointment', a.appointment_id, a.title,
               CASE WHEN a.recurrence_rule IS NOT NULL THEN 'a repeating appointment' ELSE a.organization_name END,
               CASE WHEN a.recurrence_rule IS NULL THEN a.starts_at END, 'no answer yet'::text,
               '/schedule/' || a.appointment_id, 0, count(*) OVER ()
          FROM mcp_appointment_assignees aa JOIN mcp_appointments a ON a.appointment_id = aa.appointment_id
         WHERE aa.member_id = me AND aa.response = 'pending' AND a.status IN ('scheduled', 'confirmed') AND a.recurrence_parent_id IS NULL
           AND (a.starts_at >= now() OR a.recurrence_rule IS NOT NULL)
         ORDER BY a.starts_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work appointments_to_answer: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'tickets', true, 'ticket', x.ticket_id, x.number || ' — ' || x.subject, x.organization_name, x.due, x.sla,
               '/tickets/' || x.ticket_id,
               CASE x.sla WHEN 'breached' THEN 0 WHEN 'due_soon' THEN 1 ELSE 2 END, count(*) OVER ()
          FROM (SELECT t.*, d.due,
                       CASE WHEN t.status IN ('pending', 'on_hold') THEN 'paused'
                            WHEN d.due IS NULL THEN t.status
                            WHEN d.due < now() THEN 'breached'
                            WHEN d.due < now() + interval '2 hours' THEN 'due_soon' ELSE 'on_track' END AS sla
                  FROM mcp_tickets t
                  CROSS JOIN LATERAL (SELECT CASE WHEN t.first_responded_at IS NULL AND t.first_response_due_at IS NOT NULL
                                                  THEN least(t.first_response_due_at, coalesce(t.resolution_due_at, t.first_response_due_at))
                                                  ELSE t.resolution_due_at END AS due) d
                 WHERE t.assignee_member_id = me AND t.status NOT IN ('resolved', 'closed')) x
         ORDER BY 10, array_position(ARRAY['urgent', 'high', 'normal', 'low'], x.priority), x.due NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work tickets: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'mail', true, 'mail_thread', t.mail_thread_id, t.subject, t.mailbox_name || coalesce(' · ' || t.organization_name, ''),
               t.last_message_at, 'waiting on us'::text, '/inbox/threads/' || t.mail_thread_id, 0, count(*) OVER ()
          FROM mcp_mail_threads t
         WHERE t.assigned_member_id = me AND t.status = 'open' AND t.last_direction = 'inbound' AND t.message_count > 0
         ORDER BY t.last_message_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work mail: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'content_to_review', true, 'content_item', c.content_item_id, c.title,
               'by ' || coalesce(c.author_name, 'someone') || coalesce(' · ' || c.campaign_name, ''), c.updated_at, 'in review'::text,
               '/content/' || c.content_item_id, 0, count(*) OVER ()
          FROM mcp_content_items c WHERE c.status = 'in_review' AND c.reviewer_member_id = me
         ORDER BY c.updated_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work content_to_review: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'leave_to_decide', true, 'leave_request', l.leave_request_id, l.display_name || ' — ' || l.leave_type,
               to_char(l.start_date, 'DD Mon') || ' – ' || to_char(l.end_date, 'DD Mon') || ' · ' || l.days || ' d', l.start_date::timestamptz, 'requested'::text,
               '/people/leave/' || l.leave_request_id, 0, count(*) OVER ()
          FROM mcp_leave_requests l
         WHERE l.status = 'requested' AND l.member_id <> me
           AND (app_is_super_admin() OR (app_has_module('people') AND app_can_admin_member(l.member_id)))
         ORDER BY l.start_date LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work leave_to_decide: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'form_submissions', true, 'form_submission', s.form_submission_id, s.form_name, NULL::text, s.submitted_at, 'new'::text,
               '/forms/submissions/' || s.form_submission_id, 0, count(*) OVER ()
          FROM mcp_form_submissions s JOIN mcp_forms f ON f.form_id = s.form_id
         WHERE s.status = 'new' AND f.assign_member_id = me
         ORDER BY s.submitted_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work form_submissions: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'tasks', true, 'task', t.task_id, t.title, t.project_name, t.due_date::timestamptz,
               CASE WHEN t.status = 'blocked' OR t.has_open_dependencies THEN 'blocked'
                    WHEN t.due_date < current_date THEN 'overdue' WHEN t.due_date = current_date THEN 'due today' ELSE 'due' END,
               '/tasks/' || t.task_id, CASE WHEN t.due_date < current_date THEN 0 WHEN t.due_date = current_date THEN 1 ELSE 2 END, count(*) OVER ()
          FROM mcp_tasks t
         WHERE t.assignee_member_id = me AND t.status NOT IN ('done', 'cancelled') AND t.due_date IS NOT NULL AND t.due_date <= current_date + horizon
         ORDER BY t.due_date, t.priority DESC LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work tasks: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'invoices_overdue', true, 'invoice', i.invoice_id, i.number || coalesce(' — ' || i.organization_name, ''),
               i.balance_due || ' ' || i.currency || ' outstanding', i.due_date::timestamptz, i.days_overdue || ' days overdue',
               '/invoices/' || i.invoice_id, 0, count(*) OVER ()
          FROM mcp_invoices i
         WHERE i.owner_member_id = me AND i.voided_at IS NULL AND i.status <> 'draft' AND i.balance_due > 0 AND i.days_overdue > 0
         ORDER BY i.days_overdue DESC LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work invoices_overdue: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'time_mine', true, 'time_week', to_char(w.week_start, 'YYYYMMDD')::bigint, 'Week of ' || to_char(w.week_start, 'DD Mon'),
               round(w.minutes / 60.0, 1) || ' h', NULL::timestamptz, w.state, '/time?week=' || to_char(w.week_start, 'YYYY-MM-DD'),
               CASE w.state WHEN 'rejected' THEN 0 ELSE 1 END, count(*) OVER ()
          FROM (SELECT date_trunc('week', te.entry_date)::date AS week_start, sum(te.minutes) AS minutes,
                       CASE WHEN bool_or(te.status = 'rejected') THEN 'rejected' ELSE 'not submitted' END AS state
                  FROM mcp_time_entries te
                 WHERE te.member_id = me AND te.entry_date >= current_date - 60
                   AND (te.status = 'rejected' OR (te.status = 'draft' AND te.entry_date < date_trunc('week', current_date)::date))
                 GROUP BY 1) w
         ORDER BY 10, w.week_start LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work time_mine: %', SQLERRM; END;

    -- Coming up, or waiting on someone else: shown, not counted.
    BEGIN RETURN QUERY
        SELECT 'approvals_mine', false, 'approval_request', r.approval_request_id, r.summary,
               'waiting for ' || coalesce(r.approver_name, 'an approver'), r.expires_at, 'pending'::text,
               '/approvals/' || r.approval_request_id, 0, count(*) OVER ()
          FROM mcp_approval_requests r WHERE r.status = 'pending' AND r.requested_by_member_id = me
         ORDER BY r.created_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work approvals_mine: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'purchase_orders', false, 'purchase_order', p.purchase_order_id, p.po_number || coalesce(' — ' || p.vendor_name, ''),
               CASE p.status WHEN 'partial' THEN 'partly received' ELSE 'sent' END, p.expected_date::timestamptz,
               CASE WHEN p.expected_date < current_date THEN 'late' ELSE 'awaiting receipt' END,
               '/inventory/orders/' || p.purchase_order_id, CASE WHEN p.expected_date < current_date THEN 0 ELSE 1 END, count(*) OVER ()
          FROM mcp_purchase_orders p WHERE p.owner_member_id = me AND p.status IN ('sent', 'partial')
         ORDER BY 10, p.expected_date NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work purchase_orders: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'signatures_out', false, 'signature_request', s.signature_request_id, s.subject,
               s.signed_count || ' of ' || s.signer_count || ' signed' || coalesce(' · ' || s.organization_name, ''), s.expires_at,
               CASE s.status WHEN 'partially_signed' THEN 'partly signed' ELSE 'sent' END,
               '/signatures/' || s.signature_request_id, 0, count(*) OVER ()
          FROM mcp_signature_requests s WHERE s.owner_member_id = me AND s.status IN ('sent', 'partially_signed')
         ORDER BY s.expires_at NULLS LAST, s.sent_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work signatures_out: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'leave_mine', false, 'leave_request', l.leave_request_id, l.leave_type,
               to_char(l.start_date, 'DD Mon') || ' – ' || to_char(l.end_date, 'DD Mon') || ' · ' || l.days || ' d', l.start_date::timestamptz,
               l.status, '/people/leave/' || l.leave_request_id, 0, count(*) OVER ()
          FROM mcp_leave_requests l
         WHERE l.member_id = me AND ((l.status = 'approved' AND l.end_date >= current_date AND l.start_date <= current_date + horizon) OR l.status = 'requested')
         ORDER BY l.start_date LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work leave_mine: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'duties', false, 'agent_duty', d.duty_id, d.name, d.schedule_cron, d.next_run_at, 'scheduled'::text,
               '/agents/' || d.agent_member_id, 0, count(*) OVER ()
          FROM mcp_agent_duties d WHERE d.agent_member_id = me AND d.active
         ORDER BY d.next_run_at NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work duties: %', SQLERRM; END;
    BEGIN RETURN QUERY
        SELECT 'assets_due', true, 'asset', x.asset_id, x.asset_tag || ' — ' || x.name, x.what, x.due::timestamptz, x.state,
               '/asset-register/' || x.asset_id || x.tab, CASE WHEN x.due < current_date THEN 0 ELSE 1 END, count(*) OVER ()
          FROM (SELECT a.asset_id, a.asset_tag, a.name, 'maintenance: ' || m.kind AS what, m.due_on AS due,
                       CASE WHEN m.due_on < current_date THEN 'overdue' ELSE 'due' END AS state, '?tab=maintenance' AS tab
                  FROM mcp_asset_maintenance m JOIN mcp_assets a ON a.asset_id = m.asset_id
                 WHERE m.done_on IS NULL AND m.due_on <= current_date + greatest(horizon, 30)
                   AND a.status NOT IN ('retired', 'disposed', 'lost')
                   AND (a.custodian_member_id = me OR a.department_id = ANY (app_admin_department_ids()) OR app_has_module('assets'))
                UNION ALL
                SELECT a.asset_id, a.asset_tag, a.name, 'warranty ends', a.warranty_until,
                       CASE WHEN a.warranty_until < current_date THEN 'ended' ELSE 'ending' END, ''
                  FROM mcp_assets a
                 WHERE a.warranty_until BETWEEN current_date - 7 AND current_date + greatest(horizon, 30)
                   AND a.status NOT IN ('retired', 'disposed', 'lost')
                   AND (a.custodian_member_id = me OR a.department_id = ANY (app_admin_department_ids()) OR app_has_module('assets'))
                UNION ALL
                SELECT a.asset_id, a.asset_tag, a.name, 'renewal', a.renewal_on,
                       CASE WHEN a.renewal_on < current_date THEN 'overdue' ELSE 'due' END, ''
                  FROM mcp_assets a
                 WHERE a.renewal_on <= current_date + greatest(horizon, 30)
                   AND a.status NOT IN ('retired', 'disposed', 'lost')
                   AND (a.custodian_member_id = me OR a.department_id = ANY (app_admin_department_ids()) OR app_has_module('assets'))) x
         ORDER BY x.due LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work assets_due: %', SQLERRM; END;
END;
$function$;

COMMIT;
