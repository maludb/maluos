-- 128: the Dashboard entry points at /dashboard (docs/build-specs/data-driven-nav.md, step 2).
--
-- db/127 seeded the old catalog's URL, '/', and web/lib/nav.ts translated it in code — `/` is the
-- Agent View, the traditional dashboard lives at /dashboard. The menu is data now, so the data
-- says where the entry goes and the special case leaves the code.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/128_nav_dashboard_url.sql

BEGIN;
UPDATE nav_items SET url = '/dashboard' WHERE item_key = 'dashboard' AND url = '/';
COMMIT;
