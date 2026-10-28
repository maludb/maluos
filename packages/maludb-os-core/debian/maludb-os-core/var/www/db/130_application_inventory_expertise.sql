-- 130: the application inventory, business areas, and an application's expertise
-- (docs/build-specs/applications.md, "Inventory and expertise"; approved by the owner 2026-09-21).
--
--   application_catalog   everything a business COULD run: the built-in modules and a curated list
--                         of outside products. An entry is ACTIVE when an applications row that
--                         carries its key is running; otherwise it is merely available.
--   applications          + catalog_key, business_area_id (a nav_groups row — the menu and the
--                         Applications page share one vocabulary), sme_agent_member_id (the agent
--                         that is the subject matter expert; never a grant of access).
--   skill_assignments     + scope 'application': a skill that belongs to an application reaches the
--                         application's expert and every agent that may use the application.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/130_application_inventory_expertise.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- Business areas: nav_groups, plus one for what sits under the business
-- ---------------------------------------------------------------------------
-- A group with no sidebar entry renders nothing in the menu (app_nav() joins from nav_items).
INSERT INTO nav_groups (name, sort_order) VALUES ('Technology & Infrastructure', 70)
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- The catalog
-- ---------------------------------------------------------------------------
CREATE TABLE application_catalog (
    catalog_key       text PRIMARY KEY,                     -- a built-in's key is its app_key
    name              text NOT NULL UNIQUE,
    description       text NOT NULL,
    icon              text NOT NULL DEFAULT 'feather-grid',
    business_area_id  bigint NOT NULL REFERENCES nav_groups(id) ON DELETE RESTRICT,
    kind              text NOT NULL CHECK (kind IN ('builtin', 'external')),
    vendor            text,
    category          text NOT NULL DEFAULT 'other' CHECK (category IN ('platform', 'accounting', 'crm',
                          'calendar', 'email', 'documents', 'storage', 'database',
                          'communication', 'automation', 'development', 'security', 'other')),
    sort_order        integer NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX application_catalog_area_idx ON application_catalog (business_area_id, sort_order);

ALTER TABLE application_catalog ENABLE ROW LEVEL SECURITY;
CREATE POLICY application_catalog_app_rw ON application_catalog FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON application_catalog TO app_rw;
CREATE TRIGGER application_catalog_touch BEFORE UPDATE ON application_catalog
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE applications
    ADD COLUMN catalog_key         text   REFERENCES application_catalog(catalog_key) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD COLUMN business_area_id    bigint REFERENCES nav_groups(id) ON DELETE SET NULL,
    ADD COLUMN sme_agent_member_id bigint REFERENCES agent_profiles(member_id) ON DELETE SET NULL;
CREATE INDEX applications_catalog_idx ON applications (catalog_key);
CREATE INDEX applications_area_idx    ON applications (business_area_id);
CREATE INDEX applications_sme_idx     ON applications (sme_agent_member_id);

-- A built-in sits where its first sidebar entry sits; what has no entry is infrastructure.
UPDATE applications a
   SET business_area_id = COALESCE(
           (SELECT i.group_id FROM nav_items i JOIN nav_groups g ON g.id = i.group_id
             WHERE i.application_id = a.id ORDER BY g.sort_order, i.sort_order LIMIT 1),
           (SELECT id FROM nav_groups WHERE name = 'Technology & Infrastructure'));

-- Built-ins: one entry each, from the registry row and its sidebar icon.
INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, category, sort_order)
SELECT a.app_key, a.name, COALESCE(a.description, a.name),
       COALESCE((SELECT i.icon FROM nav_items i JOIN nav_groups g ON g.id = i.group_id
                  WHERE i.application_id = a.id ORDER BY g.sort_order, i.sort_order LIMIT 1), 'feather-grid'),
       a.business_area_id, 'builtin', a.category,
       COALESCE((SELECT i.sort_order FROM nav_items i JOIN nav_groups g ON g.id = i.group_id
                  WHERE i.application_id = a.id ORDER BY g.sort_order, i.sort_order LIMIT 1), 900)
  FROM applications a
 WHERE a.is_builtin;

