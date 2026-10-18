-- 181: K43 — the MaluMail application in the catalog (D1/D15 of /srv/apps/malumail/docs/malumail-design.md §13, the owner
-- approved 2026-10-11): a Gmail-style webmail over the business's MaluMail mailboxes for people AND the OS's agents —
-- conversations across folders, search with Gmail's operators, safe HTML, compose with undo and schedule send, labels,
-- snooze, mailboxes shared by their owners — with people overseeing what agents receive and send (policies, a review queue,
-- unscreened senders), and the super-admins creating mailboxes and forwarding addresses through MaluMail's Mailbox MCP.
-- Category 'email' is already admitted by both checks (Google Workspace and Microsoft 365 use it), so nothing is widened.
-- Seeded in the unnamed top area beside those two, so every installation shows it ("from us, not installed") and the
-- installer's apply finds its row. On request, not a default (D15). Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/181_k43_malumail_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'malumail', 'MaluMail',
       'The business''s webmail over its MaluMail mailboxes, for people and for the OS''s agents: conversations across folders, search with Gmail''s operators, mail shown safely with remote images on request, compose with undo send, schedule send and drafts, labels, stars and snooze, and mailboxes their owners share at view, triage, send or full, every look by another person logged. People oversee their agents'' mail: an agent''s outgoing mail is held for review by its overseers until they widen its policy, mail from unknown outside senders waits for a person before an agent sees it, and arriving mail reaches an agent as fenced, untrusted text. The super-admins create mailboxes and forwarding addresses without leaving the OS. The Mail Expert answers and drafts from the command bar; the Mail Clerk sends the overseers a morning note. Optional; installed on request.',
       'feather-mail', g.id, 'ours', NULL, 'email', 0
  FROM nav_groups g WHERE g.name = ''
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
