-- 183: K49 — the Developer application in the catalog (D1/D16 of /srv/apps/developer/docs/developer-design.md §12–13, the owner
-- approved 2026-10-11): the business's database development and administration tool, what phpMyAdmin is to MySQL for PostgreSQL
-- 17 and the MaluDB memory system — every registered database's objects, DDL and dependencies; forms that end on one Change review
-- page showing the exact SQL and what it costs; workbenches where schemas are designed live and exported as migration files;
-- installed applications' schemas changed only by migration drafts applied by the existing route; data at a level granted per
-- person, masks as column privileges, row edits in a time-boxed window; the SQL editor and plans; activity, maintenance and
-- health; a curated, read-only view of the memory databases; one door holding the tool's database credentials. Category
-- 'database' is already admitted by both checks (db/172, db/175, db/178 kept it), so nothing is widened. Seeded so every
-- installation shows it under Technology & Infrastructure ("from us, not installed") and the installer's apply finds its row.
-- On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/183_k49_developer_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'developer', 'Developer',
       'The business''s database development and administration tool — what phpMyAdmin is to MySQL, for PostgreSQL and the MaluDB memory system, for admins, software engineers and DBAs. Every registered database''s objects with their DDL, dependencies and statistics; forms that end on one Change review page showing the exact SQL, the lock it takes and whether it rewrites the table, linted and rehearsed on a throwaway copy; workbenches where schemas are designed live and exported as the next numbered migration for an application''s repository — installed applications'' schemas change only that way; data read at a level granted per person, with personal columns masked by the database''s own privileges and row edits made in a time-boxed window and undoable; the SQL editor with plans; what the server is doing, maintenance and health findings; a curated, read-only view of the memory databases. One door holds the tool''s database credentials and audits every statement. The Database Expert explains and drafts from the command bar; the DBA Advisor''s weekday note proposes fixes and never applies one. Optional; installed on request.',
       'feather-database', g.id, 'ours', NULL, 'database', 1
  FROM nav_groups g WHERE g.name = 'Technology & Infrastructure'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
