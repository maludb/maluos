-- 176: the DocCloud application in the catalog (K31 of /srv/apps/doccloud/docs/doccloud-design.md §12; the owner's D15, 2026-10-09) — the
-- business's document cloud, what Dropbox, Box and Nextcloud are to a business: libraries (personal, group, shared) of folders and
-- documents with versions and de-duplicated blobs, groups, visibility by ownership and membership with inheritance, secure links and
-- file requests, tags, a keyword search in PostgreSQL, and a dedicated document graph in a MaluDB memory database of its own — never
-- the agents' memory, never the default ask-me-anything. Category 'storage' is already admitted by both checks (db/172, db/175), so
-- nothing is widened. Seeded so every installation shows it under Operations ("from us, not installed") and the installer's apply finds
-- its row. On request, not a default. Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'doccloud', 'DocCloud',
       'The business''s document cloud — what Dropbox, Box and Nextcloud are to a business: libraries of folders and documents with every version kept and the bytes stored once, personal libraries, group libraries that outlive their members and shared libraries; sharing to people, groups, departments, agents and, through expiring links and file requests, the outside; tags, a keyword search over the words of every document, and a dedicated knowledge graph for finding documents that is kept apart from what the agents remember. Every search answers only what the asker may see. Optional; installed on request.',
       'feather-hard-drive', g.id, 'ours', NULL, 'storage', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