-- Outside products a business commonly runs. The list is data: a row added or removed here (or
-- by a later migration) changes the inventory and nothing else.
INSERT INTO application_catalog (catalog_key, name, vendor, description, icon, business_area_id, kind, category, sort_order)
SELECT v.catalog_key, v.name, v.vendor, v.description, v.icon, g.id, 'external', v.category, 1000 + v.ord
  FROM (VALUES
    ('google_workspace', 'Google Workspace', 'Google',     'Mail, calendar, documents and drive',                  'feather-mail',           '',                            'email',         1),
    ('microsoft_365',    'Microsoft 365',    'Microsoft',  'Outlook, Office, OneDrive and SharePoint',             'feather-mail',           '',                            'email',         2),
    ('slack',            'Slack',            'Salesforce', 'Team chat and channels',                               'feather-message-square', '',                            'communication', 3),
    ('microsoft_teams',  'Microsoft Teams',  'Microsoft',  'Team chat, calls and meetings',                        'feather-message-square', '',                            'communication', 4),
    ('zoom',             'Zoom',             'Zoom',       'Video meetings and webinars',                          'feather-video',          '',                            'communication', 5),
    ('salesforce',       'Salesforce',       'Salesforce', 'Customer relationship management',                     'feather-users',          'Sales & Service',             'crm',           1),
    ('hubspot',          'HubSpot',          'HubSpot',    'CRM, marketing and sales automation',                  'feather-users',          'Sales & Service',             'crm',           2),
    ('stripe',           'Stripe',           'Stripe',     'Online payments and subscriptions',                    'feather-credit-card',    'Sales & Service',             'accounting',    3),
    ('square',           'Square',           'Block',      'Point of sale and card payments',                      'feather-credit-card',    'Sales & Service',             'accounting',    4),
    ('shopify',          'Shopify',          'Shopify',    'Online store and orders',                              'feather-shopping-bag',   'Sales & Service',             'other',         5),
    ('zendesk',          'Zendesk',          'Zendesk',    'Customer support and ticketing',                       'feather-life-buoy',      'Sales & Service',             'communication', 6),
    ('mailchimp',        'Mailchimp',        'Intuit',     'Email marketing and audiences',                        'feather-send',           'Sales & Service',             'communication', 7),
    ('quickbooks',       'QuickBooks Online','Intuit',     'Accounting, invoicing and bank feeds',                 'feather-book',           'Finance',                     'accounting',    1),
    ('xero',             'Xero',             'Xero',       'Accounting, invoicing and bank feeds',                 'feather-book',           'Finance',                     'accounting',    2),
    ('sage',             'Sage Accounting',  'Sage',       'Accounting and payroll',                               'feather-book',           'Finance',                     'accounting',    3),
    ('paypal',           'PayPal',           'PayPal',     'Online payments and payouts',                          'feather-dollar-sign',    'Finance',                     'accounting',    4),
    ('asana',            'Asana',            'Asana',      'Projects and task tracking',                           'feather-check-square',   'Operations',                  'other',         1),
    ('trello',           'Trello',           'Atlassian',  'Boards and cards for team work',                       'feather-trello',         'Operations',                  'other',         2),
    ('jira',             'Jira',             'Atlassian',  'Issue and project tracking',                           'feather-check-square',   'Operations',                  'development',   3),
    ('notion',           'Notion',           'Notion',     'Notes, wikis and lightweight databases',               'feather-file-text',      'Operations',                  'documents',     4),
    ('dropbox',          'Dropbox',          'Dropbox',    'File storage and sharing',                             'feather-hard-drive',     'Operations',                  'storage',       5),
    ('docusign',         'DocuSign',         'DocuSign',   'Electronic signatures',                                'feather-edit-3',         'Operations',                  'documents',     6),
    ('gusto',            'Gusto',            'Gusto',      'Payroll, benefits and onboarding',                     'feather-user-check',     'Human Resources',             'other',         1),
    ('adp',              'ADP',              'ADP',        'Payroll and workforce management',                     'feather-user-check',     'Human Resources',             'other',         2),
    ('bamboohr',         'BambooHR',         'BambooHR',   'Employee records, leave and reviews',                  'feather-user-check',     'Human Resources',             'other',         3),
    ('postgres',         'PostgreSQL',       'PostgreSQL', 'The record memory: every business record the platform keeps', 'feather-database', 'Technology & Infrastructure', 'database',      1),
    ('maludb',           'MaluDB memory',    'MaluDB',     'The activity memory: what happened, as episodes',      'feather-database',       'Technology & Infrastructure', 'database',      2),
    ('github',           'GitHub',           'Microsoft',  'Source code, issues and pull requests',                'feather-github',         'Technology & Infrastructure', 'development',   3),
    ('gitlab',           'GitLab',           'GitLab',     'Source code, CI/CD and issues',                        'feather-gitlab',         'Technology & Infrastructure', 'development',   4),
    ('aws',              'Amazon Web Services','Amazon',   'Cloud compute, storage and networking',                'feather-cloud',          'Technology & Infrastructure', 'platform',      5),
    ('cloudflare',       'Cloudflare',       'Cloudflare', 'DNS, CDN and network security',                        'feather-shield',         'Technology & Infrastructure', 'security',      6),
    ('proxmox',          'Proxmox VE',       'Proxmox',    'The virtualisation host that carries offices',         'feather-server',         'Technology & Infrastructure', 'platform',      7),
    ('bitwarden',        'Bitwarden',        'Bitwarden',  'Team password manager',                                'feather-lock',           'Technology & Infrastructure', 'security',      8)
  ) AS v(catalog_key, name, vendor, description, icon, area, category, ord)
  JOIN nav_groups g ON g.name = v.area;

