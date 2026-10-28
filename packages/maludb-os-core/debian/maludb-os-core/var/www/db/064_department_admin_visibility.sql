-- 064_department_admin_visibility.sql
-- mcp_department_members did not expose is_admin, so neither a screen nor an agent could
-- answer "who administers this department?" -- although that flag is exactly what makes a
-- dept-admin an administrator of one department and an ordinary user in another
-- (CLAUDE.md, roles). The membership view now carries it, beside is_primary, for the same
-- audience (insiders); the members it lists and the gate on the view are unchanged.
--
-- Found while building the Team & Access screens in the shell conversion (build plan 1.8).

BEGIN;

CREATE OR REPLACE VIEW mcp_department_members WITH (security_barrier = true) AS
SELECT dm.department_id, d.name::text AS department_name, dm.member_id, m.display_name,
       m.member_kind, dm.is_primary, dm.joined_at, dm.left_at, dm.is_admin
FROM department_members dm
JOIN departments d ON d.id = dm.department_id
JOIN members m ON m.id = dm.member_id
WHERE app_is_insider();

GRANT SELECT ON mcp_department_members TO app_records_ro, app_rw;

COMMIT;
