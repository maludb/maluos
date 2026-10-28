-- 136: the directory API (A4, 2026-09-22).
--
-- docs/business-os-integration.md, "The directory API": the kernel owns who exists, their role and
-- status, their departments; an application from us mirrors that and — HR alone — changes it
-- through the kernel, never through shared tables. Three additions:
--   * an APPLICATION TOKEN: mcp_access_tokens gains scope 'application' and the application it
--     belongs to (one live token per application; retiring the application revokes it). Its
--     member_id is the super-admin who minted it: the directory is read as the kernel sees it.
--   * applications.directory_writes — maludb-os.json "directory.writes": the kernel refuses a
--     write from an application that did not declare them.
--   * activity_log.source 'application' — a directory write is a person's act (X-Acting-Member),
--     made from inside an application.
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/136_directory_api.sql

BEGIN;

ALTER TABLE mcp_access_tokens
    ADD COLUMN application_id bigint REFERENCES applications(id) ON DELETE CASCADE;
ALTER TABLE mcp_access_tokens DROP CONSTRAINT mcp_access_tokens_scope_check;
ALTER TABLE mcp_access_tokens ADD CONSTRAINT mcp_access_tokens_scope_check
    CHECK (scope IN ('mcp', 'api', 'application'));
ALTER TABLE mcp_access_tokens ADD CONSTRAINT mcp_access_tokens_application_scope
    CHECK ((scope = 'application') = (application_id IS NOT NULL));
CREATE UNIQUE INDEX mcp_access_tokens_one_live_per_application
    ON mcp_access_tokens (application_id) WHERE scope = 'application' AND revoked_at IS NULL;
COMMENT ON COLUMN mcp_access_tokens.application_id IS 'scope = application: the application this token belongs to (OS_APPLICATION_TOKEN in its config/.env).';

ALTER TABLE applications ADD COLUMN directory_writes boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN applications.directory_writes IS 'maludb-os.json directory.writes: may call the directory API''s write endpoints as the acting person (HR).';

ALTER TABLE activity_log DROP CONSTRAINT activity_log_source_check;
ALTER TABLE activity_log ADD CONSTRAINT activity_log_source_check
    CHECK (source IN ('web', 'assistant', 'mcp', 'cron', 'agent', 'desk', 'webhook', 'portal', 'api', 'application'));

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
       a.sso_path, a.sso_logout_path,
       a.directory_writes
  FROM applications a
  LEFT JOIN locations l ON l.id = a.location_id
  LEFT JOIN departments d ON d.id = a.owner_department_id
  LEFT JOIN members om ON om.id = a.owner_member_id
  LEFT JOIN nav_groups g ON g.id = a.business_area_id
  LEFT JOIN members sm ON sm.id = a.sme_agent_member_id
 WHERE app_is_insider();

COMMIT;
