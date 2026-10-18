-- 129: a DISABLED application is closed — to people, to agents and to MCP
-- (docs/build-specs/data-driven-nav.md, step 3; the owner's three statuses, 2026-09-20).
--
--   active    in the sidebar and usable
--   hidden    not in the sidebar, still usable by URL, by agents and by MCP
--   disabled  not in the sidebar and NOT usable by anyone — the super-admin included
--
-- A module is closed when every sidebar entry that carries its grant is disabled (Contacts and
-- Deals share `contacts`: disabling Deals alone hides Deals; the module closes when both are).
-- The test goes into the two functions everything already passes through, so nothing else needs
-- to learn about it:
--   app_has_module()  screen entry (PHP require_module / require_module_grant), app_nav(),
--                     app_my_work(), the app_can_see_* family and the views that call it
--   app_path_closed()       the front door of every PHP request (app/bootstrap.php)
--   app_disabled_modules()  the MCP servers' own gate on every tool call (mcp/module_status.py)
--   app_can_see()     the row rule behind the mcp_* views — what the records MCP server reads.
--                     It had three branches that never asked app_has_module (your own record,
--                     super-admin, dept-admin in their department); a closed module now refuses
--                     before any of them.
-- Data is never touched: back to active or hidden and everything is there again.
-- While nothing is disabled both functions answer exactly as before.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/129_disabled_modules_close.sql

BEGIN;

CREATE INDEX nav_items_module_idx ON nav_items (module) WHERE module IS NOT NULL;

-- SECURITY DEFINER: the read-only MCP roles have no grant on nav_items, and must not need one.
CREATE OR REPLACE FUNCTION app_module_enabled(p_module text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT p_module IS NULL
        OR NOT EXISTS (SELECT 1 FROM nav_items WHERE module = p_module)
        OR EXISTS (SELECT 1 FROM nav_items WHERE module = p_module AND status <> 'disabled');
$$;
GRANT EXECUTE ON FUNCTION app_module_enabled(text) TO app_rw, app_records_ro, app_activity_ro, app_runner;

-- What the MCP servers ask before listing or running a tool (mcp/module_status.py): many read
-- views are gated on something other than the two functions below (app_is_insider(), a join),
-- so the servers close a disabled module's tools themselves, at the one place every call passes.
CREATE OR REPLACE FUNCTION app_disabled_modules() RETURNS text[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(array_agg(DISTINCT n.module), '{}')
      FROM nav_items n
     WHERE n.module IS NOT NULL AND NOT app_module_enabled(n.module);
$$;
GRANT EXECUTE ON FUNCTION app_disabled_modules() TO app_rw, app_records_ro, app_activity_ro, app_runner;

CREATE OR REPLACE FUNCTION public.app_has_module(p_module text)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
    SELECT app_module_enabled(p_module)
       AND (app_is_super_admin()
            OR EXISTS (SELECT 1 FROM module_grants
                        WHERE member_id = app_current_member_id() AND module = p_module));
$function$;

CREATE OR REPLACE FUNCTION public.app_can_see(p_module text, p_owner_member_id bigint, p_department_id bigint, p_entity_type text, p_entity_id bigint, p_organization_id bigint DEFAULT NULL::bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT CASE
        WHEN app_current_member_id() IS NULL THEN false
        WHEN NOT app_module_enabled(p_module) THEN false
        WHEN p_owner_member_id IS NOT NULL AND p_owner_member_id = app_current_member_id() THEN true
        WHEN app_is_super_admin() THEN true
        WHEN app_is_external() THEN
             app_has_module(p_module)
             OR app_is_shared_with_me(p_entity_type, p_entity_id)
             OR (p_organization_id IS NOT NULL
                 AND app_is_shared_with_me('organization', p_organization_id))
        WHEN app_is_dept_admin()
             AND p_department_id IS NOT NULL
             AND p_department_id = ANY (app_admin_department_ids()) THEN true
        ELSE
             app_has_module(p_module)
             AND (p_department_id IS NULL OR p_department_id = ANY (app_my_department_ids()))
    END;
$function$;

-- ---------------------------------------------------------------------------
-- The front door: every PHP request asks this once (app/bootstrap.php). Handlers gate in many
-- ways — require_module(), require_insider(), the people rule — so a disabled application is
-- closed by ADDRESS, before any of them: the entry whose address (or one of its
-- active_patterns) is the longest prefix of the request path owns it; if that entry is disabled
-- the request is refused, whoever asks — a person, or the actions MCP server posting for an agent.
-- Returns the entry's label, NULL when the path is open.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_path_closed(p_path text) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT CASE WHEN c.status = 'disabled' THEN c.label END
      FROM (SELECT i.label, i.status, rtrim(p.prefix, '/') AS prefix
              FROM nav_items i
             CROSS JOIN LATERAL unnest(array_append(i.active_patterns, i.url)) AS p(prefix)
             WHERE i.opens = 'same') c
     WHERE c.prefix <> ''
       AND (p_path = c.prefix OR starts_with(p_path, c.prefix || '/'))
     ORDER BY length(c.prefix) DESC, (c.status = 'disabled')
     LIMIT 1;
$$;
GRANT EXECUTE ON FUNCTION app_path_closed(text) TO app_rw;

-- Addresses that belong to an application but sit outside its own path.
UPDATE nav_items SET active_patterns = active_patterns || '{/skills}'::text[] WHERE item_key = 'agents' AND NOT '/skills' = ANY (active_patterns);
UPDATE nav_items SET active_patterns = active_patterns || '{/portal}'::text[] WHERE item_key = 'forms'  AND NOT '/portal' = ANY (active_patterns);

COMMIT;
