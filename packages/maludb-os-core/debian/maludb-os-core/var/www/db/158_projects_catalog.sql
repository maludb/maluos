-- 158: the Projects application in the catalog (build plan A9, K1; owner, 2026-09-28) — an application
-- from us, seeded so every installation knows it exists before the installer puts it beside the kernel
-- (HR's row was added by hand). Under Operations until a business area of its own is wanted. Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'projects', 'Projects',
       'Agile project management — backlogs, sprints and a kanban board, in the manner of Jira and Linear; agents are assignees. Installed by default beside the kernel.',
       'feather-trello', g.id, 'ours', NULL, 'other', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
