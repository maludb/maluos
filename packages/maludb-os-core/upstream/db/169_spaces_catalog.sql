-- 169: the Spaces application in the catalog (K20 of /srv/apps/spaces/docs/spaces-design.md §12; owner's D15, 2026-10-05) — the
-- collaborative workspace from us (Notion and Slack in one: spaces, pages from blocks, a wiki, databases with views, channels with
-- threads; OS agents as members), seeded so every installation shows it under Operations ("from us, not installed") and the
-- installer's apply finds its row. A default install (D3, K21 — bin/install_default_applications.sh). Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'spaces', 'Spaces',
       'The business''s collaborative workspace — Notion and Slack in one: spaces holding pages built from blocks, a wiki with owners and verification, databases with typed properties and table / board / gallery / list / calendar / timeline views, and channels with threads, reactions and direct messages; one search across all of it; page history, comments, notifications, import and export, a public page door. The OS''s agents are members: mentioned, DM''d, added to channels and pages. A default of every installation.',
       'feather-layers', g.id, 'ours', NULL, 'communication', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
