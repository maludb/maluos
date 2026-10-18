-- 172: the Inventory application in the catalog (K27 of /srv/apps/inventory/docs/inventory-design.md §12; owner's D15, 2026-10-05) — sales
-- inventory for a retailer that holds some stock and drop-ships the rest (modelled on mattress retail): a catalog with GTINs and every
-- seller's identifier, own stock by location on a transaction ledger, other websites and suppliers' feeds read politely with every offer
-- snapshotted and matched to the catalog, Find, orders filled from stock or drop-shipped. The catalog's category check gains
-- 'inventory' (there was none; 'other' would have hidden what it is) — the PHP list APPLICATION_CATEGORIES is widened in the same change.
-- Seeded so every installation shows it under Operations ("from us, not installed") and the installer's apply finds its row.
-- On request, not a default. Additive.
BEGIN;

ALTER TABLE application_catalog DROP CONSTRAINT application_catalog_category_check;
ALTER TABLE application_catalog ADD CONSTRAINT application_catalog_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'other'));

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'inventory', 'Inventory',
       'Sales inventory for a retailer of packaged goods who holds some stock and drop-ships the rest — modelled on mattress retail. A catalog in Shopify''s and GS1''s words (a product, its sizes as variants, every identifier a seller uses), the business''s own stock by location on a transaction ledger, and the sources it can sell from without holding anything: other websites read politely, suppliers'' inventory feeds, price sheets, another installation of this application — every offer remembered as it changes and matched to the catalog. One Find answers own stock, every supplier''s offer by cost and lead time, and the references; an order line is filled from the shelf or drop-shipped, the supplier acknowledges and adds tracking through a secure link, the customer watches through theirs. The ledger reads sales, purchases and stock value. Optional; installed on request.',
       'feather-package', g.id, 'ours', NULL, 'inventory', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
