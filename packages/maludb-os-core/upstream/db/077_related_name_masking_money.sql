-- 077_related_name_masking_money.sql
-- A record you may see must still not name a record you may not — the money modules.
--
-- db/065 fixed this for mcp_contacts and mcp_deals during the Contacts slice, and said why:
-- "the row rule was right; the borrowed label leaked around it." Every money module built
-- afterwards reintroduced it, because each one joins organizations for a readable name and
-- nothing carried the lesson forward.
--
-- Proven 2026-09-18, twice:
--   * A plain user with no grants sees an expense he submitted himself and it prints
--     "Acme Manufacturing", while mcp_organizations returns him nothing for that company.
--   * A member holding `sales` but not `contacts` sees ZERO organizations, yet mcp_invoices
--     printed 4 customer names, mcp_quotes 1 and mcp_payments 3. Organizations are gated on the
--     contacts module; the sales views never asked.
--
-- The cause is visible in the gates: mcp_expenses and mcp_recurring_expenses call app_can_see()
-- with NULL for the organization, so the vendor is never considered; mcp_invoices and mcp_quotes
-- do pass organization_id, but app_can_see admits them on the sales grant alone, which says
-- nothing about whether the caller may see the company.
--
-- Same treatment as db/065: the rows each view returns are UNCHANGED, the id stays (a caller who
-- cannot see the company cannot open it either way), and only the borrowed label is masked —
-- NULL, which the screens already print as an em dash.
--
-- Not fixed here, deliberately: mcp_tasks, mcp_milestones, mcp_projects, mcp_tickets,
-- mcp_mail_threads, mcp_signature_requests and mcp_purchase_orders carry the same shape. Their
-- slices are unbuilt or owned by another session (projects/tasks/milestones are being specified
-- now, and that session found the leak independently). Each should mask at build time rather
-- than have this migration reach into a module nobody has shipped.

BEGIN;

CREATE OR REPLACE VIEW mcp_expenses AS
SELECT e.id AS expense_id,
    e.number,
    e.vendor_organization_id,
    CASE WHEN app_can_see('contacts'::text, vo.owner_member_id, vo.department_id,
                             'organization'::text, vo.id, vo.id)
             THEN vo.name ELSE NULL::text END AS vendor_name,
    e.vendor_contact_id,
    e.category_id,
    ec.name::text AS category_name,
    e.description,
    e.expense_date,
    e.due_date,
    e.amount,
    e.tax_amount,
    e.currency,
    e.payment_status,
    e.paid_on,
    e.payment_method,
    e.status,
    e.submitted_by,
    sm.display_name AS submitted_by_name,
    sm.member_kind AS submitted_by_kind,
    e.approved_by,
    e.approved_at,
    e.approval_request_id,
    e.project_id,
    e.task_id,
    e.organization_id,
    e.campaign_id,
    e.billable,
    e.invoice_line_id,
    e.receipt_document_id IS NOT NULL AS has_receipt,
    e.receipt_document_id,
    e.recurring_expense_id,
    e.department_id,
    e.search_tsv,
    e.created_at,
    e.updated_at
   FROM expenses e
     LEFT JOIN organizations vo ON vo.id = e.vendor_organization_id
     LEFT JOIN expense_categories ec ON ec.id = e.category_id
     LEFT JOIN members sm ON sm.id = e.submitted_by
  WHERE e.submitted_by = app_current_member_id() OR app_can_see('expenses'::text, NULL::bigint, e.department_id, 'expense'::text, e.id, NULL::bigint);

CREATE OR REPLACE VIEW mcp_recurring_expenses AS
SELECT r.id AS recurring_expense_id,
    r.vendor_organization_id,
    CASE WHEN app_can_see('contacts'::text, vo.owner_member_id, vo.department_id,
                             'organization'::text, vo.id, vo.id)
             THEN vo.name ELSE NULL::text END AS vendor_name,
    r.category_id,
    r.description,
    r.amount,
    r.currency,
    r.frequency,
    r.next_due_on,
    r.ends_on,
    r.active,
    r.department_id
   FROM recurring_expenses r
     LEFT JOIN organizations vo ON vo.id = r.vendor_organization_id
  WHERE app_can_see('expenses'::text, NULL::bigint, r.department_id, 'recurring_expense'::text, r.id, NULL::bigint);

