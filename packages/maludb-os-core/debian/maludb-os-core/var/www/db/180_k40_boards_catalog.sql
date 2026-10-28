-- 180: K40 — the Boards application in the catalog (D1/D15 of /srv/apps/boards/docs/boards-design.md §13, the owner
-- approved 2026-10-10): a Miro-style infinite whiteboard where people and the OS's agents work on the same canvas — sticky
-- notes, shapes, text, connectors that stay attached, frames, pen, images and files, comments pinned to the canvas — with
-- live cursors and edits through the application's own WebSocket relay over server-authoritative rows. Category
-- 'communication' is already admitted by both checks (Spaces uses it; db/172, db/175, db/178 kept it), so nothing is
-- widened. Seeded so every installation shows it under Operations ("from us, not installed") and the installer's apply
-- finds its row. On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/180_k40_boards_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'boards', 'Boards',
       'The business''s infinite whiteboard: sticky notes, shapes, text, connectors that stay attached, frames, freehand pen, images and files, and comments pinned to the canvas — with everyone''s cursor and every change live on every screen. Boards shared with people, departments and agents at view, comment, edit or full; folders, favourites, templates, history with named versions and restore, PNG and SVG export, and a text outline of every board. The OS''s agents work on the canvas like colleagues: the Boards Expert answers and acts from the command bar, the Facilitator clusters, summarises and lays out a workshop when mentioned in a comment, and their edits appear live. Optional; installed on request.',
       'feather-pen-tool', g.id, 'ours', NULL, 'communication', 0
  FROM nav_groups g WHERE g.name = 'Operations'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
