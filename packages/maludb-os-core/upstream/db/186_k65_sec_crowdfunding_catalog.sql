-- 186: K65 — the SEC Crowdfunding application in the catalog (D1/D16 of
-- /srv/apps/sec_crowdfunding/docs/sec-crowdfunding-design.md §12–13, the owner approved 2026-10-20): the business's equity-crowdfunding
-- deal engine for Regulation A+ Tier 2 and Regulation Crowdfunding offerings, run for a broker-dealer (or funding portal) of record and
-- the issuers raising through it — issuers with the bad-actor file, offerings with versioned terms and dated gates, the public offering
-- page and the checkout with both regimes' investor limits, money recorded and reconciled against the escrow agent's statement and
-- never held, closings with instructions issued by a principal and issuance tracked to the transfer agent's confirmation, the obligation
-- calendars of both regimes, the 17a-4 audit trail. BOTH category checks gain 'capital_markets' in this one file (the K30 lesson of
-- db/175: K27 and K29 widened the catalog's check only and the ProcessCore apply failed at register); the PHP list APPLICATION_CATEGORIES
-- is widened in the same change. db/185 is left for the forge's K61 (reserved by its design). Seeded so every installation shows it
-- under Finance ("from us, not installed") and the installer's apply finds its row. On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/186_k65_sec_crowdfunding_catalog.sql
BEGIN;

ALTER TABLE application_catalog DROP CONSTRAINT application_catalog_category_check;
ALTER TABLE application_catalog ADD CONSTRAINT application_catalog_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing',
                        'investor_relations', 'capital_markets', 'other'));

ALTER TABLE applications DROP CONSTRAINT applications_category_check;
ALTER TABLE applications ADD CONSTRAINT applications_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing',
                        'investor_relations', 'capital_markets', 'other'));

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'sec_crowdfunding', 'SEC Crowdfunding',
       'The deal engine for Regulation A+ Tier 2 and Regulation Crowdfunding offerings, run for a broker-dealer (or funding portal) of record and the companies raising through it: issuers onboarded with the bad-actor file and a diligence checklist; offerings with versioned terms and dated gates (Form C filed, 1-A qualified, FINRA''s no-objection letter, each state''s notice); the public offering page and the checkout with both regimes'' investor limits computed and explained, the educational acknowledgements, click-to-sign with E-SIGN consent; money recorded and reconciled daily against the escrow agent''s statement and never held — a release, a refund and an issuance are instructions a principal issues; closings tracked to the transfer agent''s confirmation; the obligation calendars of both regimes; the 17a-4 audit trail; identifiers and bank details sealed to a vault. The Expert works the command bar; the Compliance Analyst writes the morning note and proposes dispositions. Optional; installed on request.',
       'feather-trending-up', g.id, 'ours', NULL, 'capital_markets', 0
  FROM nav_groups g WHERE g.name = 'Finance'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
