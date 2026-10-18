-- 182: K47 — the Restaurant Inventory application in the catalog (D1 of
-- /srv/apps/restaurant_inventory/docs/restaurant-inventory-design.md §13, the owner approved 2026-10-11): a kitchen and bar
-- stock desk — purchasing and receiving, costed recipes with sub-recipes and yields, POS sales depleting stock through the
-- recipes, waste, physical counts by storage area, usage periods with actual vs theoretical, and the projection of expected
-- usage into a suggested order per supplier. Site-scoped (every restaurant a kernel site). Category 'inventory' is admitted
-- by both checks since db/172 and db/175, so nothing is widened. Seeded under Operations beside the retail Inventory row so
-- every installation shows it ("from us, not installed") and the installer's apply finds its row. On request, not a default.
-- Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/182_k47_restaurant_inventory_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'restaurant_inventory', 'Restaurant Inventory',
       'The kitchen''s and the bar''s stock desk: what the restaurant buys, in the units it buys, counts and cooks it in; recipes with sub-recipes and yields so every plate has a cost as of any date; purchase orders and receiving at a known cost; the POS''s sales depleting stock through the recipes; waste, transfers, prep batches and physical counts by storage area; usage periods showing actual against theoretical with every bucket; and the projection — expected sales exploded through recipes into expected usage, projected stock per ingredient per day, and one suggested order per supplier for its next delivery with the arithmetic on every line. Every restaurant is a site. The Kitchen Inventory Expert answers and drafts from the command bar; the Purchasing agent''s morning note carries the day''s suggested orders and never places one. Optional; installed on request.',
       'feather-coffee', g.id, 'ours', NULL, 'inventory', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
