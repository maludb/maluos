-- 063_app_read_views.sql
-- The app reads what the agents read.
--
-- Business RLS is permissive for app_rw (049): the application role can reach every row, and
-- the application is the gate. That is right for writes, but it would mean two visibility
-- rules -- app_can_see() in SQL for the MCP servers, and hand-written WHERE clauses in PHP for
-- the screens -- which is exactly how a screen ends up showing a person something their agent
-- would refuse to show them.
--
-- So every list and detail screen reads an mcp_* view, and this migration gives app_rw the
-- SELECT it needs to do that. The views are security_barrier and carry app_can_see(), so the
-- rows a screen renders are decided by the same function, in the same place, for humans and
-- agents alike. Writes still go to the base tables, after the endpoint's own authorization
-- check (build spec: docs/build-specs/contacts-crm.md, "Gate and visibility").

BEGIN;

DO $$
DECLARE v record;
BEGIN
    FOR v IN
        SELECT table_name FROM information_schema.views
         WHERE table_schema = 'public' AND table_name LIKE 'mcp\_%'
    LOOP
        EXECUTE format('GRANT SELECT ON %I TO app_rw', v.table_name);
    END LOOP;
END$$;

-- Future views created by later migrations must not be forgotten: the read roles are granted
-- explicitly per migration, and app_rw is granted here. A slice that adds a view adds its
-- grant in its own migration, exactly as db/050 does.

COMMIT;
