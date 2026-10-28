-- 143: "Human Workforce" in the sidebar, under "Agent Workforce" (2026-09-26 — the owner: the people who
-- work here are added and maintained from a page the navigation reaches). /team — People & access,
-- filtered to people — was reachable only as part of Agent Workforce; it gets its own entry, and Agent
-- Workforce keeps /skills. Admins only (inviting and maintaining people is theirs). Data only.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/143_nav_human_workforce.sql
BEGIN;
INSERT INTO nav_items (item_key, application_id, group_id, sort_order, label, icon, url, audience, active_patterns, phase)
SELECT 'human_workforce', 22, i.group_id, i.sort_order + 5, 'Human Workforce', 'feather-user', '/team?kind=human', 'admin', '{/team}', 1
  FROM nav_items i WHERE i.item_key = 'agents'
ON CONFLICT (item_key) DO NOTHING;
UPDATE nav_items SET active_patterns = array_remove(active_patterns, '/team'), updated_at = now() WHERE item_key = 'agents';
COMMIT;
