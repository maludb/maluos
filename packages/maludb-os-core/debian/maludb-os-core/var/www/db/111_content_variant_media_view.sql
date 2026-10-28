-- 111: a read view for content_variant_media (docs/build-specs/content.md). ADDITIVE.
--
-- db/040 gave the media table no mcp_* view, and "every list/detail screen reads an mcp_* view"
-- (db/063). An attachment is visible only to someone who can see BOTH the content item (through
-- mcp_content_variants) and the document (through mcp_documents) — a variant must never become
-- a way to learn the title of a document the caller may not open.
BEGIN;

CREATE OR REPLACE VIEW mcp_content_variant_media WITH (security_barrier = true) AS
SELECT vm.content_variant_id, cv.content_item_id, vm.document_id, d.title AS document_title,
       d.mime_type, d.size_bytes, vm.sort_order
FROM content_variant_media vm
JOIN mcp_content_variants cv ON cv.content_variant_id = vm.content_variant_id
JOIN mcp_documents d         ON d.document_id = vm.document_id;

GRANT SELECT ON mcp_content_variant_media TO app_rw, app_records_ro;

COMMIT;
