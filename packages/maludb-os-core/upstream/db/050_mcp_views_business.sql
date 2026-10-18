-- 050_mcp_views_business.sql
-- The Business OS read surface for the MCP servers: one visibility-scoped view per business
-- table (same design as 012_views.sql — owner-rights views with security_barrier, the
-- visibility predicate embedded, read roles granted these views and nothing else).
-- Aggregate/question-shaped views (aging, utilization, spend roll-ups, audit checks) are
-- designed with the MCP tool surface (build plan 1.5) and land in a later migration.
--
-- Visibility rules (docs/business-os-schema.md):
--   app_can_see(module, owner, department, entity_type, entity_id, organization_id)
--   app_is_insider()  — owner/manager/staff, human or agent (never External)
--   Secrets never appear: no secret ids, no token hashes, no provider credentials.

BEGIN;

-- ==========================================================================
-- FOUNDATION
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_team_directory WITH (security_barrier = true) AS
SELECT m.id AS member_id, m.display_name, m.member_kind, m.business_role, m.job_title,
       m.timezone, m.status, m.joined_at,
       (SELECT array_agg(d.name::text ORDER BY dm.is_primary DESC, d.name)
          FROM department_members dm JOIN departments d ON d.id = dm.department_id
         WHERE dm.member_id = m.id AND dm.left_at IS NULL) AS departments,
       CASE WHEN app_can_admin_member(m.id) THEN m.email::text END AS email,
       CASE WHEN app_can_admin_member(m.id) THEN m.phone END AS phone,
       CASE WHEN app_is_super_admin() OR m.id = app_current_member_id()
            THEN m.totp_enabled_at IS NOT NULL END AS has_2fa,                          -- A4
       CASE WHEN app_is_super_admin() OR m.id = app_current_member_id()
            THEN m.last_login_at END AS last_login_at                                    -- A8, DB6
FROM members m
WHERE app_is_insider() AND m.status IN ('active', 'suspended');

CREATE OR REPLACE VIEW mcp_departments WITH (security_barrier = true) AS
SELECT d.id AS department_id, d.name::text AS name, d.description, d.parent_id,
       d.manager_member_id, mm.display_name AS manager_name, d.handbook_document_id,
       d.is_system, d.system_key, d.home_location_id, l.name AS home_location_name,
       d.monthly_budget_amount, d.budget_currency,
       (SELECT count(*) FROM department_members dm
         WHERE dm.department_id = d.id AND dm.left_at IS NULL) AS member_count,
       d.archived_at, d.created_at
FROM departments d
LEFT JOIN members mm ON mm.id = d.manager_member_id
LEFT JOIN locations l ON l.id = d.home_location_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_department_members WITH (security_barrier = true) AS
SELECT dm.department_id, d.name::text AS department_name, dm.member_id, m.display_name,
       m.member_kind, dm.is_primary, dm.joined_at, dm.left_at
FROM department_members dm
JOIN departments d ON d.id = dm.department_id
JOIN members m ON m.id = dm.member_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_module_grants WITH (security_barrier = true) AS
SELECT g.member_id, m.display_name, g.module, g.access, g.created_at
FROM module_grants g JOIN members m ON m.id = g.member_id
WHERE app_can_admin_member(g.member_id);

CREATE OR REPLACE VIEW mcp_record_shares WITH (security_barrier = true) AS
SELECT s.id AS share_id, s.entity_type, s.entity_id, s.member_id, m.display_name,
       s.access, s.expires_at, s.created_at
FROM record_shares s JOIN members m ON m.id = s.member_id
WHERE s.revoked_at IS NULL
  AND app_can_admin_member(s.member_id);

CREATE OR REPLACE VIEW mcp_token_list WITH (security_barrier = true) AS           -- A5, X7
SELECT t.id AS token_id, t.member_id, m.display_name, t.label, t.last_used_at,
       t.expires_at, t.created_at
FROM mcp_access_tokens t JOIN members m ON m.id = t.member_id
WHERE t.revoked_at IS NULL
  AND app_can_admin_member(t.member_id);

CREATE OR REPLACE VIEW mcp_business_invitations WITH (security_barrier = true) AS    -- A3
SELECT iv.id AS invitation_id, iv.email::text AS email, iv.business_role_granted,
       iv.invited_by, ib.display_name AS invited_by_name, iv.expires_at, iv.created_at
FROM invitations iv JOIN members ib ON ib.id = iv.invited_by
WHERE (app_is_super_admin() OR app_is_admin_of(iv.department_id))
  AND iv.accepted_at IS NULL AND iv.revoked_at IS NULL;

CREATE OR REPLACE VIEW mcp_business_settings WITH (security_barrier = true) AS
SELECT business_name, legal_name, base_currency, timezone, fiscal_year_start_month,
       default_payment_terms_days, deal_quiet_days, prompt_payload_retention_days
FROM business_settings
WHERE app_current_member_id() IS NOT NULL;

CREATE OR REPLACE VIEW mcp_tags WITH (security_barrier = true) AS
SELECT t.id AS tag_id, t.name::text AS name, t.color FROM tags t
WHERE app_is_insider();

-- ==========================================================================
-- CONTACTS & CRM
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_organizations WITH (security_barrier = true) AS
SELECT o.id AS organization_id, o.name, o.legal_name, o.website, o.email::text AS email, o.phone,
       o.industry, o.address, o.relationship_types, o.owner_member_id,
       om.display_name AS owner_name, o.department_id, o.source, o.source_campaign_id,
       o.source_content_item_id, o.payment_terms_days, o.currency, o.notes, o.merged_into_id,
       o.archived_at, o.search_tsv, o.created_by, o.created_at, o.updated_at
FROM organizations o
LEFT JOIN members om ON om.id = o.owner_member_id
WHERE o.anonymized_at IS NULL
  AND app_can_see('contacts', o.owner_member_id, o.department_id, 'organization', o.id, o.id);

CREATE OR REPLACE VIEW mcp_contacts WITH (security_barrier = true) AS
SELECT c.id AS contact_id, c.organization_id, o.name AS organization_name, c.first_name,
       c.last_name, c.full_name, c.email::text AS email, c.phone, c.mobile, c.job_title,
       c.is_primary_contact, c.relationship_types, c.owner_member_id,
       cm.display_name AS owner_name, c.department_id, c.source, c.source_campaign_id,
       c.source_content_item_id, c.portal_member_id, c.address, c.notes, c.merged_into_id,
       c.archived_at, c.search_tsv, c.created_by, c.created_at, c.updated_at
FROM contacts c
LEFT JOIN organizations o ON o.id = c.organization_id
LEFT JOIN members cm ON cm.id = c.owner_member_id
WHERE c.anonymized_at IS NULL
  AND app_can_see('contacts', c.owner_member_id, c.department_id, 'contact', c.id, c.organization_id);

CREATE OR REPLACE VIEW mcp_pipelines WITH (security_barrier = true) AS
SELECT p.id AS pipeline_id, p.name, p.is_default, s.id AS stage_id, s.name AS stage_name,
       s.stage_kind, s.probability, s.sort_order
FROM pipelines p JOIN deal_stages s ON s.pipeline_id = p.id
WHERE p.archived_at IS NULL AND s.archived_at IS NULL AND app_has_module('contacts')
  AND NOT app_is_external();

