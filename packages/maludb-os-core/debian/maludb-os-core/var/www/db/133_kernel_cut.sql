-- 133: the kernel cut (2026-09-22).
--
-- The owner's decision: the Business OS is a kernel — the agents, the super-admins who administer
-- them, and single sign-on — and runs no business application. Every business module is removed:
-- CRM, Sales, Books, Expenses, Projects, Calendar, Time, Tickets, Inbox, Documents, Signatures,
-- Inventory, People (employment), Content, Portal & Forms, Reports, Assets, Company Profile, the
-- person half of My Work, the kernel's own command bar — and the cert-study fork's tables under
-- them. Design and inventory: docs/business-os-integration.md ("The cut"); the decisions in the
-- requirements (product vision, 2026-09-22).
--
-- NOT additive: this migration drops tables. The database was dumped to ~/cutover-backups/
-- certstudy-pre-kernel-cut.dump and the tree tagged pre-kernel-cut before it ran. Activity memory
-- is untouched (activity_log stays; MaluDB episodes stay).
--
-- Order matters: (1) what the kernel keeps but stored in a leaf moves first (department
-- handbooks); (2) kernel columns that point at leaf tables go, with their views recreated;
-- (3) the leaf views and tables, then the fork's; (4) the vocabulary — grants, navigation,
-- application rows, approval policies, tool grants — shrinks to the kernel's set.
--
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/133_kernel_cut.sql

BEGIN;

-- ---------------------------------------------------------------------------------------------
-- 1. Department handbooks: from Documents onto the department itself.
--    The runner's persona keeps reading runner_department_handbooks with the same columns, so
--    mcp/agent_runner/persona.py does not change. Edited on the department screen.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE departments ADD COLUMN handbook_markdown text;
UPDATE departments d SET handbook_markdown = h.body_markdown
  FROM runner_department_handbooks h WHERE h.department_id = d.id;

DROP VIEW runner_department_handbooks;
DROP VIEW mcp_departments;
ALTER TABLE departments DROP COLUMN handbook_document_id;

CREATE VIEW mcp_departments WITH (security_barrier = true) AS
SELECT d.id AS department_id, d.name::text AS name, d.description, d.parent_id,
       d.manager_member_id, mm.display_name AS manager_name,
       d.is_system, d.system_key, d.home_location_id, l.name AS home_location_name,
       d.monthly_budget_amount, d.budget_currency,
       (SELECT count(*) FROM department_members dm WHERE dm.department_id = d.id AND dm.left_at IS NULL) AS member_count,
       d.archived_at, d.created_at, pd.name::text AS parent_name,
       d.handbook_markdown, d.updated_at
  FROM departments d
  LEFT JOIN members mm ON mm.id = d.manager_member_id
  LEFT JOIN locations l ON l.id = d.home_location_id
  LEFT JOIN departments pd ON pd.id = d.parent_id
 WHERE app_is_insider();
GRANT SELECT ON mcp_departments TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_departments TO app_rw;

CREATE VIEW runner_department_handbooks AS
SELECT d.id AS department_id, d.name::text AS department_name, NULL::bigint AS document_id,
       (d.name::text || ' handbook') AS title, d.handbook_markdown AS body_markdown, d.updated_at
  FROM departments d
 WHERE btrim(coalesce(d.handbook_markdown, '')) <> '';
COMMENT ON VIEW runner_department_handbooks IS
    'The one live handbook per department, for the agent runner''s persona rendering: the department''s own handbook_markdown since db/133.';
GRANT SELECT ON runner_department_handbooks TO app_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON runner_department_handbooks TO app_rw;

-- ---------------------------------------------------------------------------------------------
-- 2. Kernel columns that pointed at leaf tables. Each view is recreated without the column.
-- ---------------------------------------------------------------------------------------------
DROP VIEW mcp_agent_escalations;
ALTER TABLE agent_escalations DROP COLUMN ticket_id;
CREATE VIEW mcp_agent_escalations WITH (security_barrier = true) AS
SELECT e.id AS escalation_id, e.agent_member_id, am.display_name AS agent_name, e.to_member_id,
       e.reason_kind, e.summary, e.entity_type, e.entity_id, e.approval_request_id,
       e.resolved_at, e.resolved_by, e.created_at
  FROM agent_escalations e JOIN members am ON am.id = e.agent_member_id
 WHERE e.to_member_id = app_current_member_id() OR app_can_see_agent(e.agent_member_id);