UPDATE applications SET catalog_key = app_key WHERE is_builtin;
UPDATE applications SET catalog_key = app_key WHERE app_key IN ('postgres', 'maludb') AND NOT is_builtin;

-- ---------------------------------------------------------------------------
-- Skills that belong to an application
-- ---------------------------------------------------------------------------
ALTER TABLE skill_assignments
    ADD COLUMN application_id bigint REFERENCES applications(id) ON DELETE CASCADE;
ALTER TABLE skill_assignments DROP CONSTRAINT skill_assignments_scope_kind_check;
ALTER TABLE skill_assignments ADD CONSTRAINT skill_assignments_scope_kind_check
    CHECK (scope_kind IN ('org', 'department', 'role', 'agent', 'application'));
-- The four existing scope checks never mention application_id; this one says it belongs to the
-- application scope and to nothing else.
ALTER TABLE skill_assignments ADD CONSTRAINT skill_assignments_application_check
    CHECK ((scope_kind = 'application') = (application_id IS NOT NULL)
       AND (scope_kind <> 'application'
            OR (department_id IS NULL AND role_key IS NULL AND agent_member_id IS NULL)));

DROP INDEX skill_assignments_live_idx;
CREATE UNIQUE INDEX skill_assignments_live_idx
    ON skill_assignments (skill_name, scope_kind, COALESCE(department_id, 0), COALESCE(role_key, ''),
                          COALESCE(agent_member_id, 0), COALESCE(application_id, 0))
    WHERE revoked_at IS NULL;