CREATE OR REPLACE VIEW mcp_deals WITH (security_barrier = true) AS
SELECT d.id AS deal_id, d.title, d.organization_id, o.name AS organization_name,
       d.primary_contact_id, d.pipeline_id, d.stage_id, s.name AS stage_name, s.stage_kind,
       d.stage_entered_at, d.value, d.currency,
       COALESCE(d.probability_override, s.probability) AS probability,
       round(d.value * COALESCE(d.probability_override, s.probability) / 100, 2) AS weighted_value,
       d.expected_close_date, d.closed_at, d.lost_reason, d.owner_member_id,
       dm.display_name AS owner_name, d.department_id, d.source, d.source_campaign_id,
       d.source_content_item_id, d.description, d.archived_at, d.search_tsv,
       (SELECT max(i.occurred_at) FROM interactions i WHERE i.deal_id = d.id) AS last_interaction_at,
       d.created_by, d.created_at, d.updated_at
FROM deals d
JOIN deal_stages s ON s.id = d.stage_id
LEFT JOIN organizations o ON o.id = d.organization_id
LEFT JOIN members dm ON dm.id = d.owner_member_id
WHERE NOT app_is_external()
  AND app_can_see('contacts', d.owner_member_id, d.department_id, 'deal', d.id, NULL);

CREATE OR REPLACE VIEW mcp_interactions WITH (security_barrier = true) AS
SELECT i.id AS interaction_id, i.kind, i.direction, i.occurred_at, i.organization_id,
       i.contact_id, i.deal_id, i.member_id, m.display_name AS member_name, i.subject, i.body,
       i.duration_minutes, i.search_tsv, i.created_at
FROM interactions i
LEFT JOIN members m ON m.id = i.member_id
LEFT JOIN deals d ON d.id = i.deal_id
LEFT JOIN organizations o ON o.id = i.organization_id
LEFT JOIN contacts c ON c.id = i.contact_id
WHERE NOT app_is_external()
  AND app_can_see('contacts', i.member_id,
                  COALESCE(d.department_id, o.department_id, c.department_id),
                  'interaction', i.id, NULL);