CREATE OR REPLACE VIEW mcp_invoices AS
SELECT i.id AS invoice_id,
    i.number,
    i.organization_id,
    CASE WHEN app_can_see('contacts'::text, o.owner_member_id, o.department_id,
                             'organization'::text, o.id, o.id)
             THEN o.name ELSE NULL::text END AS organization_name,
    i.contact_id,
    i.deal_id,
    i.project_id,
    i.quote_id,
    i.status,
    i.issue_date,
    i.due_date,
    i.currency,
    i.subtotal,
    i.tax_total,
    i.total,
    i.amount_paid,
    i.amount_credited,
    i.balance_due,
        CASE
            WHEN (i.status = ANY (ARRAY['sent'::text, 'viewed'::text, 'partially_paid'::text])) AND i.due_date < CURRENT_DATE THEN CURRENT_DATE - i.due_date
            ELSE 0
        END AS days_overdue,
    i.online_payment_enabled,
    i.sent_at,
    i.first_viewed_at,
    i.paid_at,
    i.voided_at,
    i.void_reason,
    i.last_reminder_at,
    i.reminder_count,
    i.notes,
    i.terms,
    i.owner_member_id,
    i.department_id,
    i.created_by,
    cm.member_kind AS created_by_kind,
    i.created_at,
    i.updated_at
   FROM invoices i
     LEFT JOIN organizations o ON o.id = i.organization_id
     LEFT JOIN members cm ON cm.id = i.created_by
  WHERE (i.status <> 'draft'::text OR app_is_insider()) AND app_can_see('sales'::text, i.owner_member_id, i.department_id, 'invoice'::text, i.id, i.organization_id);

CREATE OR REPLACE VIEW mcp_quotes AS
SELECT q.id AS quote_id,
    q.number,
    q.organization_id,
    CASE WHEN app_can_see('contacts'::text, o.owner_member_id, o.department_id,
                             'organization'::text, o.id, o.id)
             THEN o.name ELSE NULL::text END AS organization_name,
    q.contact_id,
    q.deal_id,
    q.project_id,
    q.status,
    q.issue_date,
    q.valid_until,
    q.currency,
    q.subtotal,
    q.tax_total,
    q.total,
    q.notes,
    q.terms,
    q.sent_at,
    q.accepted_at,
    q.declined_at,
    q.converted_invoice_id,
    q.owner_member_id,
    q.department_id,
    q.created_by,
    q.created_at,
    q.updated_at
   FROM quotes q
     LEFT JOIN organizations o ON o.id = q.organization_id
  WHERE (q.status <> 'draft'::text OR app_is_insider()) AND app_can_see('sales'::text, q.owner_member_id, q.department_id, 'quote'::text, q.id, q.organization_id);

CREATE OR REPLACE VIEW mcp_payments AS
SELECT p.id AS payment_id,
    p.organization_id,
    CASE WHEN app_can_see('contacts'::text, o.owner_member_id, o.department_id,
                             'organization'::text, o.id, o.id)
             THEN o.name ELSE NULL::text END AS organization_name,
    p.contact_id,
    p.received_on,
    p.amount,
    p.currency,
    p.method,
    p.source,
    p.provider_payment_id,
    p.reference,
    p.notes,
    p.recorded_by,
    COALESCE(( SELECT sum(pa.amount) AS sum
           FROM payment_allocations pa
          WHERE pa.payment_id = p.id), 0::numeric) AS amount_allocated,
    p.created_at
   FROM payments p
     LEFT JOIN organizations o ON o.id = p.organization_id
  WHERE app_can_see('sales'::text, NULL::bigint, NULL::bigint, 'payment'::text, p.id, p.organization_id);

COMMIT;
