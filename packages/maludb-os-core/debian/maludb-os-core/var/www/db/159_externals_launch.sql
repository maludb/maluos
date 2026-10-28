-- 159: an external can launch (build plan A9, K2; owner, 2026-09-28 — "yes, open it up"). Until now the
-- launcher's view was gated on app_is_insider(), so a member flagged external saw an empty launcher even
-- with a live grant (recorded open in docs/build-specs/kernel-sign-on.md). app_can_launch() admits an insider
-- as before, and an external who holds at least one live grant; mcp_my_applications takes it in place of
-- app_is_insider() (same columns; app_can_use_application() still decides each row), and the launcher reads
-- one view of its own, mcp_launcher_applications, instead of joining the insider-gated registry views.
-- An external still sees nothing of the registry, the catalog or the OS face. Additive.
BEGIN;

CREATE OR REPLACE FUNCTION app_can_launch() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $fn$
    SELECT app_business_role() <> 'anon'
       AND (NOT app_is_external()
            OR EXISTS (SELECT 1 FROM applications a
                        WHERE a.status <> 'retired'
                          AND EXISTS (SELECT 1 FROM app_member_grants(a.id, app_current_member_id()))));
$fn$;
COMMENT ON FUNCTION app_can_launch() IS 'May the signed-in person open the launcher: an insider, or an external with a live application grant (db/159).';

CREATE OR REPLACE VIEW mcp_my_applications WITH (security_barrier = true) AS
 SELECT a.id AS application_id,
    a.name,
    a.app_key,
    a.category,
    a.is_builtin,
    a.module,
    a.location_id,
    l.name AS location_name,
    a.url,
    a.status,
    a.health_status,
    COALESCE(( SELECT g.capability
           FROM app_member_grants(a.id, app_current_member_id()) g(application_access_id, scope_id, role_key, capability, route)
          ORDER BY (app_capability_rank(g.capability)) DESC
         LIMIT 1),
        CASE
            WHEN app_is_super_admin() THEN 'admin'::text
            ELSE NULL::text
        END) AS capability,
    ( SELECT count(*) AS count
           FROM application_endpoints e
          WHERE e.application_id = a.id AND e.status = 'active'::text AND e.agent_reachable) AS endpoint_count,
    a.sso_path,
    a.scope_kind
   FROM applications a
     LEFT JOIN locations l ON l.id = a.location_id
  WHERE a.status <> 'retired'::text AND app_can_launch() AND app_can_use_application(a.id);

CREATE OR REPLACE VIEW mcp_launcher_applications WITH (security_barrier = true) AS
 SELECT m.application_id, m.name, m.app_key, m.category, m.url, m.status, m.capability, m.sso_path, m.scope_kind,
        a.description, g.name AS business_area_name, g.sort_order AS business_area_sort, c.icon
   FROM mcp_my_applications m
   JOIN applications a ON a.id = m.application_id
   LEFT JOIN nav_groups g ON g.id = a.business_area_id
   LEFT JOIN application_catalog c ON c.catalog_key = a.catalog_key
  WHERE m.app_key IS DISTINCT FROM 'platform' AND NOT a.is_builtin;
COMMENT ON VIEW mcp_launcher_applications IS 'What the launcher offers the signed-in person (db/159): their applications with description, area and icon, gated by app_can_launch(), never by the registry views.';
GRANT SELECT ON mcp_launcher_applications TO app_rw, app_records_ro;

COMMIT;
