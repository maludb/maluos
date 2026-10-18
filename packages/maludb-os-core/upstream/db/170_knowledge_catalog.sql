-- 170: the Knowledge application in the catalog (K25 of /srv/apps/knowledge/docs/knowledge-design.md §12; owner's D15, 2026-10-05) — the
-- business's knowledge bases, built first for laws, codes and regulations: documents parsed into provisions, guidelines and focus areas
-- compiled into a MaluDB knowledge graph, asked through an ask-me-anything window, a token API and the agents. Seeded so every
-- installation shows it under Operations ("from us, not installed") and the installer's apply finds its row. On request, not a default.
-- Additive.
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'knowledge', 'Knowledge',
       'The business''s knowledge bases — upload documents, write guidelines, name the areas that matter, and ask the knowledge graph it builds: in an ask-me-anything window, through a token API from other applications, or through the OS''s agents. Built first for laws, codes and regulations: a code is parsed into its numbered provisions with definitions and cross-references, a jurisdiction''s amendments are layered over the model edition by a curator, and every answer quotes the provision with its number, edition and date or says the base holds nothing on the question. Optional; installed on request.',
       'feather-book-open', g.id, 'ours', NULL, 'documents', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
