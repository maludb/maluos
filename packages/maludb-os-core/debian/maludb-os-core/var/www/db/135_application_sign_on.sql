-- 135: where an application receives the platform's sign-on (A3, 2026-09-22).
--
-- docs/business-os-integration.md, "Identity and single sign-on": the kernel is the one identity;
-- an application from us keeps no password. The launcher mints a 60-second, single-use hand-off
-- token for a person with a live access grant and sends the browser to the application's sso path;
-- the kernel's sign-out posts a notice to the logout path. Both paths are the application's
-- declaration (maludb-os.json, "sso"), recorded here at registration. An application with no sso
-- path cannot be signed in to: the launcher opens its address as it is.
--
-- Additive: two columns, appended last to the two views they travel on. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/135_application_sign_on.sql

BEGIN;

ALTER TABLE applications
    ADD COLUMN sso_path        text CHECK (sso_path IS NULL OR (sso_path ~ '^/' AND length(sso_path) <= 200)),
    ADD COLUMN sso_logout_path text CHECK (sso_logout_path IS NULL OR (sso_logout_path ~ '^/' AND length(sso_logout_path) <= 200));

COMMENT ON COLUMN applications.sso_path IS 'Where the application receives the hand-off token (maludb-os.json sso.path); NULL = the platform cannot sign a person in to it.';
COMMENT ON COLUMN applications.sso_logout_path IS 'Where the application receives the kernel''s sign-out notice (maludb-os.json sso.logout_path).';

CREATE OR REPLACE VIEW mcp_applications WITH (security_barrier = true) AS
SELECT a.id AS application_id, a.name, a.app_key, a.category, a.description, a.vendor, a.is_self_hosted,
       a.is_builtin, a.module, a.location_id, l.name AS location_name, l.kind AS location_kind,
       a.owner_department_id, d.name::text AS owner_department_name, a.owner_member_id, om.display_name AS owner_name,
       a.url, a.version, a.criticality, a.status, a.health_status, a.last_health_check_at,
       app_can_use_application(a.id) AS i_can_use,
       a.notes, a.retired_at, a.created_at, a.catalog_key, a.business_area_id,
       g.name AS business_area_name, g.sort_order AS business_area_sort,
       (NOT a.is_builtin OR app_module_enabled(a.module)) AS module_enabled,
       a.sme_agent_member_id, sm.display_name AS sme_agent_name,
       a.sso_path, a.sso_logout_path
  FROM applications a
  LEFT JOIN locations l ON l.id = a.location_id
  LEFT JOIN departments d ON d.id = a.owner_department_id
  LEFT JOIN members om ON om.id = a.owner_member_id
  LEFT JOIN nav_groups g ON g.id = a.business_area_id
  LEFT JOIN members sm ON sm.id = a.sme_agent_member_id
 WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_my_applications WITH (security_barrier = true) AS
SELECT a.id AS application_id, a.name, a.app_key, a.category, a.is_builtin, a.module,
       a.location_id, l.name AS location_name, a.url, a.status, a.health_status,
       coalesce((SELECT max(ac.capability) FROM application_access ac
                  WHERE ac.application_id = a.id AND ac.revoked_at IS NULL
                    AND (ac.expires_at IS NULL OR ac.expires_at > now())
                    AND (ac.member_id = app_current_member_id()
                         OR ac.department_id = ANY (app_my_department_ids()))),
                CASE WHEN app_is_super_admin() THEN 'admin' END) AS capability,
       (SELECT count(*) FROM application_endpoints e
         WHERE e.application_id = a.id AND e.status = 'active' AND e.agent_reachable) AS endpoint_count,
       a.sso_path
  FROM applications a
  LEFT JOIN locations l ON l.id = a.location_id
 WHERE a.status <> 'retired' AND app_is_insider() AND app_can_use_application(a.id);

COMMIT;
