-- 167: the General Ledger application in the catalog (K13 of /srv/apps/gl/docs/gl-design.md §12; owner's D13,
-- 2026-10-04) — the optional accounting application from us, seeded so every installation shows it under Finance
-- beside QuickBooks, Xero and Sage ("from us, not installed") and the installer's apply finds its row. Never a
-- default install, never granted to the standing departments (D3). Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'gl', 'General Ledger',
       'The books: a chart of accounts, a double-entry journal with fiscal periods, the financial statements, accounts receivable (customers, invoices, receipts), accounts payable (vendors, bills, payment runs) and cash management against the bank. The kernel''s monthly AI statement becomes one bill per provider. Optional — installed on request.',
       'feather-book-open', g.id, 'ours', NULL, 'accounting', 0
  FROM nav_groups g WHERE g.name = 'Finance'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
