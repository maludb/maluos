-- 178: K34 — the Shareholder Intelligence application in the catalog (D1/D15 of
-- /srv/apps/shareholder_intelligence/docs/shareholder-intelligence-design.md §12–13, the owner approved 2026-10-09): shareholder
-- surveillance for a publicly traded company (or an advisory firm serving several) — the DTC Security Position Report, the NOBO list
-- and the transfer agent's register uploaded and reconciled with the share count, holders matched across lists, SEC EDGAR, FINRA
-- short interest and daily short volume, the SEC's fails-to-deliver and the Reg SHO threshold lists fetched under a declared policy,
-- prices and events, nineteen signal rules with an evidence class on every signal for a person to judge. BOTH category checks gain
-- 'investor_relations' in this one file (the K30 lesson of db/175: K27 and K29 widened the catalog's check only and the ProcessCore
-- apply failed at register); the PHP list APPLICATION_CATEGORIES is widened in the same change. Seeded so every installation shows
-- it under Finance ("from us, not installed") and the installer's apply finds its row. On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/178_k34_shareholder_intelligence_catalog.sql
BEGIN;

ALTER TABLE application_catalog DROP CONSTRAINT application_catalog_category_check;
ALTER TABLE application_catalog ADD CONSTRAINT application_catalog_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing',
                        'investor_relations', 'other'));

ALTER TABLE applications DROP CONSTRAINT applications_category_check;
ALTER TABLE applications ADD CONSTRAINT applications_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing',
                        'investor_relations', 'other'));

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'shareholder_intelligence', 'Shareholder Intelligence',
       'Shareholder surveillance for a publicly traded company: the weekly DTC Security Position Report, Broadridge''s NOBO list and the transfer agent''s register uploaded, tied to their own totals and reconciled with the share count; holders matched across lists; SEC EDGAR filings and ownership forms (13F, 13D/13G, Forms 3/4/5, 144), FINRA short interest and daily short volume, the SEC''s fails-to-deliver and the Reg SHO threshold lists fetched under a declared policy; every series charted against the price with the company''s events; rules that raise signals, each with its evidence and whether that evidence is established, contested or lore, for a person to judge. Nothing leaves the business. The Expert works the command bar; the Surveillance Analyst writes the market-day morning note and drafts the weekly pack. Optional; installed on request.',
       'feather-trending-down', g.id, 'ours', NULL, 'investor_relations', 0
  FROM nav_groups g WHERE g.name = 'Finance'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
