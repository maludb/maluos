-- 174: K29 — the ProcessCore application in the catalog (D15 of /srv/apps/processcore/docs/processcore-design.md, owner approved
-- 2026-10-08): a base manufacturing application for converting processes — material in as lots, runs on equipment turning them
-- into other lots (products, co-products, scrap), packaging, quality release, shipments; industry is data, not code (a profile
-- seeds the item classes, operations and vocabulary; steel processing the default). Forked from the cidery. The catalog's category
-- check gains 'manufacturing' (there was none — the cidery sits under 'other'); the PHP list APPLICATION_CATEGORIES is widened in
-- the same change. Seeded so every installation shows it under Operations ("from us, not installed") and the installer's apply
-- finds its row. On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/174_k29_processcore_catalog.sql
BEGIN;

ALTER TABLE application_catalog DROP CONSTRAINT application_catalog_category_check;
ALTER TABLE application_catalog ADD CONSTRAINT application_catalog_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing', 'other'));

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'processcore', 'ProcessCore',
       'A base manufacturing application for converting processes: material arrives as lots, is transformed by runs on equipment into other lots (products, co-products, scrap), is packed, released by quality and shipped — every quantity on the inventory ledger, every lot traceable to what it came from, with purchase orders, receipts, customer orders, planning, costing and an equipment schedule. Industry is data, not code: a profile seeds the item classes, operations, measurements and vocabulary — steel processing the default (coils by heat with mill test reports, slit, cut to length, sheared and blanked into sheets and blanks, scrap sold by weight). Forked from the Cidery with the beverage layers removed. Optional; installed on request.',
       'feather-layers', g.id, 'ours', NULL, 'manufacturing', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
