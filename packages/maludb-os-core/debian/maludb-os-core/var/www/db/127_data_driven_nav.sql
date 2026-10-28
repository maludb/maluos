-- 127: the sidebar becomes data (docs/build-specs/data-driven-nav.md, step 1).
--
-- The menu was a PHP array, module_catalog() in app/business.php: adding an application meant a
-- deploy, a business could not switch off what it does not use, and the grouping was frozen in
-- code. Three tables and one gatherer replace it:
--
--   nav_groups          the headings ('' = the unheaded top group: what a person opens every day)
--   nav_items           one row per sidebar entry, tied to its applications row
--   member_nav_hidden   a person's own "I do not use this" (hide only — owner, 2026-09-20)
--   app_nav()           the signed-in member's menu, in order. ONE gatherer, as app_my_work() is:
--                       the session endpoint, the MCP tool and the settings preview all call it.
--
-- An entry has one of THREE statuses (owner, 2026-09-20):
--   active    in the sidebar, usable by people, agents and MCP
--   hidden    not in the sidebar; still works for agents and MCP
--   disabled  not in the sidebar and closed to agents and MCP (enforcement lands with the
--             settings screen, step 3 — until then nothing can set it)
-- Only a super-admin arranges the menu. A locked entry (Dashboard, My Work, Settings) stays
-- active: nobody can switch off the screen that switches things back on.
--
-- Seeded with today's catalog exactly, so the menu is unchanged by this migration.
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/127_data_driven_nav.sql

BEGIN;

