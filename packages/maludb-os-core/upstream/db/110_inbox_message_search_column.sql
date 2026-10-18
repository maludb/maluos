-- 110: mail search for the read tools (docs/build-specs/inbox.md). ADDITIVE.
--
-- mcp_mail_messages (db/057) left out the message's tsvector, so `search_mail` — which runs as
-- app_records_ro and has no grant on the base table — had nothing to search. Appended as the
-- LAST column, the way mcp_tickets and mcp_ticket_messages carry search_tsv. The WHERE clause,
-- the security barrier and every existing column are unchanged.
BEGIN;

CREATE OR REPLACE VIEW mcp_mail_messages WITH (security_barrier = true) AS
SELECT ms.id AS mail_message_id, ms.thread_id, ms.mailbox_id, ms.direction, ms.from_address::text,
       ms.from_name, ms.to_addresses::text[] AS to_addresses, ms.cc_addresses::text[] AS cc_addresses,
       ms.subject, ms.body_text, ms.snippet, ms.sent_at, ms.received_at, ms.sent_by_member_id,
       ms.is_draft, ms.has_attachments, ms.spam_score,
       ms.search AS search_tsv
FROM mail_messages ms
JOIN mail_threads t ON t.id = ms.thread_id
WHERE app_can_see_mailbox(ms.mailbox_id) OR t.assigned_member_id = app_current_member_id();

COMMIT;
