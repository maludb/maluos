-- 146: "System" in the sidebar's Administration group (2026-09-27 — docs/build-specs/system-one-harness.md):
-- the Sysadmin's view of the server, for the super-admin and IT admins. Data only.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/146_nav_system.sql
BEGIN;
INSERT INTO nav_items (item_key, application_id, group_id, sort_order, label, icon, url, audience, active_patterns, phase)
SELECT 'system', 10, g.id, 45, 'System', 'feather-cpu', '/ai/system', 'admin', '{/ai/system}', 5
  FROM nav_groups g WHERE g.name = 'Administration'
ON CONFLICT (item_key) DO NOTHING;
COMMIT;
