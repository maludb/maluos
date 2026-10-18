-- 177: the Sales CRM application in the catalog (K32 of /srv/apps/sales_crm/docs/sales-crm-design.md §12; the owner's D15, 2026-10-09) —
-- prospecting and customer relationship management: leads worked and converted into an account, a contact and a deal; accounts and
-- contacts with one timeline; deals through several pipelines on a kanban board that shows the sales cycle; every call, email, meeting
-- and task as an activity with a reminder on a calendar; email logged by a BCC mailbox; campaigns, lists, imports and the reports a
-- sales manager runs a team by. Category 'crm' is admitted by both checks since db/130, so nothing is widened. Seeded so every
-- installation shows it under Sales & Service ("from us, not installed") and the installer's apply finds its row. On request, not a
-- default. Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'sales_crm', 'Sales CRM',
       'Prospecting and customer relationship management: leads worked and converted into accounts, contacts and deals; every company and person with one timeline of calls, emails, meetings and notes; deals moved through pipelines on a kanban board that shows the sales cycle, with the next step on every card; a reminder calendar of the work to do; email logged by a BCC address; campaigns, lists, imports and the forecast, funnel and activity reports a sales manager runs a team by. The Sales CRM Expert works the command bar; the Sales Assistant writes each seller''s morning note and proposes the next step. Optional; installed on request.',
       'feather-target', g.id, 'ours', NULL, 'crm', 0
  FROM nav_groups g WHERE g.name = 'Sales & Service'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
