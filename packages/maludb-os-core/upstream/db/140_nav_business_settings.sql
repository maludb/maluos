-- 140: Business settings in the sidebar (2026-09-23).
-- The company's name, legal details, currency, hours and logo live at /settings/business, a
-- super-admin screen nothing linked to: the owner looked for the logo upload and could not find
-- it. One entry in the Administration group, just before Settings. Audience 'admin' is the
-- tightest the menu offers (app_is_admin: super-admin or dept-admin); the screen itself refuses
-- anyone but the super-admin, and the os. face admits only super-admins. Additive: one row.
BEGIN;

INSERT INTO nav_items (item_key, group_id, sort_order, label, icon, url, audience, active_patterns, status)
SELECT 'business_settings', g.id, 55, 'Business Settings', 'feather-briefcase', '/settings/business', 'admin', '{}', 'active'
  FROM nav_groups g
 WHERE g.name = 'Administration'
ON CONFLICT (item_key) DO NOTHING;

COMMIT;