CREATE INDEX skill_assignments_application_idx ON skill_assignments (application_id) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- Who may use what — asked about a member, not about the caller
-- ---------------------------------------------------------------------------
-- The running applications a member may use: a built-in through its module grant, anything through
-- a live application_access row (their own or a department's). The same rule as
-- app_can_use_application(), without the super-admin branch — this is asked about agents, and an
-- agent is never an admin. SECURITY DEFINER: the runner holds no grant on these tables.
CREATE FUNCTION app_member_application_ids(p_member_id bigint) RETURNS bigint[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(array_agg(a.id ORDER BY a.id), '{}')
      FROM applications a
     WHERE a.status IN ('active', 'degraded')
       AND (NOT a.is_builtin OR app_module_enabled(a.module))
       AND ((a.is_builtin AND a.module IS NOT NULL
             AND EXISTS (SELECT 1 FROM module_grants mg
                          WHERE mg.member_id = p_member_id AND mg.module = a.module))
         -- a built-in nothing in the menu gates (the platform itself, Team & Access) is open to
         -- everyone who works here — the convention app_module_enabled() already follows
         OR (a.is_builtin AND (a.module IS NULL
                               OR NOT EXISTS (SELECT 1 FROM nav_items n WHERE n.module = a.module)))
         OR EXISTS (SELECT 1 FROM application_access x
                     WHERE x.application_id = a.id AND x.revoked_at IS NULL
                       AND (x.expires_at IS NULL OR x.expires_at > now())
                       AND (x.member_id = p_member_id
                            OR x.department_id IN (SELECT dm.department_id FROM department_members dm
                                                    WHERE dm.member_id = p_member_id AND dm.left_at IS NULL))));
$$;

-- The applications whose skills reach an agent: those it may use, and those it is the expert on.
CREATE FUNCTION app_agent_skill_application_ids(p_member_id bigint) RETURNS bigint[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(array_agg(DISTINCT id), '{}')
      FROM (SELECT unnest(app_member_application_ids(p_member_id)) AS id
            UNION
            SELECT a.id FROM applications a
             WHERE a.sme_agent_member_id = p_member_id AND a.status IN ('active', 'degraded')
               AND (NOT a.is_builtin OR app_module_enabled(a.module))) s;
$$;
GRANT EXECUTE ON FUNCTION app_member_application_ids(bigint), app_agent_skill_application_ids(bigint)
    TO app_rw, app_records_ro, app_runner;

-- ---------------------------------------------------------------------------
-- Read surface (columns appended last; security_barrier kept)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW mcp_applications WITH (security_barrier = true) AS
 SELECT a.id AS application_id,
    a.name,
    a.app_key,
    a.category,
    a.description,
    a.vendor,
    a.is_self_hosted,
    a.is_builtin,
    a.module,
    a.location_id,
    l.name AS location_name,
    l.kind AS location_kind,
    a.owner_department_id,
    d.name::text AS owner_department_name,
    a.owner_member_id,
    om.display_name AS owner_name,
    a.url,
    a.version,
    a.criticality,
    a.status,
    a.health_status,
    a.last_health_check_at,
    app_can_use_application(a.id) AS i_can_use,
        CASE
            WHEN app_has_module('applications'::text) OR app_is_super_admin() THEN a.recurring_expense_id
            ELSE NULL::bigint
        END AS recurring_expense_id,
    a.notes,
    a.retired_at,
    a.created_at,
    a.catalog_key,
    a.business_area_id,
    g.name AS business_area_name,
    g.sort_order AS business_area_sort,
    (NOT a.is_builtin OR app_module_enabled(a.module)) AS module_enabled,
    a.sme_agent_member_id,
    sm.display_name AS sme_agent_name
   FROM applications a
     LEFT JOIN locations l ON l.id = a.location_id
     LEFT JOIN departments d ON d.id = a.owner_department_id
     LEFT JOIN members om ON om.id = a.owner_member_id
     LEFT JOIN nav_groups g ON g.id = a.business_area_id
     LEFT JOIN members sm ON sm.id = a.sme_agent_member_id
  WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_skill_assignments WITH (security_barrier = true) AS
 SELECT a.id AS skill_assignment_id,
    a.skill_name,
    a.pinned_bundle_hash,
    a.scope_kind,
    a.department_id,
    d.name AS department_name,
    a.role_key,
    a.agent_member_id,
    m.display_name AS agent_name,
    a.note,
    a.assigned_by,
    a.created_at,
    a.application_id,
    ap.name AS application_name
   FROM skill_assignments a
     LEFT JOIN departments d ON d.id = a.department_id
     LEFT JOIN members m ON m.id = a.agent_member_id
     LEFT JOIN applications ap ON ap.id = a.application_id
  WHERE a.revoked_at IS NULL AND app_is_insider();

CREATE VIEW mcp_application_catalog WITH (security_barrier = true) AS
 SELECT c.catalog_key,
    c.name,
    c.description,
    c.icon,
    c.kind,
    c.vendor,
    c.category,
    c.business_area_id,
    g.name AS business_area_name,
    g.sort_order AS business_area_sort,
    c.sort_order
   FROM application_catalog c
     JOIN nav_groups g ON g.id = c.business_area_id
  WHERE app_is_insider();
GRANT SELECT ON mcp_application_catalog TO app_rw, app_records_ro;

COMMIT;