GRANT SELECT ON mcp_agent_escalations TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agent_escalations TO app_rw;

DROP VIEW mcp_agent_runs;
ALTER TABLE agent_runs DROP COLUMN project_id, DROP COLUMN task_id, DROP COLUMN campaign_id;
CREATE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id,
       r.location_id, r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id,
       r.harness, r.sdk_version, r.request_id, r.status, r.error,
       r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens, r.cost, r.currency,
       r.started_at, r.finished_at, r.instructions, r.result, r.parent_run_id, r.requested_by,
       r.approval_request_id
  FROM agent_runs r LEFT JOIN members am ON am.id = r.agent_member_id
 WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);
GRANT SELECT ON mcp_agent_runs TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agent_runs TO app_rw;

DROP VIEW mcp_prompt_ledger;
ALTER TABLE prompt_ledger DROP COLUMN project_id, DROP COLUMN task_id, DROP COLUMN campaign_id;
CREATE VIEW mcp_prompt_ledger WITH (security_barrier = true) AS
SELECT id AS ledger_id, occurred_at, agent_run_id, agent_member_id, acting_member_id, location_id,
       harness, sdk_version, provider, model_id, provider_model_id, request_id, call_kind, status,
       error_code, error_message, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
       latency_ms, cost, currency, payload_archived_at
  FROM prompt_ledger pl
 WHERE app_can_see_run(agent_member_id, acting_member_id);
GRANT SELECT ON mcp_prompt_ledger TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_prompt_ledger TO app_rw;

DROP VIEW mcp_applications;
ALTER TABLE applications DROP COLUMN recurring_expense_id;
CREATE VIEW mcp_applications WITH (security_barrier = true) AS
SELECT a.id AS application_id, a.name, a.app_key, a.category, a.description, a.vendor, a.is_self_hosted,
       a.is_builtin, a.module, a.location_id, l.name AS location_name, l.kind AS location_kind,
       a.owner_department_id, d.name::text AS owner_department_name, a.owner_member_id, om.display_name AS owner_name,
       a.url, a.version, a.criticality, a.status, a.health_status, a.last_health_check_at,
       app_can_use_application(a.id) AS i_can_use,
       a.notes, a.retired_at, a.created_at, a.catalog_key, a.business_area_id,
       g.name AS business_area_name, g.sort_order AS business_area_sort,
       (NOT a.is_builtin OR app_module_enabled(a.module)) AS module_enabled,
       a.sme_agent_member_id, sm.display_name AS sme_agent_name
  FROM applications a
  LEFT JOIN locations l ON l.id = a.location_id
  LEFT JOIN departments d ON d.id = a.owner_department_id
  LEFT JOIN members om ON om.id = a.owner_member_id
  LEFT JOIN nav_groups g ON g.id = a.business_area_id
  LEFT JOIN members sm ON sm.id = a.sme_agent_member_id
 WHERE app_is_insider();
GRANT SELECT ON mcp_applications TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_applications TO app_rw;

ALTER TABLE invitations DROP COLUMN share_organization_id;

