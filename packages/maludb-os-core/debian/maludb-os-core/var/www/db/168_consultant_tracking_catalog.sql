-- 168: the Consultant Tracking application in the catalog (K17 of /srv/apps/consultant_tracking/docs/consultant-tracking-design.md
-- §12; owner's D14, 2026-10-04) — the professional-services time, expenses and billing application from us for a technical or
-- AI consultancy, seeded so every installation shows it under Sales & Service ("from us, not installed") and the installer's
-- apply finds its row. Not a default install (D3); installed on request, with the standing departments granted. Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'consultant_tracking', 'Consultant Tracking',
       'Professional services for a technical or AI consultancy: clients and engagements (time-and-materials with expenses, or fixed bid against milestones), weekly timesheets with a timer, expenses with receipts, hosting and model-usage pass-through allocated from the kernel''s AI statement, invoices by email and secure link, unbilled work, utilization, realization and margin. Bills, never the books — the accounting system reads it through the kernel. Optional — installed on request.',
       'feather-briefcase', g.id, 'ours', NULL, 'other', 0
  FROM nav_groups g WHERE g.name = 'Sales & Service'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
