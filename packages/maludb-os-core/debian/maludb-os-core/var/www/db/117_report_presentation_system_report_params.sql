-- 117: how a saved report is drawn, and working parameters for the starter set. ADDITIVE.
-- (docs/build-specs/reports.md)
--
-- db/062 kept `visualization` (table / bar / …) but nowhere to say WHICH column names a row and
-- which columns are drawn. `presentation` = {"label": col, "values": [col…], "columns": [col…]};
-- '{}' means "work it out from the rows". Appended to mcp_report_definitions as the LAST column;
-- the WHERE clause, the security barrier and every existing column are unchanged.
BEGIN;

ALTER TABLE report_definitions ADD COLUMN IF NOT EXISTS presentation jsonb NOT NULL DEFAULT '{}';

CREATE OR REPLACE VIEW mcp_report_definitions WITH (security_barrier = true) AS
SELECT r.id AS report_id, r.key, r.name, r.description, r.category, r.module, r.server,
       r.tool_name, r.params, r.prompt_params, r.visualization, r.is_system, r.owner_member_id,
       r.department_id, r.is_shared, r.archived_at,
       (SELECT max(started_at) FROM report_runs rr WHERE rr.report_id = r.id) AS last_run_at,
       r.presentation
FROM report_definitions r
WHERE app_is_insider()
  AND app_has_module(r.module)
  AND (r.is_shared OR r.owner_member_id = app_current_member_id());

-- The starter set was seeded before its tools existed; give each the params its tool now takes.
-- Only rows still exactly as seeded ('{}' params) are touched, so an owner's edit is never undone.
UPDATE report_definitions SET params = '{"group_by": "department", "period": "this_month"}', prompt_params = '{period}',
       presentation = '{"label": "label", "values": ["cost"]}'
 WHERE key = 'ai_spend_by_department' AND is_system AND params = '{}';
UPDATE report_definitions SET params = '{"group_by": "project", "period": "this_month"}', prompt_params = '{period}',
       presentation = '{"label": "label", "values": ["hours", "billable_hours"]}'
 WHERE key = 'time_by_project' AND is_system AND params = '{}';
-- 'receivables' never existed as a tool: the tool is receivables_aging (mcp/business_sales.py).
UPDATE report_definitions SET tool_name = 'receivables_aging', prompt_params = '{}',
       presentation = '{"label": "organization_name", "values": ["total_due"]}'
 WHERE key = 'receivables_aging' AND is_system AND params = '{}' AND tool_name = 'receivables';
UPDATE report_definitions SET params = '{"statement": "pl"}', prompt_params = '{period}',
       presentation = '{"label": "name", "values": ["amount"], "columns": ["code", "name", "account_type", "amount", "compare_amount", "variance"]}'
 WHERE key = 'profit_and_loss' AND is_system AND params = '{}';
UPDATE report_definitions SET params = '{"status": "open"}', prompt_params = '{}'
 WHERE key = 'open_tickets_by_age' AND is_system AND params = '{}';

COMMIT;