CREATE TABLE nav_groups (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text        NOT NULL UNIQUE,            -- '' = no heading
    sort_order  integer     NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE nav_items (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_key        text        NOT NULL UNIQUE,        -- immutable: nav-<key> DOM ids, smokes, active-nav
    application_id  bigint      REFERENCES applications(id) ON DELETE CASCADE,
    group_id        bigint      NOT NULL REFERENCES nav_groups(id) ON DELETE RESTRICT,
    sort_order      integer     NOT NULL DEFAULT 0,
    label           text        NOT NULL,
    icon            text        NOT NULL DEFAULT 'feather-grid',
    url             text        NOT NULL,
    opens           text        NOT NULL DEFAULT 'same'     CHECK (opens IN ('same', 'new_tab')),
    module          text,                                   -- the module grant that admits; NULL = none needed
    audience        text        NOT NULL DEFAULT 'everyone' CHECK (audience IN ('everyone', 'internal', 'admin')),
    active_patterns text[]      NOT NULL DEFAULT '{}',      -- other paths that light this entry up
    status          text        NOT NULL DEFAULT 'active'   CHECK (status IN ('active', 'hidden', 'disabled')),
    is_locked       boolean     NOT NULL DEFAULT false,
    phase           smallint,                               -- build-plan phase of a built-in; NULL for added applications
    created_by      bigint      REFERENCES members(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT nav_items_locked_stays_active CHECK (NOT is_locked OR status = 'active')
);
CREATE INDEX nav_items_group_idx       ON nav_items (group_id, sort_order);
CREATE INDEX nav_items_application_idx ON nav_items (application_id);
CREATE INDEX nav_items_created_by_idx  ON nav_items (created_by);

CREATE TABLE member_nav_hidden (
    member_id   bigint      NOT NULL REFERENCES members(id)   ON DELETE CASCADE,
    nav_item_id bigint      NOT NULL REFERENCES nav_items(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, nav_item_id)
);
CREATE INDEX member_nav_hidden_item_idx ON member_nav_hidden (nav_item_id);

-- RLS + updated_at, as in 055
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['nav_groups', 'nav_items', 'member_nav_hidden'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['nav_groups', 'nav_items'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- ---------------------------------------------------------------------------
-- Seed: today's catalog, in today's order (Option A grouping, d493352)
-- ---------------------------------------------------------------------------
INSERT INTO nav_groups (name, sort_order) VALUES
    ('',                10),
    ('Sales & Service', 20),
    ('Finance',         30),
    ('Operations',      40),
    ('Human Resources', 50),
    ('Administration',  60);

INSERT INTO nav_items (group_id, sort_order, item_key, label, url, icon, module, audience, phase, is_locked, application_id, active_patterns)
SELECT g.id, v.sort_order, v.item_key, v.label, v.url, v.icon, v.module, v.audience, v.phase, v.is_locked, a.id, v.active_patterns
  FROM (VALUES
    -- group,            order, key,            label,              url,                  icon,                   module,        audience,   phase, locked, app_key,        active patterns
    ('',                 10, 'dashboard',    'Dashboard',        '/',                  'feather-home',         NULL,          'everyone', 1, true,  'platform',     '{}'::text[]),
    ('',                 20, 'my-work',      'My Work',          '/my-work',           'feather-check-square', NULL,          'everyone', 3, true,  'platform',     '{/tasks}'),
    ('',                 30, 'schedule',     'Calendar',         '/schedule/',         'feather-calendar',     'scheduling',  'everyone', 3, false, 'calendar',     '{}'),
    ('',                 40, 'inbox',        'Inbox',            '/inbox/',            'feather-inbox',        'inbox',       'everyone', 3, false, 'inbox',        '{}'),
    ('',                 50, 'approvals',    'Approvals',        '/approvals/',        'feather-check-circle', 'approvals',   'everyone', 5, false, 'approvals',    '{}'),

    ('Sales & Service',  10, 'contacts',     'Contacts & CRM',   '/contacts/',         'feather-users',        'contacts',    'everyone', 1, false, 'crm',          '{/interactions}'),
    ('Sales & Service',  20, 'deals',        'Deals',            '/deals/',            'feather-trending-up',  'contacts',    'everyone', 1, false, 'crm',          '{}'),
    ('Sales & Service',  30, 'invoices',     'Sales & Invoices', '/invoices/',         'feather-file-text',    'sales',       'everyone', 2, false, 'sales',        '{/quotes,/payments,/sales}'),
    ('Sales & Service',  40, 'tickets',      'Helpdesk',         '/tickets/',          'feather-life-buoy',    'tickets',     'everyone', 3, false, 'helpdesk',     '{}'),
    ('Sales & Service',  50, 'forms',        'Portal & Forms',   '/forms/',            'feather-globe',        'portal',      'everyone', 4, false, 'portal',       '{}'),

    ('Finance',          10, 'books',        'Books',            '/books/',            'feather-book',         'books',       'everyone', 2, false, 'books',        '{}'),
    ('Finance',          20, 'expenses',     'Expenses',         '/expenses/',         'feather-credit-card',  'expenses',    'everyone', 2, false, 'expenses',     '{}'),
    ('Finance',          30, 'reports',      'Reports',          '/reports/',          'feather-bar-chart-2',  'reports',     'everyone', 4, false, 'reports',      '{}'),

    ('Operations',       10, 'projects',     'Projects & Tasks', '/projects/',         'feather-clipboard',    'projects',    'everyone', 3, false, 'projects',     '{}'),
    ('Operations',       20, 'time',         'Time',             '/time/',             'feather-clock',        'time',        'everyone', 3, false, 'time',         '{}'),
    ('Operations',       30, 'inventory',    'Products & Stock', '/inventory/',        'feather-package',      'inventory',   'everyone', 2, false, 'inventory',    '{}'),
    ('Operations',       40, 'documents',    'Documents',        '/documents/',        'feather-folder',       'documents',   'everyone', 4, false, 'documents',    '{}'),
    ('Operations',       50, 'signatures',   'Signatures',       '/signatures/',       'feather-edit',         'signatures',  'everyone', 4, false, 'signatures',   '{}'),
    ('Operations',       60, 'content',      'Content',          '/content/',          'feather-edit-3',       'content',     'everyone', 3, false, 'content',      '{}'),

    ('Human Resources',  10, 'people',       'People',           '/people/',           'feather-user-check',   'people',      'admin',    5, false, 'people',       '{}'),
    ('Human Resources',  20, 'agents',       'Agent Workforce',  '/agents/',           'feather-users',        'hr',          'everyone', 5, false, 'agent_hr',     '{/team}'),
    ('Human Resources',  30, 'departments',  'Departments',      '/team/departments',  'feather-layers',       NULL,          'admin',    1, false, 'team_access',  '{}'),

    ('Administration',   10, 'company',      'Company',          '/company/',          'feather-briefcase',    NULL,          'internal', 4, false, 'platform',     '{}'),
    ('Administration',   20, 'estate',       'Work Locations',   '/locations/',        'feather-server',       'locations',   'everyone', 4, false, 'estate',       '{}'),
    ('Administration',   30, 'applications', 'Applications',     '/applications/',     'feather-grid',         'applications','everyone', 4, false, 'applications', '{}'),
    ('Administration',   40, 'ai',           'AI Ops',           '/ai/prompt-log',     'feather-activity',     'ledger',      'everyone', 5, false, 'ai_ops',       '{/ai}'),
    ('Administration',   50, 'activity',     'Activity',         '/activity',          'feather-activity',     NULL,          'everyone', 1, false, 'platform',     '{}'),
    ('Administration',   60, 'settings',     'Settings',         '/settings/',         'feather-settings',     NULL,          'everyone', 1, true,  'platform',     '{}')
  ) AS v(group_name, sort_order, item_key, label, url, icon, module, audience, phase, is_locked, app_key, active_patterns)
  JOIN nav_groups g ON g.name = v.group_name
  LEFT JOIN applications a ON a.app_key = v.app_key;

-- ---------------------------------------------------------------------------
-- The gatherer. The rule is the old nav_modules() rule, unchanged:
--   admin entries    → super-admin or dept-admin
--   internal entries → anyone who is not external
--   a module entry   → the module grant, or an admin (require_module() admits any dept-admin)
-- plus two that the array could not express: an entry for an EXTERNAL application needs a live
-- access grant (app_can_use_application), and a person's own hidden entries are left out.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_nav()
RETURNS TABLE (group_name text, item_key text, label text, url text, icon text, phase smallint,
               opens text, active_patterns text[], nav_item_id bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT g.name, i.item_key, i.label, i.url, i.icon, i.phase, i.opens, i.active_patterns, i.id
      FROM nav_items i
      JOIN nav_groups g ON g.id = i.group_id
      LEFT JOIN applications a ON a.id = i.application_id
     WHERE app_current_member_id() IS NOT NULL
       AND i.status = 'active'
       AND (a.id IS NULL OR a.status <> 'retired')
       AND CASE i.audience
               WHEN 'admin'    THEN app_is_admin()
               WHEN 'internal' THEN NOT app_is_external()
               ELSE i.module IS NULL OR app_has_module(i.module) OR app_is_admin()
           END
       AND (a.id IS NULL OR a.is_builtin OR app_can_use_application(a.id))
       AND NOT EXISTS (SELECT 1 FROM member_nav_hidden h
                        WHERE h.nav_item_id = i.id AND h.member_id = app_current_member_id())
     ORDER BY g.sort_order, g.id, i.sort_order, i.id;
$$;
GRANT EXECUTE ON FUNCTION app_nav() TO app_rw, app_records_ro;

COMMIT;
