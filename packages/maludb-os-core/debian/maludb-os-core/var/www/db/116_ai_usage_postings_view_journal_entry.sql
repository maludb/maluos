-- 116: AI Ops (docs/build-specs/ai-ops.md). ADDITIVE.
--
-- mcp_ai_usage_postings (db/055) predates the general ledger (db/056 added
-- ai_usage_postings.journal_entry_id), so a posting could not say which journal entry carries it.
-- Appended as the LAST column; the WHERE clause, the security barrier and every existing column
-- are unchanged.
BEGIN;

CREATE OR REPLACE VIEW mcp_ai_usage_postings WITH (security_barrier = true) AS
SELECT p.id AS ai_usage_posting_id, p.period_start, p.period_end, p.provider,
       p.model_id, mr.display_name AS model_name, p.department_id, d.name::text AS department_name,
       p.agent_member_id, m.display_name AS agent_name, p.call_count, p.input_tokens,
       p.output_tokens, p.cache_read_tokens, p.cache_write_tokens, p.amount, p.currency,
       p.expense_id, p.status, p.posted_at, p.note,
       p.journal_entry_id
FROM ai_usage_postings p
LEFT JOIN model_registry mr ON mr.id = p.model_id
LEFT JOIN departments d     ON d.id = p.department_id
LEFT JOIN members m         ON m.id = p.agent_member_id
WHERE app_is_insider()
  AND (app_has_module('ledger') OR app_has_module('expenses') OR app_is_super_admin());

COMMIT;