-- ==========================================================================
-- PROJECTS & TASKS
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_projects WITH (security_barrier = true) AS
SELECT p.id AS project_id, p.code, p.name, p.description, p.organization_id,
       o.name AS organization_name, p.deal_id, p.department_id, p.owner_member_id,
       pm.display_name AS owner_name, p.status, p.start_date, p.due_date, p.completed_at,
       p.billing_type, p.budget_hours, p.budget_amount, p.currency,
       CASE WHEN NOT app_is_external() THEN p.hourly_rate END AS hourly_rate,
       (SELECT count(*) FROM tasks t WHERE t.project_id = p.id AND t.status <> 'cancelled') AS tasks_total,
       (SELECT count(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'done') AS tasks_done,
       p.archived_at, p.search_tsv, p.created_at, p.updated_at
FROM projects p
LEFT JOIN organizations o ON o.id = p.organization_id
LEFT JOIN members pm ON pm.id = p.owner_member_id
WHERE app_can_see('projects', p.owner_member_id, p.department_id, 'project', p.id, p.organization_id)
   OR EXISTS (SELECT 1 FROM project_members x
               WHERE x.project_id = p.id AND x.member_id = app_current_member_id());

CREATE OR REPLACE VIEW mcp_project_members WITH (security_barrier = true) AS
SELECT x.project_id, x.member_id, m.display_name, m.member_kind, x.role, x.added_at
FROM project_members x
JOIN mcp_projects p ON p.project_id = x.project_id
JOIN members m ON m.id = x.member_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_milestones WITH (security_barrier = true) AS
SELECT ms.id AS milestone_id, ms.project_id, p.name AS project_name, ms.name, ms.due_date,
       ms.completed_at, ms.sort_order
FROM milestones ms
JOIN mcp_projects p ON p.project_id = ms.project_id;

CREATE OR REPLACE VIEW mcp_tasks WITH (security_barrier = true) AS
SELECT t.id AS task_id, t.project_id, p.name AS project_name, t.milestone_id, t.parent_task_id,
       t.organization_id, t.ticket_id, t.title, t.description, t.task_type,
       t.assignee_member_id, am.display_name AS assignee_name, am.member_kind AS assignee_kind,
       t.department_id, t.status, t.blocked_reason, t.priority, t.start_date, t.due_date,
       t.estimate_hours, t.completed_at,
       EXISTS (SELECT 1 FROM task_dependencies td JOIN tasks dt ON dt.id = td.depends_on_task_id
                WHERE td.task_id = t.id AND dt.status NOT IN ('done', 'cancelled')) AS has_open_dependencies,
       t.search_tsv, t.created_by, t.created_at, t.updated_at
FROM tasks t
LEFT JOIN projects p ON p.id = t.project_id
LEFT JOIN members am ON am.id = t.assignee_member_id
WHERE app_is_insider()
  AND (t.assignee_member_id = app_current_member_id()
       OR t.created_by = app_current_member_id()
       OR app_can_see('projects', p.owner_member_id, COALESCE(t.department_id, p.department_id),
                      'task', t.id, NULL)
       OR EXISTS (SELECT 1 FROM project_members x
                   WHERE x.project_id = t.project_id AND x.member_id = app_current_member_id()));

CREATE OR REPLACE VIEW mcp_task_dependencies WITH (security_barrier = true) AS
SELECT td.task_id, td.depends_on_task_id, dt.title AS depends_on_title, dt.status AS depends_on_status
FROM task_dependencies td
JOIN mcp_tasks t ON t.task_id = td.task_id
JOIN tasks dt ON dt.id = td.depends_on_task_id;

CREATE OR REPLACE VIEW mcp_task_checklist_items WITH (security_barrier = true) AS
SELECT ci.id AS checklist_item_id, ci.task_id, ci.body, ci.done_at, ci.sort_order
FROM task_checklist_items ci
JOIN mcp_tasks t ON t.task_id = ci.task_id;

-- ==========================================================================
-- SCHEDULING
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_appointment_types WITH (security_barrier = true) AS
SELECT id AS appointment_type_id, name, default_duration_minutes, is_billable, department_id
FROM appointment_types
WHERE archived_at IS NULL AND app_is_insider();

CREATE OR REPLACE VIEW mcp_bookable_resources WITH (security_barrier = true) AS
SELECT id AS resource_id, name, kind FROM bookable_resources
WHERE archived_at IS NULL AND app_is_insider();

CREATE OR REPLACE VIEW mcp_appointments WITH (security_barrier = true) AS
SELECT a.id AS appointment_id, a.appointment_type_id, at.name AS appointment_type, a.title,
       a.description, a.organization_id, o.name AS organization_name, a.contact_id, a.deal_id,
       a.project_id, a.task_id, a.location_text, a.meeting_url, a.starts_at, a.ends_at,
       a.all_day, a.timezone, a.status, a.recurrence_rule, a.recurrence_parent_id,
       a.completed_at, a.cancelled_reason, a.owner_member_id, a.department_id,
       (SELECT array_agg(aa.member_id) FROM appointment_assignees aa
         WHERE aa.appointment_id = a.id AND aa.response <> 'declined') AS assignee_ids,
       EXISTS (SELECT 1 FROM invoice_lines il WHERE il.appointment_id = a.id) AS is_invoiced,
       a.created_at, a.updated_at
FROM appointments a
LEFT JOIN appointment_types at ON at.id = a.appointment_type_id
LEFT JOIN organizations o ON o.id = a.organization_id
WHERE app_is_insider()
  AND (EXISTS (SELECT 1 FROM appointment_assignees aa
                WHERE aa.appointment_id = a.id AND aa.member_id = app_current_member_id())
       OR app_can_see('scheduling', a.owner_member_id, a.department_id, 'appointment', a.id, NULL));

CREATE OR REPLACE VIEW mcp_appointment_assignees WITH (security_barrier = true) AS
SELECT aa.appointment_id, aa.member_id, m.display_name, m.member_kind, aa.role, aa.response
FROM appointment_assignees aa
JOIN mcp_appointments a ON a.appointment_id = aa.appointment_id
JOIN members m ON m.id = aa.member_id;

CREATE OR REPLACE VIEW mcp_appointment_resources WITH (security_barrier = true) AS
SELECT ar.appointment_id, ar.resource_id, r.name AS resource_name, r.kind
FROM appointment_resources ar
JOIN mcp_appointments a ON a.appointment_id = ar.appointment_id
JOIN bookable_resources r ON r.id = ar.resource_id;

-- Busy time for free/busy questions (K3, K5) without exposing appointment details.
CREATE OR REPLACE VIEW mcp_busy_blocks WITH (security_barrier = true) AS
SELECT aa.member_id, NULL::bigint AS resource_id, a.starts_at, a.ends_at, 'appointment'::text AS source
FROM appointment_assignees aa JOIN appointments a ON a.id = aa.appointment_id
WHERE a.status NOT IN ('cancelled') AND aa.response <> 'declined' AND app_is_insider()
UNION ALL
SELECT NULL, ar.resource_id, a.starts_at, a.ends_at, 'appointment'
FROM appointment_resources ar JOIN appointments a ON a.id = ar.appointment_id
WHERE a.status NOT IN ('cancelled') AND app_is_insider()
UNION ALL
SELECT b.member_id, b.resource_id, b.starts_at, b.ends_at, b.kind
FROM availability_blocks b
WHERE app_is_insider();

-- ==========================================================================
-- TICKETS
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_tickets WITH (security_barrier = true) AS
SELECT t.id AS ticket_id, t.number, t.subject, t.description, t.origin, t.requester_contact_id,
       t.requester_member_id, t.organization_id, o.name AS organization_name, t.project_id,
       t.department_id, t.category_id, tc.name AS category_name, t.assignee_member_id,
       am.display_name AS assignee_name, am.member_kind AS assignee_kind, t.priority, t.status,
       t.first_response_due_at, t.resolution_due_at, t.first_responded_at, t.resolved_at,
       t.resolved_by_member_id, t.closed_at, t.reopened_count, t.resolution_summary,
       t.satisfaction_score, t.search_tsv, t.created_at, t.updated_at
FROM tickets t
LEFT JOIN organizations o ON o.id = t.organization_id
LEFT JOIN ticket_categories tc ON tc.id = t.category_id
LEFT JOIN members am ON am.id = t.assignee_member_id
WHERE t.requester_member_id = app_current_member_id()
   OR app_can_see('tickets', t.assignee_member_id, t.department_id, 'ticket', t.id, t.organization_id);

CREATE OR REPLACE VIEW mcp_ticket_messages WITH (security_barrier = true) AS
SELECT tm.id AS message_id, tm.ticket_id, tm.kind, tm.author_member_id,
       m.display_name AS author_name, tm.author_contact_id, tm.body, tm.search_tsv, tm.created_at
FROM ticket_messages tm
JOIN mcp_tickets t ON t.ticket_id = tm.ticket_id
LEFT JOIN members m ON m.id = tm.author_member_id
WHERE tm.kind = 'reply' OR app_is_insider();                 -- External never sees internal notes

-- ==========================================================================
-- DOCUMENTS
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_folders WITH (security_barrier = true) AS
SELECT f.id AS folder_id, f.parent_id, f.name, f.department_id, f.owner_member_id
FROM folders f
WHERE f.archived_at IS NULL
  AND app_can_see('documents', f.owner_member_id, f.department_id, 'folder', f.id, NULL);

CREATE OR REPLACE VIEW mcp_documents WITH (security_barrier = true) AS
SELECT d.id AS document_id, d.folder_id, d.title, d.kind, d.department_id, d.owner_member_id,
       om.display_name AS owner_name, d.current_version_id,
       (SELECT v.version_no FROM document_versions v WHERE v.id = d.current_version_id) AS version_no,
       d.mime_type, d.size_bytes, d.body_markdown, d.origin, d.origin_location_id,
       d.search_tsv, d.archived_at, d.created_by, d.created_at, d.updated_at
FROM documents d
LEFT JOIN members om ON om.id = d.owner_member_id
WHERE d.deleted_at IS NULL
  AND app_can_see('documents', d.owner_member_id, d.department_id, 'document', d.id, NULL);

CREATE OR REPLACE VIEW mcp_document_versions WITH (security_barrier = true) AS
SELECT v.id AS version_id, v.document_id, v.version_no, v.size_bytes, v.mime_type,
       v.body_markdown, v.change_note, v.created_by, v.created_at
FROM document_versions v
JOIN mcp_documents d ON d.document_id = v.document_id;

CREATE OR REPLACE VIEW mcp_document_links WITH (security_barrier = true) AS
SELECT l.document_id, d.title, d.kind, l.entity_type, l.entity_id, l.created_at
FROM document_links l
JOIN mcp_documents d ON d.document_id = l.document_id;

-- ==========================================================================
-- TIME
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_time_entries WITH (security_barrier = true) AS
SELECT te.id AS time_entry_id, te.member_id, m.display_name AS member_name, te.entry_date,
       te.started_at, te.ended_at, te.minutes, round(te.minutes / 60.0, 2) AS hours,
       te.project_id, te.task_id, te.organization_id, te.ticket_id, te.appointment_id,
       te.campaign_id, te.department_id, te.description, te.billable,
       CASE WHEN app_can_admin_member(te.member_id) OR app_is_external()
            THEN te.hourly_rate END AS hourly_rate,
       te.currency, te.status, te.approved_by, te.approved_at, te.locked_at,
       te.invoice_line_id, te.created_at, te.updated_at
FROM time_entries te
JOIN members m ON m.id = te.member_id
WHERE app_can_see('time', te.member_id, te.department_id, 'time_entry', te.id, NULL);

-- ==========================================================================
-- SALES & INVOICING
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_tax_rates WITH (security_barrier = true) AS
SELECT id AS tax_rate_id, name, rate, is_default FROM tax_rates
WHERE archived_at IS NULL AND app_has_module('sales');

CREATE OR REPLACE VIEW mcp_catalog_items WITH (security_barrier = true) AS
SELECT id AS catalog_item_id, name, description, unit, unit_price, currency, tax_rate_id
FROM catalog_items
WHERE archived_at IS NULL AND app_has_module('sales');

CREATE OR REPLACE VIEW mcp_quotes WITH (security_barrier = true) AS
SELECT q.id AS quote_id, q.number, q.organization_id, o.name AS organization_name, q.contact_id,
       q.deal_id, q.project_id, q.status, q.issue_date, q.valid_until, q.currency, q.subtotal,
       q.tax_total, q.total, q.notes, q.terms, q.sent_at, q.accepted_at, q.declined_at,
       q.converted_invoice_id, q.owner_member_id, q.department_id, q.created_by, q.created_at,
       q.updated_at
FROM quotes q
LEFT JOIN organizations o ON o.id = q.organization_id
WHERE (q.status <> 'draft' OR app_is_insider())
  AND app_can_see('sales', q.owner_member_id, q.department_id, 'quote', q.id, q.organization_id);

CREATE OR REPLACE VIEW mcp_quote_lines WITH (security_barrier = true) AS
SELECT ql.id AS quote_line_id, ql.quote_id, ql.sort_order, ql.catalog_item_id, ql.description,
       ql.quantity, ql.unit_price, ql.tax_rate_id, ql.line_subtotal, ql.line_tax, ql.line_total
FROM quote_lines ql
JOIN mcp_quotes q ON q.quote_id = ql.quote_id;

CREATE OR REPLACE VIEW mcp_invoices WITH (security_barrier = true) AS
SELECT i.id AS invoice_id, i.number, i.organization_id, o.name AS organization_name, i.contact_id,
       i.deal_id, i.project_id, i.quote_id, i.status, i.issue_date, i.due_date, i.currency,
       i.subtotal, i.tax_total, i.total, i.amount_paid, i.amount_credited, i.balance_due,
       CASE WHEN i.status IN ('sent', 'viewed', 'partially_paid') AND i.due_date < current_date
            THEN current_date - i.due_date ELSE 0 END AS days_overdue,
       i.online_payment_enabled, i.sent_at, i.first_viewed_at, i.paid_at, i.voided_at,
       i.void_reason, i.last_reminder_at, i.reminder_count, i.notes, i.terms,
       i.owner_member_id, i.department_id, i.created_by, cm.member_kind AS created_by_kind,
       i.created_at, i.updated_at
FROM invoices i
LEFT JOIN organizations o ON o.id = i.organization_id
LEFT JOIN members cm ON cm.id = i.created_by
WHERE (i.status <> 'draft' OR app_is_insider())
  AND app_can_see('sales', i.owner_member_id, i.department_id, 'invoice', i.id, i.organization_id);

CREATE OR REPLACE VIEW mcp_invoice_lines WITH (security_barrier = true) AS
SELECT il.id AS invoice_line_id, il.invoice_id, il.sort_order, il.catalog_item_id,
       il.appointment_id, il.description, il.quantity, il.unit_price, il.tax_rate_id,
       tr.name AS tax_rate_name, tr.rate AS tax_rate, il.line_subtotal, il.line_tax, il.line_total
FROM invoice_lines il
JOIN mcp_invoices i ON i.invoice_id = il.invoice_id
LEFT JOIN tax_rates tr ON tr.id = il.tax_rate_id;

CREATE OR REPLACE VIEW mcp_payments WITH (security_barrier = true) AS
SELECT p.id AS payment_id, p.organization_id, o.name AS organization_name, p.contact_id,
       p.received_on, p.amount, p.currency, p.method, p.source, p.provider_payment_id,
       p.reference, p.notes, p.recorded_by,
       COALESCE((SELECT sum(pa.amount) FROM payment_allocations pa WHERE pa.payment_id = p.id), 0)
           AS amount_allocated,
       p.created_at
FROM payments p
LEFT JOIN organizations o ON o.id = p.organization_id
WHERE app_can_see('sales', NULL, NULL, 'payment', p.id, p.organization_id);

CREATE OR REPLACE VIEW mcp_payment_allocations WITH (security_barrier = true) AS
SELECT pa.payment_id, pa.invoice_id, i.number AS invoice_number, pa.amount
FROM payment_allocations pa
JOIN mcp_payments p ON p.payment_id = pa.payment_id
JOIN invoices i ON i.id = pa.invoice_id;

CREATE OR REPLACE VIEW mcp_credit_notes WITH (security_barrier = true) AS
SELECT cn.id AS credit_note_id, cn.number, cn.invoice_id, cn.organization_id, cn.issue_date,
       cn.amount, cn.currency, cn.reason, cn.status, cn.created_by, cn.created_at
FROM credit_notes cn
WHERE (cn.status <> 'draft' OR app_is_insider())
  AND app_can_see('sales', NULL, NULL, 'credit_note', cn.id, cn.organization_id);

-- ==========================================================================
-- ONLINE PAYMENTS (no secret ids, no raw webhook payloads)
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_payment_providers WITH (security_barrier = true) AS
SELECT id AS payment_provider_id, provider, display_name, mode, status, is_default,
       connected_at, last_event_at, last_error
FROM payment_providers
WHERE app_is_super_admin() OR app_has_module('sales');

CREATE OR REPLACE VIEW mcp_payment_links WITH (security_barrier = true) AS
SELECT pl.id AS payment_link_id, pl.invoice_id, i.number AS invoice_number, pl.provider_id,
       pl.url, pl.amount, pl.currency, pl.status, pl.expires_at, pl.first_opened_at,
       pl.completed_at, pl.created_by, pl.created_at
FROM payment_links pl
JOIN mcp_invoices i ON i.invoice_id = pl.invoice_id;

CREATE OR REPLACE VIEW mcp_provider_payments WITH (security_barrier = true) AS
SELECT pp.id AS provider_payment_id, pp.provider_id, pp.payment_link_id, pp.invoice_id,
       i.number AS invoice_number, pp.amount, pp.fee_amount, pp.net_amount, pp.currency,
       pp.status, pp.failure_code, pp.failure_message, pp.paid_at, pp.payout_id,
       EXISTS (SELECT 1 FROM payments p WHERE p.provider_payment_id = pp.id) AS is_recorded,
       pp.created_at
FROM provider_payments pp
LEFT JOIN invoices i ON i.id = pp.invoice_id
WHERE app_can_see('sales', NULL, NULL, 'provider_payment', pp.id, i.organization_id);

CREATE OR REPLACE VIEW mcp_payouts WITH (security_barrier = true) AS
SELECT id AS payout_id, provider_id, amount, fee_total, currency, status, arrival_date, created_at
FROM payouts
WHERE app_has_module('sales');

CREATE OR REPLACE VIEW mcp_refunds WITH (security_barrier = true) AS
SELECT r.id AS refund_id, r.provider_payment_id, r.payment_id, r.invoice_id, r.amount, r.currency,
       r.reason, r.status, r.requested_by, rm.display_name AS requested_by_name,
       rm.member_kind AS requested_by_kind, r.approval_request_id, r.processed_at, r.created_at
FROM refunds r
LEFT JOIN members rm ON rm.id = r.requested_by
WHERE app_has_module('sales');

CREATE OR REPLACE VIEW mcp_disputes WITH (security_barrier = true) AS
SELECT d.id AS dispute_id, d.provider_payment_id, pp.invoice_id, d.amount, d.currency, d.reason,
       d.status, d.evidence_due_at, d.opened_at, d.closed_at
FROM disputes d
JOIN provider_payments pp ON pp.id = d.provider_payment_id
WHERE app_has_module('sales');

-- ==========================================================================
-- EXPENSES
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_expense_categories WITH (security_barrier = true) AS
SELECT id AS category_id, name::text AS name, accounting_code, is_billable_default
FROM expense_categories
WHERE archived_at IS NULL AND app_current_member_id() IS NOT NULL;

CREATE OR REPLACE VIEW mcp_expenses WITH (security_barrier = true) AS
SELECT e.id AS expense_id, e.number, e.vendor_organization_id, vo.name AS vendor_name,
       e.vendor_contact_id, e.category_id, ec.name::text AS category_name, e.description,
       e.expense_date, e.due_date, e.amount, e.tax_amount, e.currency, e.payment_status, e.paid_on,
       e.payment_method, e.status, e.submitted_by, sm.display_name AS submitted_by_name,
       sm.member_kind AS submitted_by_kind, e.approved_by, e.approved_at, e.approval_request_id,
       e.project_id, e.task_id, e.organization_id, e.campaign_id, e.billable, e.invoice_line_id,
       e.receipt_document_id IS NOT NULL AS has_receipt, e.receipt_document_id,
       e.recurring_expense_id, e.department_id, e.search_tsv, e.created_at, e.updated_at
FROM expenses e
LEFT JOIN organizations vo ON vo.id = e.vendor_organization_id
LEFT JOIN expense_categories ec ON ec.id = e.category_id
LEFT JOIN members sm ON sm.id = e.submitted_by
WHERE e.submitted_by = app_current_member_id()
   OR app_can_see('expenses', NULL, e.department_id, 'expense', e.id, NULL);

CREATE OR REPLACE VIEW mcp_recurring_expenses WITH (security_barrier = true) AS
SELECT r.id AS recurring_expense_id, r.vendor_organization_id, vo.name AS vendor_name,
       r.category_id, r.description, r.amount, r.currency, r.frequency, r.next_due_on, r.ends_on,
       r.active, r.department_id
FROM recurring_expenses r
LEFT JOIN organizations vo ON vo.id = r.vendor_organization_id
WHERE app_can_see('expenses', NULL, r.department_id, 'recurring_expense', r.id, NULL);

CREATE OR REPLACE VIEW mcp_accountant_exports WITH (security_barrier = true) AS
SELECT a.id AS export_id, a.period_start, a.period_end, a.format, a.includes, a.row_counts,
       a.document_id, a.generated_by, a.generated_at, a.last_downloaded_at
FROM accountant_exports a
WHERE app_has_module('expenses');

-- ==========================================================================
-- CONTENT & SOCIAL (no channel credentials)
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_channels WITH (security_barrier = true) AS
SELECT id AS channel_id, platform, name, handle, publish_mode, connection_status, connected_at,
       last_checked_at, last_error, department_id, archived_at
FROM channels
WHERE app_has_module('content') AND app_is_insider();

CREATE OR REPLACE VIEW mcp_campaigns WITH (security_barrier = true) AS
SELECT c.id AS campaign_id, c.name, c.goal, c.status, c.starts_on, c.ends_on, c.budget_amount,
       c.currency, c.owner_member_id, c.department_id, c.created_at, c.updated_at
FROM campaigns c
WHERE app_is_insider()
  AND app_can_see('content', c.owner_member_id, c.department_id, 'campaign', c.id, NULL);

CREATE OR REPLACE VIEW mcp_content_items WITH (security_barrier = true) AS
SELECT ci.id AS content_item_id, ci.title, ci.brief, ci.campaign_id, c.name AS campaign_name,
       ci.author_member_id, am.display_name AS author_name, am.member_kind AS author_kind,
       ci.owner_member_id, ci.reviewer_member_id, ci.department_id, ci.status,
       ci.approval_request_id, ci.approved_by, ci.approved_at, ci.search_tsv, ci.created_at,
       ci.updated_at
FROM content_items ci
LEFT JOIN campaigns c ON c.id = ci.campaign_id
LEFT JOIN members am ON am.id = ci.author_member_id
WHERE app_is_insider()
  AND (ci.author_member_id = app_current_member_id()
       OR ci.reviewer_member_id = app_current_member_id()
       OR app_can_see('content', ci.owner_member_id, ci.department_id, 'content_item', ci.id, NULL));

CREATE OR REPLACE VIEW mcp_content_variants WITH (security_barrier = true) AS
SELECT cv.id AS content_variant_id, cv.content_item_id, ci.title, ci.campaign_id, cv.channel_id,
       ch.platform, ch.name AS channel_name, cv.body, cv.status, cv.scheduled_at, cv.published_at,
       cv.published_by, cv.platform_post_id, cv.published_url, cv.publish_error, cv.search_tsv,
       cv.created_at, cv.updated_at
FROM content_variants cv
JOIN mcp_content_items ci ON ci.content_item_id = cv.content_item_id
JOIN channels ch ON ch.id = cv.channel_id;

CREATE OR REPLACE VIEW mcp_content_metrics WITH (security_barrier = true) AS
SELECT cm.id AS metric_id, cm.content_variant_id, cv.content_item_id, cv.channel_id,
       cm.captured_at, cm.source, cm.impressions, cm.reach, cm.engagements, cm.clicks, cm.likes,
       cm.comments, cm.shares, cm.video_views
FROM content_metrics cm
JOIN mcp_content_variants cv ON cv.content_variant_id = cm.content_variant_id;

-- ==========================================================================
-- NOTIFICATIONS
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_my_notifications WITH (security_barrier = true) AS
SELECT n.id AS notification_id, n.kind, n.priority, n.entity_type, n.entity_id, n.title, n.body,
       n.action_url, n.actor_member_id, n.email_sent_at, n.read_at, n.created_at
FROM notifications n
WHERE n.member_id = app_current_member_id();

CREATE OR REPLACE VIEW mcp_notification_preferences WITH (security_barrier = true) AS
SELECT member_id, kind, channel FROM notification_preferences
WHERE app_can_admin_member(member_id);

CREATE OR REPLACE VIEW mcp_email_messages WITH (security_barrier = true) AS
SELECT em.id AS email_message_id, em.member_id, em.to_email::text AS to_email, em.template,
       em.entity_type, em.entity_id, em.subject, em.status, em.error, em.sent_at, em.delivered_at,
       em.opened_at, em.bounced_at, em.created_at
FROM email_messages em
WHERE em.member_id = app_current_member_id() OR app_is_super_admin();

CREATE OR REPLACE VIEW mcp_email_suppressions WITH (security_barrier = true) AS
SELECT email::text AS email, reason, source, suppressed_at, lifted_at
FROM email_suppressions
WHERE app_is_super_admin() OR app_has_module('inbox');

CREATE OR REPLACE VIEW mcp_my_digests WITH (security_barrier = true) AS
SELECT id AS digest_id, period_start, period_end, content, sent_at
FROM digest_sends
WHERE member_id = app_current_member_id();

-- ==========================================================================
-- AGENT HR
-- ==========================================================================

-- Who may see an agent's employment details: HR module holders, the agent's manager,
-- and the agent itself (H3, H9, H10).
CREATE OR REPLACE FUNCTION app_can_see_agent(p_agent_member_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_is_insider()
       AND (app_has_module('hr')
            OR p_agent_member_id = app_current_member_id()
            OR EXISTS (SELECT 1 FROM agent_profiles ap
                        WHERE ap.member_id = p_agent_member_id
                          AND ap.manager_member_id = app_current_member_id()));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_agent(bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_model_registry WITH (security_barrier = true) AS
SELECT id AS model_id, model_key, display_name, provider, provider_model_id, harness,
       context_window_tokens, price_input_per_mtok, price_output_per_mtok,
       price_cache_read_per_mtok, price_cache_write_per_mtok, currency, status
FROM model_registry
WHERE app_is_insider();

-- Everyone inside the business can see who the agents are and who they report to (H2);
-- job descriptions, grants and budgets are behind app_can_see_agent.
CREATE OR REPLACE VIEW mcp_agents WITH (security_barrier = true) AS
SELECT ap.member_id AS agent_member_id, m.display_name, m.job_title, ap.status,
       ap.is_office_manager, ap.manager_member_id, mm.display_name AS manager_name,
       ap.home_location_id, mr.model_key, mr.harness,
       CASE WHEN app_can_see_agent(ap.member_id) THEN ap.current_config_version_id END AS current_config_version_id,
       CASE WHEN app_can_see_agent(ap.member_id) THEN ap.monthly_budget_amount END AS monthly_budget_amount,
       ap.budget_currency, ap.hired_at, ap.suspended_at, ap.offboarded_at
FROM agent_profiles ap
JOIN members m ON m.id = ap.member_id
JOIN members mm ON mm.id = ap.manager_member_id
JOIN model_registry mr ON mr.id = ap.model_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_agent_config_versions WITH (security_barrier = true) AS
SELECT v.id AS config_version_id, v.agent_member_id, v.version_no, v.job_description,
       v.model_id, v.harness_config, v.tool_grants, v.schedule, v.monthly_budget_amount,
       v.change_note, v.created_by, v.created_at, v.gating_eval_run_id, v.activated_at,
       v.activated_by
FROM agent_config_versions v
WHERE app_can_see_agent(v.agent_member_id);

CREATE OR REPLACE VIEW mcp_agent_tool_grants WITH (security_barrier = true) AS
SELECT g.agent_member_id, g.server, g.tool_name, g.constraints, g.granted_by, g.created_at
FROM agent_tool_grants g
WHERE g.revoked_at IS NULL AND app_can_see_agent(g.agent_member_id);

CREATE OR REPLACE VIEW mcp_agent_duties WITH (security_barrier = true) AS
SELECT d.id AS duty_id, d.agent_member_id, d.name, d.instructions, d.schedule_cron, d.timezone,
       d.location_id, d.active, d.last_run_at, d.next_run_at
FROM agent_duties d
WHERE app_can_see_agent(d.agent_member_id);

CREATE OR REPLACE VIEW mcp_hr_events WITH (security_barrier = true) AS
SELECT e.id AS hr_event_id, e.member_id, m.display_name, m.member_kind, e.event_type,
       e.config_version_id, e.note, e.actor_member_id, e.occurred_at
FROM hr_events e
JOIN members m ON m.id = e.member_id
WHERE app_has_module('hr') OR e.member_id = app_current_member_id()
   OR (m.member_kind = 'agent' AND app_can_see_agent(e.member_id));

CREATE OR REPLACE VIEW mcp_performance_reviews WITH (security_barrier = true) AS
SELECT r.id AS review_id, r.member_id, m.display_name, m.member_kind, r.reviewer_member_id,
       r.period_start, r.period_end, r.rating, r.summary, r.metrics, r.created_at
FROM performance_reviews r
JOIN members m ON m.id = r.member_id
WHERE app_has_module('hr') OR r.member_id = app_current_member_id()
   OR r.reviewer_member_id = app_current_member_id()
   OR (m.member_kind = 'agent' AND app_can_see_agent(r.member_id));

CREATE OR REPLACE VIEW mcp_agent_escalations WITH (security_barrier = true) AS
SELECT e.id AS escalation_id, e.agent_member_id, am.display_name AS agent_name, e.to_member_id,
       e.reason_kind, e.summary, e.entity_type, e.entity_id, e.ticket_id, e.approval_request_id,
       e.resolved_at, e.resolved_by, e.created_at
FROM agent_escalations e
JOIN members am ON am.id = e.agent_member_id
WHERE e.to_member_id = app_current_member_id() OR app_can_see_agent(e.agent_member_id);

-- ==========================================================================
-- LOCATIONS & TASK QUEUE
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_locations WITH (security_barrier = true) AS
SELECT l.id AS location_id, l.name, l.kind, l.parent_location_id,
       pl.name AS parent_location_name, l.description,
       l.owner_member_id, om.display_name AS owner_name,
       l.office_manager_member_id, l.status, l.presence, l.last_seen_at,
       l.platform, l.external_ref, l.hostname, host(l.ip_address) AS ip_address,
       l.cpu_cores, l.memory_mb, l.storage_gb, l.is_always_on,
       l.app_version, l.os_platform, l.mcp_surface_version, l.enrolled_at, l.retired_at,
       (SELECT count(*) FROM locations c WHERE c.parent_location_id = l.id
          AND c.status = 'active') AS child_count,
       (SELECT count(*) FROM location_residents r WHERE r.location_id = l.id
          AND r.removed_at IS NULL) AS resident_count,
       (SELECT count(*) FROM departments d WHERE d.home_location_id = l.id
          AND d.archived_at IS NULL) AS department_count
FROM locations l
LEFT JOIN members om ON om.id = l.owner_member_id
LEFT JOIN locations pl ON pl.id = l.parent_location_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_location_residents WITH (security_barrier = true) AS
SELECT r.location_id, l.name AS location_name, l.kind AS location_kind,
       r.member_id, m.display_name AS member_name, m.member_kind,
       coalesce(ap.is_office_manager, false) AS is_office_manager,
       r.is_primary, r.added_at
FROM location_residents r
JOIN locations l ON l.id = r.location_id
JOIN members m ON m.id = r.member_id
LEFT JOIN agent_profiles ap ON ap.member_id = r.member_id
WHERE r.removed_at IS NULL AND app_is_insider();

CREATE OR REPLACE VIEW mcp_consent_grants WITH (security_barrier = true) AS
SELECT g.id AS consent_grant_id, g.desk_location_id, l.name AS desk_name, g.grantee_member_id,
       g.grantee_location_id, g.task_type, g.scope, g.granted_by, g.expires_at, g.used_at,
       g.created_at
FROM consent_grants g
JOIN locations l ON l.id = g.desk_location_id
WHERE g.revoked_at IS NULL
  AND (l.owner_member_id = app_current_member_id()
       OR g.grantee_member_id = app_current_member_id()
       OR app_is_super_admin());

CREATE OR REPLACE VIEW mcp_location_tasks WITH (security_barrier = true) AS
SELECT t.id AS location_task_id, t.requester_member_id, rm.display_name AS requester_name,
       t.requester_location_id, t.target_location_id, tl.name AS target_location_name,
       t.assigned_agent_member_id, t.task_type, t.title, t.instructions, t.priority, t.status,
       t.consent_grant_id, t.result_summary, t.refused_reason, t.failure_reason, t.entity_type,
       t.entity_id, t.agent_run_id, t.queued_at, t.delivered_at, t.started_at, t.finished_at,
       t.expires_at
FROM location_tasks t
JOIN members rm ON rm.id = t.requester_member_id
JOIN locations tl ON tl.id = t.target_location_id
WHERE app_is_insider()
  AND (t.requester_member_id = app_current_member_id()
       OR tl.owner_member_id = app_current_member_id()
       OR t.assigned_agent_member_id = app_current_member_id()
       OR tl.office_manager_member_id = app_current_member_id()
       OR app_has_module('locations'));

-- ==========================================================================
-- APPROVALS
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_approval_policies WITH (security_barrier = true) AS
SELECT id AS policy_id, name, category, action_pattern, applies_to, agent_member_id, department_id,
       amount_threshold, currency, approver_member_id, expires_after_hours, active, updated_at
FROM approval_policies
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_approval_requests WITH (security_barrier = true) AS
SELECT r.id AS approval_request_id, r.policy_id, r.requested_by_member_id,
       rm.display_name AS requested_by_name, rm.member_kind AS requested_by_kind, r.agent_run_id,
       r.action_key, r.parameters, r.summary, r.amount, r.currency, r.entity_type, r.entity_id,
       r.approver_member_id, am.display_name AS approver_name, r.status, r.decided_by,
       r.decided_at, r.decision_note, r.expires_at, r.executed_at, r.executed_activity_id,
       r.execution_error, r.created_at
FROM approval_requests r
JOIN members rm ON rm.id = r.requested_by_member_id
JOIN members am ON am.id = r.approver_member_id
WHERE app_is_insider()
  AND (r.requested_by_member_id = app_current_member_id()
       OR r.approver_member_id = app_current_member_id()
       OR r.decided_by = app_current_member_id()
       OR app_has_module('approvals')
       OR app_can_see_agent(r.requested_by_member_id));

-- ==========================================================================
-- AGENT RUNS & PROMPT LEDGER
-- ==========================================================================

CREATE OR REPLACE FUNCTION app_can_see_run(p_agent_member_id bigint, p_acting_member_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_is_insider()
       AND (app_has_module('ledger')
            OR p_acting_member_id = app_current_member_id()
            OR (p_agent_member_id IS NOT NULL AND app_can_see_agent(p_agent_member_id)));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_run(bigint, bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id,
       r.location_id, r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id,
       r.harness, r.sdk_version, r.request_id, r.project_id, r.task_id, r.campaign_id, r.status,
       r.error, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
       r.cost, r.currency, r.started_at, r.finished_at
FROM agent_runs r
LEFT JOIN members am ON am.id = r.agent_member_id
WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);

CREATE OR REPLACE VIEW mcp_prompt_ledger WITH (security_barrier = true) AS
SELECT pl.id AS ledger_id, pl.occurred_at, pl.agent_run_id, pl.agent_member_id, pl.acting_member_id,
       pl.location_id, pl.harness, pl.sdk_version, pl.provider, pl.model_id, pl.provider_model_id,
       pl.request_id, pl.call_kind, pl.status, pl.error_code, pl.error_message, pl.input_tokens,
       pl.output_tokens, pl.cache_read_tokens, pl.cache_write_tokens, pl.latency_ms, pl.cost,
       pl.currency, pl.project_id, pl.task_id, pl.campaign_id, pl.payload_archived_at
FROM prompt_ledger pl
WHERE app_can_see_run(pl.agent_member_id, pl.acting_member_id);

-- Full payloads: humans with ledger access or the acting member; an agent sees only its
-- own calls — never another agent's context (questions doc, "won't answer").
CREATE OR REPLACE VIEW mcp_prompt_payloads WITH (security_barrier = true) AS
SELECT pp.ledger_id, pl.agent_member_id, pp.context, pp.response, pp.byte_size, pp.archived_at
FROM prompt_payloads pp
JOIN prompt_ledger pl ON pl.id = pp.ledger_id
WHERE app_is_insider()
  AND (pl.agent_member_id = app_current_member_id()
       OR (app_member_kind() = 'human'
           AND (app_has_module('ledger') OR pl.acting_member_id = app_current_member_id()
                OR (pl.agent_member_id IS NOT NULL AND app_can_see_agent(pl.agent_member_id)))));

-- ==========================================================================
-- EVALS
-- ==========================================================================

CREATE OR REPLACE FUNCTION app_can_see_evals(p_agent_member_id bigint) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT app_is_insider()
       AND (app_has_module('evals')
            OR (p_agent_member_id IS NOT NULL AND app_can_see_agent(p_agent_member_id)));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_evals(bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_eval_sets WITH (security_barrier = true) AS
SELECT id AS eval_set_id, name, description, agent_member_id, role_key, department_id,
       pass_threshold, status, created_at, updated_at
FROM eval_sets
WHERE app_can_see_evals(agent_member_id);

-- Agents never read their own eval cases (that would leak the answers into their context).
CREATE OR REPLACE VIEW mcp_eval_cases WITH (security_barrier = true) AS
SELECT c.id AS eval_case_id, c.eval_set_id, c.title, c.input, c.expected, c.rubric, c.grader,
       c.weight, c.origin, c.source_ledger_id, c.source_run_id, c.promoted_by, c.active, c.created_at
FROM eval_cases c
JOIN eval_sets s ON s.id = c.eval_set_id
WHERE app_member_kind() = 'human' AND app_can_see_evals(s.agent_member_id);

CREATE OR REPLACE VIEW mcp_eval_runs WITH (security_barrier = true) AS
SELECT r.id AS eval_run_id, r.eval_set_id, s.name AS eval_set_name, r.agent_member_id,
       r.config_version_id, r.model_id, r.harness, r.trigger, r.status, r.pass_threshold, r.score,
       r.cases_total, r.cases_passed, r.baseline_run_id, r.cost, r.currency, r.started_by,
       r.started_at, r.finished_at, r.created_at
FROM eval_runs r
JOIN eval_sets s ON s.id = r.eval_set_id
WHERE app_can_see_evals(COALESCE(r.agent_member_id, s.agent_member_id));

CREATE OR REPLACE VIEW mcp_eval_results WITH (security_barrier = true) AS
SELECT er.id AS eval_result_id, er.eval_run_id, er.eval_case_id, c.title AS case_title,
       er.agent_run_id, er.passed, er.score, er.grader_notes, er.created_at
FROM eval_results er
JOIN mcp_eval_runs r ON r.eval_run_id = er.eval_run_id
JOIN eval_cases c ON c.id = er.eval_case_id
WHERE app_member_kind() = 'human';

CREATE OR REPLACE VIEW mcp_trace_grades WITH (security_barrier = true) AS
SELECT g.id AS trace_grade_id, g.agent_run_id, r.agent_member_id, g.eval_set_id, g.score, g.passed,
       g.grader_notes, g.promoted_case_id, g.sampled_at, g.graded_at
FROM trace_grades g
JOIN agent_runs r ON r.id = g.agent_run_id
WHERE app_member_kind() = 'human' AND app_can_see_evals(r.agent_member_id);

-- ==========================================================================
-- OPS (owner only)
-- ==========================================================================

CREATE OR REPLACE VIEW mcp_backup_runs WITH (security_barrier = true) AS
SELECT b.id AS backup_run_id, b.kind, b.scope, b.status, b.size_bytes, b.error, b.started_at,
       b.finished_at,
       (SELECT rr.status FROM restore_rehearsals rr WHERE rr.backup_run_id = b.id
         ORDER BY rr.performed_at DESC LIMIT 1) AS last_rehearsal_status
FROM backup_runs b
WHERE app_is_super_admin();

CREATE OR REPLACE VIEW mcp_restore_rehearsals WITH (security_barrier = true) AS
SELECT id AS rehearsal_id, backup_run_id, status, checks, notes, performed_by, performed_at
FROM restore_rehearsals
WHERE app_is_super_admin();

CREATE OR REPLACE VIEW mcp_data_exports WITH (security_barrier = true) AS
SELECT id AS export_id, requested_by, includes, status, size_bytes, error, requested_at,
       completed_at, downloaded_at, expires_at
FROM data_exports
WHERE app_is_super_admin();

-- ==========================================================================
-- GENERIC ENTITY VISIBILITY (tags, comments, links, activity history)
-- ==========================================================================
-- Dispatches to the entity's own mcp_* view, so every polymorphic reference (taggings,
-- record_comments, document_links, activity_log) obeys exactly the same rule as the record.
CREATE OR REPLACE FUNCTION app_can_see_entity(p_entity_type text, p_entity_id bigint) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF app_current_member_id() IS NULL OR p_entity_type IS NULL OR p_entity_id IS NULL THEN
        RETURN false;
    END IF;
    RETURN CASE p_entity_type
        WHEN 'organization'     THEN EXISTS (SELECT 1 FROM mcp_organizations    WHERE organization_id = p_entity_id)
        WHEN 'contact'          THEN EXISTS (SELECT 1 FROM mcp_contacts         WHERE contact_id = p_entity_id)
        WHEN 'deal'             THEN EXISTS (SELECT 1 FROM mcp_deals            WHERE deal_id = p_entity_id)
        WHEN 'interaction'      THEN EXISTS (SELECT 1 FROM mcp_interactions     WHERE interaction_id = p_entity_id)
        WHEN 'project'          THEN EXISTS (SELECT 1 FROM mcp_projects         WHERE project_id = p_entity_id)
        WHEN 'task'             THEN EXISTS (SELECT 1 FROM mcp_tasks            WHERE task_id = p_entity_id)
        WHEN 'appointment'      THEN EXISTS (SELECT 1 FROM mcp_appointments     WHERE appointment_id = p_entity_id)
        WHEN 'ticket'           THEN EXISTS (SELECT 1 FROM mcp_tickets          WHERE ticket_id = p_entity_id)
        WHEN 'document'         THEN EXISTS (SELECT 1 FROM mcp_documents        WHERE document_id = p_entity_id)
        WHEN 'time_entry'       THEN EXISTS (SELECT 1 FROM mcp_time_entries     WHERE time_entry_id = p_entity_id)
        WHEN 'quote'            THEN EXISTS (SELECT 1 FROM mcp_quotes           WHERE quote_id = p_entity_id)
        WHEN 'invoice'          THEN EXISTS (SELECT 1 FROM mcp_invoices         WHERE invoice_id = p_entity_id)
        WHEN 'payment'          THEN EXISTS (SELECT 1 FROM mcp_payments         WHERE payment_id = p_entity_id)
        WHEN 'credit_note'      THEN EXISTS (SELECT 1 FROM mcp_credit_notes     WHERE credit_note_id = p_entity_id)
        WHEN 'refund'           THEN EXISTS (SELECT 1 FROM mcp_refunds          WHERE refund_id = p_entity_id)
        WHEN 'expense'          THEN EXISTS (SELECT 1 FROM mcp_expenses         WHERE expense_id = p_entity_id)
        WHEN 'campaign'         THEN EXISTS (SELECT 1 FROM mcp_campaigns        WHERE campaign_id = p_entity_id)
        WHEN 'content_item'     THEN EXISTS (SELECT 1 FROM mcp_content_items    WHERE content_item_id = p_entity_id)
        WHEN 'location_task'    THEN EXISTS (SELECT 1 FROM mcp_location_tasks   WHERE location_task_id = p_entity_id)
        WHEN 'approval_request' THEN EXISTS (SELECT 1 FROM mcp_approval_requests WHERE approval_request_id = p_entity_id)
        WHEN 'agent'            THEN app_can_see_agent(p_entity_id)
        WHEN 'member'           THEN app_can_admin_member(p_entity_id)
        WHEN 'department'       THEN app_is_insider()
        ELSE app_is_super_admin()    -- unknown/legacy types: super-admin only
    END;
END$$;
GRANT EXECUTE ON FUNCTION app_can_see_entity(text, bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_taggings WITH (security_barrier = true) AS
SELECT tg.tag_id, t.name::text AS tag_name, tg.entity_type, tg.entity_id, tg.created_at
FROM taggings tg JOIN tags t ON t.id = tg.tag_id
WHERE app_is_insider() AND app_can_see_entity(tg.entity_type, tg.entity_id);

CREATE OR REPLACE VIEW mcp_record_comments WITH (security_barrier = true) AS
SELECT rc.id AS comment_id, rc.entity_type, rc.entity_id, rc.author_member_id,
       m.display_name AS author_name, rc.body, rc.created_at, rc.updated_at
FROM record_comments rc JOIN members m ON m.id = rc.author_member_id
WHERE rc.deleted_at IS NULL AND app_can_see_entity(rc.entity_type, rc.entity_id);

-- ==========================================================================
-- ACTIVITY MEMORY VIEWS (granted to app_activity_ro)
-- ==========================================================================

-- History of any record the caller can see (C14, C15, S13, P10, K9, T10, DC7, X1, ...).
CREATE OR REPLACE VIEW mcp_activity_entity_history WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id, m.display_name AS actor_name,
       m.member_kind AS actor_kind, al.source, al.action, al.entity_type, al.entity_id,
       al.before, al.after, al.request_id, al.location_id, al.agent_run_id,
       al.approval_request_id
FROM activity_log al
LEFT JOIN members m ON m.id = al.actor_member_id
WHERE al.entity_type IS NOT NULL
  AND (app_is_super_admin() OR al.actor_member_id = app_current_member_id()
       OR (app_is_dept_admin() AND al.department_id = ANY (app_admin_department_ids()))
       OR app_can_see_entity(al.entity_type, al.entity_id));

-- The business stream: the whole of it for a super-admin, a dept-admin's own departments
-- for them (DB6, X2, X3, X4, A7–A9, AP7, EV7).
CREATE OR REPLACE VIEW mcp_activity_business WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id, m.display_name AS actor_name,
       m.member_kind AS actor_kind, al.source, al.action, al.screen, al.route, al.entity_type,
       al.entity_id, al.before, al.after, al.request_id, al.session_id, al.ip_address,
       al.location_id, al.agent_run_id, al.approval_request_id, al.department_id
FROM activity_log al
LEFT JOIN members m ON m.id = al.actor_member_id
WHERE app_is_super_admin()
   OR (app_is_dept_admin() AND al.department_id = ANY (app_admin_department_ids()));

-- An agent's trail — its timesheet (H6, H13, DB7) — for whoever may see the agent.
CREATE OR REPLACE VIEW mcp_activity_agents WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id AS agent_member_id, m.display_name AS agent_name,
       al.source, al.action, al.screen, al.entity_type, al.entity_id, al.before, al.after,
       al.request_id, al.location_id, al.agent_run_id, al.approval_request_id
FROM activity_log al
JOIN members m ON m.id = al.actor_member_id AND m.member_kind = 'agent'
WHERE app_can_see_agent(al.actor_member_id);

-- ==========================================================================
-- GRANTS — the read roles see ONLY these views.
-- ==========================================================================
GRANT SELECT ON
    mcp_team_directory, mcp_departments, mcp_department_members, mcp_module_grants,
    mcp_record_shares, mcp_token_list, mcp_business_invitations, mcp_business_settings,
    mcp_tags, mcp_organizations, mcp_contacts, mcp_pipelines, mcp_deals, mcp_interactions,
    mcp_projects, mcp_project_members, mcp_milestones, mcp_tasks, mcp_task_dependencies,
    mcp_task_checklist_items, mcp_appointment_types, mcp_bookable_resources, mcp_appointments,
    mcp_appointment_assignees, mcp_appointment_resources, mcp_busy_blocks, mcp_tickets,
    mcp_ticket_messages, mcp_folders, mcp_documents, mcp_document_versions, mcp_document_links,
    mcp_time_entries, mcp_tax_rates, mcp_catalog_items, mcp_quotes, mcp_quote_lines,
    mcp_invoices, mcp_invoice_lines, mcp_payments, mcp_payment_allocations, mcp_credit_notes,
    mcp_payment_providers, mcp_payment_links, mcp_provider_payments, mcp_payouts, mcp_refunds,
    mcp_disputes, mcp_expense_categories, mcp_expenses, mcp_recurring_expenses,
    mcp_accountant_exports, mcp_channels, mcp_campaigns, mcp_content_items,
    mcp_content_variants, mcp_content_metrics, mcp_my_notifications,
    mcp_notification_preferences, mcp_email_messages, mcp_email_suppressions, mcp_my_digests,
    mcp_model_registry, mcp_agents, mcp_agent_config_versions, mcp_agent_tool_grants,
    mcp_agent_duties, mcp_hr_events, mcp_performance_reviews, mcp_agent_escalations,
    mcp_locations, mcp_location_residents, mcp_consent_grants, mcp_location_tasks,
    mcp_approval_policies, mcp_approval_requests, mcp_agent_runs, mcp_prompt_ledger,
    mcp_prompt_payloads, mcp_eval_sets, mcp_eval_cases, mcp_eval_runs, mcp_eval_results,
    mcp_trace_grades, mcp_backup_runs, mcp_restore_rehearsals, mcp_data_exports, mcp_taggings,
    mcp_record_comments
TO app_records_ro;

GRANT SELECT ON mcp_activity_entity_history, mcp_activity_business, mcp_activity_agents
TO app_activity_ro;

COMMIT;
