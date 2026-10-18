-- 066_gapless_document_numbers.sql
-- An issued invoice sequence must have no holes.
--
-- Decided 2026-09-18, answering the escalation the Sales & invoicing slice recorded rather
-- than guessed (docs/build-specs/sales-invoicing.md, "Escalations raised while building", 1).
--
-- The problem: `number` was NOT NULL, so `next_document_number()` ran inside the INSERT and a
-- document owned a number from the moment it existed. Deleting a draft therefore burned one,
-- leaving a gap in the issued sequence. Unique and mostly-ascending satisfies the US; much of
-- the EU, the UK, Italy and Latin America require the issued sequence to be provably gapless,
-- and an auditor reads a hole as a deleted invoice.
--
-- The fix: a number is taken when the document is ISSUED, not when it is drafted. `number`
-- becomes nullable; a draft carries NULL and the screens show "Draft". `send_invoice()` and
-- `issue_credit_note()` already assign with
-- `COALESCE(number, next_document_number(...))` inside the same transaction as the status
-- change, so a send that rolls back returns the number to the sequence -- `document_sequences`
-- is a TABLE updated transactionally, not a Postgres sequence, which is exactly why gapless
-- works here and would not with a bare SEQUENCE.
--
-- Scope: invoices and credit notes, which are tax documents. QUOTES KEEP CREATION-TIME
-- NUMBERING on purpose -- a quote is not a tax document, no jurisdiction requires its sequence
-- to be gapless, and a quote that never ships is a normal outcome rather than a hole to
-- explain. `quotes.number` stays NOT NULL.
--
-- Existing rows already hold numbers and are untouched; UNIQUE is unchanged, and NULLs do not
-- collide under it.

BEGIN;

ALTER TABLE invoices     ALTER COLUMN number DROP NOT NULL;
ALTER TABLE credit_notes ALTER COLUMN number DROP NOT NULL;

COMMENT ON COLUMN invoices.number IS
    'Taken on send, not at creation, so the issued sequence is gapless (db/066). NULL = draft.';
COMMENT ON COLUMN credit_notes.number IS
    'Taken on issue, not at creation, so the issued sequence is gapless (db/066). NULL = draft.';

-- A document that has left the building must carry a number: the gapless rule is about the
-- ISSUED sequence, and a sent invoice without a number would be a hole of a different kind.
ALTER TABLE invoices ADD CONSTRAINT invoices_issued_have_numbers
    CHECK (status = 'draft' OR number IS NOT NULL);
ALTER TABLE credit_notes ADD CONSTRAINT credit_notes_issued_have_numbers
    CHECK (status = 'draft' OR number IS NOT NULL);

COMMIT;