-- The AI usage roll-up stays as the period statement the ledger exports (design, "Token
-- accounting"); its links to an expense and a journal entry go with the books.
DROP VIEW mcp_ai_usage_postings;
ALTER TABLE ai_usage_postings DROP COLUMN expense_id, DROP COLUMN journal_entry_id;
CREATE VIEW mcp_ai_usage_postings WITH (security_barrier = true) AS
SELECT p.id AS ai_usage_posting_id, p.period_start, p.period_end, p.provider, p.model_id,
       mr.display_name AS model_name, p.department_id, d.name::text AS department_name,
       p.agent_member_id, m.display_name AS agent_name, p.call_count, p.input_tokens, p.output_tokens,
       p.cache_read_tokens, p.cache_write_tokens, p.amount, p.currency, p.status, p.posted_at, p.note
  FROM ai_usage_postings p
  LEFT JOIN model_registry mr ON mr.id = p.model_id
  LEFT JOIN departments d ON d.id = p.department_id
  LEFT JOIN members m ON m.id = p.agent_member_id
 WHERE app_is_insider() AND (app_has_module('ledger') OR app_is_super_admin());
GRANT SELECT ON mcp_ai_usage_postings TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_ai_usage_postings TO app_rw;

-- ---------------------------------------------------------------------------------------------
-- 3. The leaf modules' tables and views, then the fork's. CASCADE takes the mcp_* views, RLS
--    policies, triggers and the foreign keys between leaf tables; nothing in the kernel depends
--    on them any more (checked with pg_depend before this was written). business_hours stays:
--    opening hours are a business setting, not the Helpdesk's.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION app_my_work(integer, integer);          -- My Work's person half (db/118)

DROP TABLE IF EXISTS
    -- CRM
    interactions, deals, deal_stages, pipelines, contacts, organizations,
    -- Sales
    disputes, refunds, provider_events, provider_payments, payouts, payment_links, payment_providers,
    credit_notes, payment_allocations, payments, invoice_lines, invoices, quote_lines, quotes, catalog_items, tax_rates,
    -- Books
    bank_reconciliations, bank_transactions, bank_accounts, gl_posting_rules, journal_lines, journal_entries, fiscal_periods, gl_accounts,
    -- Expenses
    accountant_exports, expenses, recurring_expenses, expense_categories,
    -- Projects
    task_checklist_items, task_dependencies, tasks, milestones, project_members, projects,
    -- Calendar
    availability_blocks, appointment_resources, appointment_assignees, appointments, bookable_resources, appointment_types,
    -- Time
    time_timers, time_entries,
    -- Tickets (business_hours stays)
    ticket_messages, tickets, sla_policies, ticket_categories,
    -- Inbox
    mail_rules, mail_thread_reads, mail_attachments, mail_messages, mail_threads, mailboxes,
    -- Documents
    desk_imports, document_links, document_versions, documents, folders,
    -- Signatures
    signature_events, signature_signers, signature_requests, signature_providers,
    -- Inventory
    purchase_order_lines, purchase_orders, stock_movements, stock_levels, stock_locations, products,
    -- People: employment
    leave_requests, leave_balances, leave_types, pay_run_lines, pay_run_items, pay_runs, compensation_changes, employment_profiles,
    -- Content
    content_metrics, content_variant_media, content_variants, content_items, campaigns, channels,
    -- Portal & forms
    form_submissions, form_fields, forms, portal_settings,
    -- Reports
    dashboard_widgets, dashboards, report_schedules, report_runs, report_definitions,
    -- Assets
    asset_depreciation, asset_maintenance, asset_movements, assets, asset_categories,
    -- Company profile
    company_profile_items, company_profile, company_profile_media
    CASCADE;

-- The functions the dropped views and triggers used (their views went with the tables above).
DROP FUNCTION IF EXISTS gl_lines_immutable();
DROP FUNCTION app_can_see_project(bigint);
DROP FUNCTION app_can_manage_asset(bigint);
DROP FUNCTION app_can_see_asset(bigint, bigint);

-- The cert-study fork: never ported, retired with the React cut-over, tables kept until now.
DROP TABLE IF EXISTS
    resource_endorsements, resource_exams, resource_domains, resources,
    event_rsvps, community_events, community_settings, calendar_feed_tokens,
    replies, study_issues, plan_comments, plan_items, study_plans, study_sessions,
    exam_attempts, exam_domains, exams
    CASCADE;

-- ---------------------------------------------------------------------------------------------
-- 4. The vocabulary shrinks to the kernel's.
-- ---------------------------------------------------------------------------------------------
-- Module grants: only the kernel's applications can be granted.
DELETE FROM module_grants WHERE module NOT IN ('hr', 'locations', 'applications', 'approvals', 'ledger', 'evals');
ALTER TABLE module_grants DROP CONSTRAINT module_grants_module_check;
ALTER TABLE module_grants ADD CONSTRAINT module_grants_module_check
    CHECK (module IN ('hr', 'locations', 'applications', 'approvals', 'ledger', 'evals'));

-- Navigation: the leaf entries go (member_nav_hidden cascades). my-work was locked; it is gone.
DELETE FROM nav_items WHERE item_key IN ('schedule', 'my-work', 'inbox', 'forms', 'tickets', 'contacts', 'deals', 'invoices',
    'books', 'reports', 'expenses', 'signatures', 'content', 'time', 'documents', 'projects', 'inventory', 'people',
    'company', 'assets');

-- The built-in application rows of the removed modules, and their catalog entries.
DELETE FROM applications WHERE is_builtin AND app_key IN ('inventory', 'portal', 'sales', 'inbox', 'crm', 'projects', 'helpdesk',
    'calendar', 'people', 'expenses', 'documents', 'time', 'content', 'signatures', 'reports', 'books', 'assets');
DELETE FROM application_catalog WHERE kind = 'builtin' AND catalog_key IN ('inventory', 'portal', 'sales', 'inbox', 'crm', 'projects',
    'helpdesk', 'calendar', 'people', 'expenses', 'documents', 'time', 'content', 'signatures', 'reports', 'books', 'assets');

-- Approval policies that named a leaf action. What stays: invitation.send, record_share.create,
-- *.delete, memory.remember_shared, memory.core_set.
DELETE FROM approval_policies WHERE action_pattern IN ('payment_link.create', 'invoice.send_reminder', 'content_variant.schedule',
    'content_variant.publish', 'statement.send', 'invoice.write_off', 'invoice.send', 'expense.mark_paid', 'expense.create',
    'invoice.void', 'recurring_expense.create', 'ticket.reply', 'quote.send', 'credit_note.issue', 'refund.create',
    'compensation_change.create', 'ai_usage_posting.void', 'contact.enable_portal', 'report_schedule.save', 'purchase_order.send',
    'ai_usage_posting.post', 'stock_movement.write_off', 'mail_message.send', 'signature_request.remind', 'pay_run.pay',
    'pay_run.approve', 'signature_request.send', 'company_profile.publish', 'asset.dispose', 'asset_depreciation.post');

-- Tool grants on tools that no longer exist (the Accounting agents are re-versioned by hand after this).
DELETE FROM agent_tool_grants WHERE tool_name IN (
    'find_contacts', 'get_organization', 'get_contact', 'get_deal', 'pipeline', 'sales_performance', 'contact_hygiene', 'lead_sources',
    'find_invoices', 'get_invoice', 'receivables_aging', 'revenue_summary', 'customer_statement', 'quotes_pipeline', 'unbilled_work',
    'financial_statement', 'account_activity', 'find_journal_entries', 'bank_status', 'posting_rules', 'books_audit',
    'spend_summary', 'find_expenses', 'bills_due', 'recurring_costs', 'accountant_export_status',
    'find_projects', 'get_project', 'find_tasks', 'upcoming_milestones',
    'schedule', 'find_free_time', 'schedule_conflicts', 'job_counts', 'time_summary', 'missing_timesheets',
    'find_tickets', 'get_ticket', 'sla_status', 'similar_tickets', 'ticket_metrics',
    'find_mail_threads', 'mail_thread', 'search_mail', 'mailbox_stats', 'mailbox_rules',
    'find_documents', 'get_document', 'record_documents', 'compare_document_versions',
    'find_signature_requests', 'signature_audit', 'find_products', 'stock_levels', 'stock_movements', 'product_sales', 'purchase_orders',
    'find_people', 'employment_profile', 'payroll_summary', 'pay_runs', 'leave',
    'content_calendar', 'content_pipeline', 'content_performance', 'channel_health', 'find_content', 'unapproved_publishing',
    'find_forms', 'form_submissions', 'portal_status', 'find_reports', 'run_report', 'report_schedules',
    'find_assets', 'get_asset', 'asset_summary', 'company_profile', 'my_work', 'find_screen', 'navigate',
    'task_create', 'contact_delete', 'interaction_delete', 'interaction_log');

-- Tags, comments and shares that hung on leaf records.
DELETE FROM taggings WHERE entity_type IN ('organization', 'contact', 'deal', 'project', 'task', 'invoice', 'quote', 'expense', 'ticket', 'document', 'appointment', 'content_item');
DELETE FROM record_comments WHERE entity_type IN ('organization', 'contact', 'deal', 'project', 'task', 'invoice', 'quote', 'expense', 'ticket', 'document', 'appointment', 'content_item');
DELETE FROM record_shares WHERE entity_type IN ('organization', 'contact', 'deal', 'project', 'task', 'invoice', 'quote', 'expense', 'ticket', 'document', 'appointment', 'content_item');

COMMIT;
