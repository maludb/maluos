-- 118: My Work — one gatherer for the screen and the tool (docs/build-specs/my-work.md). ADDITIVE.
--
-- app_my_work() reads ONLY mcp_* views as the caller (SECURITY INVOKER), so a row it returns is a
-- row the caller could already open. Each section is its own block: a failure is a WARNING and a
-- skipped section, never a broken page. `waiting` = it waits on the caller (counted in the
-- header); false = coming up, or waiting on someone else. At most p_limit rows per section;
-- `total` is the section's full count.
BEGIN;

CREATE OR REPLACE FUNCTION app_my_work(p_horizon_days integer DEFAULT 7, p_limit integer DEFAULT 10)
RETURNS TABLE (section text, waiting boolean, kind text, id bigint, title text, detail text,
               due_at timestamptz, state text, href text, urgency integer, total bigint)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = public AS $fn$
DECLARE
    me bigint := app_current_member_id();
    horizon integer := least(greatest(coalesce(p_horizon_days, 7), 1), 60);
    lim integer := least(greatest(coalesce(p_limit, 10), 1), 50);
BEGIN
    IF me IS NULL THEN
        RETURN;
    END IF;

    BEGIN RETURN QUERY
        SELECT 'approvals_to_decide', true, 'approval_request', r.approval_request_id, r.summary,
               'asked by ' || coalesce(r.requested_by_name, 'someone'), r.expires_at, 'pending'::text,
               '/approvals/' || r.approval_request_id, 0, count(*) OVER ()
          FROM mcp_approval_requests r WHERE r.status = 'pending' AND r.approver_member_id = me
         ORDER BY r.expires_at NULLS LAST, r.created_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work approvals_to_decide: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'time_to_approve', true, 'time_week', w.member_id, w.member_name || ' — week of ' || to_char(w.week_start, 'DD Mon'),
               round(w.minutes / 60.0, 1) || ' h in ' || w.entries || ' entries', NULL::timestamptz, 'submitted'::text,
               '/time/approvals?week=' || to_char(w.week_start, 'YYYY-MM-DD'), 0, count(*) OVER ()
          FROM (SELECT te.member_id, te.member_name, date_trunc('week', te.entry_date)::date AS week_start,
                       sum(te.minutes) AS minutes, count(*) AS entries
                  FROM mcp_time_entries te
                 WHERE te.status = 'submitted' AND te.member_id <> me AND (app_is_admin() OR app_has_module('time'))
                 GROUP BY 1, 2, 3) w
         ORDER BY w.week_start, w.member_name LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work time_to_approve: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'appointments_to_answer', true, 'appointment', a.appointment_id, a.title,
               CASE WHEN a.recurrence_rule IS NOT NULL THEN 'a repeating appointment' ELSE a.organization_name END,
               CASE WHEN a.recurrence_rule IS NULL THEN a.starts_at END, 'no answer yet'::text,
               '/schedule/' || a.appointment_id, 0, count(*) OVER ()
          FROM mcp_appointment_assignees aa JOIN mcp_appointments a ON a.appointment_id = aa.appointment_id
         WHERE aa.member_id = me AND aa.response = 'pending' AND a.status IN ('scheduled', 'confirmed') AND a.recurrence_parent_id IS NULL
           AND (a.starts_at >= now() OR a.recurrence_rule IS NOT NULL)
         ORDER BY a.starts_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work appointments_to_answer: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'tickets', true, 'ticket', x.ticket_id, x.number || ' — ' || x.subject, x.organization_name, x.due, x.sla,
               '/tickets/' || x.ticket_id,
               CASE x.sla WHEN 'breached' THEN 0 WHEN 'due_soon' THEN 1 ELSE 2 END, count(*) OVER ()
          FROM (SELECT t.*, d.due,
                       CASE WHEN t.status IN ('pending', 'on_hold') THEN 'paused'
                            WHEN d.due IS NULL THEN t.status
                            WHEN d.due < now() THEN 'breached'
                            WHEN d.due < now() + interval '2 hours' THEN 'due_soon' ELSE 'on_track' END AS sla
                  FROM mcp_tickets t
                  CROSS JOIN LATERAL (SELECT CASE WHEN t.first_responded_at IS NULL AND t.first_response_due_at IS NOT NULL
                                                  THEN least(t.first_response_due_at, coalesce(t.resolution_due_at, t.first_response_due_at))
                                                  ELSE t.resolution_due_at END AS due) d
                 WHERE t.assignee_member_id = me AND t.status NOT IN ('resolved', 'closed')) x
         ORDER BY 10, array_position(ARRAY['urgent', 'high', 'normal', 'low'], x.priority), x.due NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work tickets: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'mail', true, 'mail_thread', t.mail_thread_id, t.subject, t.mailbox_name || coalesce(' · ' || t.organization_name, ''),
               t.last_message_at, 'waiting on us'::text, '/inbox/threads/' || t.mail_thread_id, 0, count(*) OVER ()
          FROM mcp_mail_threads t
         WHERE t.assigned_member_id = me AND t.status = 'open' AND t.last_direction = 'inbound' AND t.message_count > 0
         ORDER BY t.last_message_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work mail: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'content_to_review', true, 'content_item', c.content_item_id, c.title,
               'by ' || coalesce(c.author_name, 'someone') || coalesce(' · ' || c.campaign_name, ''), c.updated_at, 'in review'::text,
               '/content/' || c.content_item_id, 0, count(*) OVER ()
          FROM mcp_content_items c WHERE c.status = 'in_review' AND c.reviewer_member_id = me
         ORDER BY c.updated_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work content_to_review: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'leave_to_decide', true, 'leave_request', l.leave_request_id, l.display_name || ' — ' || l.leave_type,
               to_char(l.start_date, 'DD Mon') || ' – ' || to_char(l.end_date, 'DD Mon') || ' · ' || l.days || ' d', l.start_date::timestamptz, 'requested'::text,
               '/people/leave/' || l.leave_request_id, 0, count(*) OVER ()
          FROM mcp_leave_requests l
         WHERE l.status = 'requested' AND l.member_id <> me
           AND (app_is_super_admin() OR (app_has_module('people') AND app_can_admin_member(l.member_id)))
         ORDER BY l.start_date LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work leave_to_decide: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'form_submissions', true, 'form_submission', s.form_submission_id, s.form_name, NULL::text, s.submitted_at, 'new'::text,
               '/forms/submissions/' || s.form_submission_id, 0, count(*) OVER ()
          FROM mcp_form_submissions s JOIN mcp_forms f ON f.form_id = s.form_id
         WHERE s.status = 'new' AND f.assign_member_id = me
         ORDER BY s.submitted_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work form_submissions: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'tasks', true, 'task', t.task_id, t.title, t.project_name, t.due_date::timestamptz,
               CASE WHEN t.status = 'blocked' OR t.has_open_dependencies THEN 'blocked'
                    WHEN t.due_date < current_date THEN 'overdue' WHEN t.due_date = current_date THEN 'due today' ELSE 'due' END,
               '/tasks/' || t.task_id, CASE WHEN t.due_date < current_date THEN 0 WHEN t.due_date = current_date THEN 1 ELSE 2 END, count(*) OVER ()
          FROM mcp_tasks t
         WHERE t.assignee_member_id = me AND t.status NOT IN ('done', 'cancelled') AND t.due_date IS NOT NULL AND t.due_date <= current_date + horizon
         ORDER BY t.due_date, t.priority DESC LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work tasks: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'invoices_overdue', true, 'invoice', i.invoice_id, i.number || coalesce(' — ' || i.organization_name, ''),
               i.balance_due || ' ' || i.currency || ' outstanding', i.due_date::timestamptz, i.days_overdue || ' days overdue',
               '/invoices/' || i.invoice_id, 0, count(*) OVER ()
          FROM mcp_invoices i
         WHERE i.owner_member_id = me AND i.voided_at IS NULL AND i.status <> 'draft' AND i.balance_due > 0 AND i.days_overdue > 0
         ORDER BY i.days_overdue DESC LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work invoices_overdue: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'time_mine', true, 'time_week', to_char(w.week_start, 'YYYYMMDD')::bigint, 'Week of ' || to_char(w.week_start, 'DD Mon'),
               round(w.minutes / 60.0, 1) || ' h', NULL::timestamptz, w.state, '/time?week=' || to_char(w.week_start, 'YYYY-MM-DD'),
               CASE w.state WHEN 'rejected' THEN 0 ELSE 1 END, count(*) OVER ()
          FROM (SELECT date_trunc('week', te.entry_date)::date AS week_start, sum(te.minutes) AS minutes,
                       CASE WHEN bool_or(te.status = 'rejected') THEN 'rejected' ELSE 'not submitted' END AS state
                  FROM mcp_time_entries te
                 WHERE te.member_id = me AND te.entry_date >= current_date - 60
                   AND (te.status = 'rejected' OR (te.status = 'draft' AND te.entry_date < date_trunc('week', current_date)::date))
                 GROUP BY 1) w
         ORDER BY 10, w.week_start LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work time_mine: %', SQLERRM; END;

    -- Coming up, or waiting on someone else: shown, not counted.
    BEGIN RETURN QUERY
        SELECT 'approvals_mine', false, 'approval_request', r.approval_request_id, r.summary,
               'waiting for ' || coalesce(r.approver_name, 'an approver'), r.expires_at, 'pending'::text,
               '/approvals/' || r.approval_request_id, 0, count(*) OVER ()
          FROM mcp_approval_requests r WHERE r.status = 'pending' AND r.requested_by_member_id = me
         ORDER BY r.created_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work approvals_mine: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'purchase_orders', false, 'purchase_order', p.purchase_order_id, p.po_number || coalesce(' — ' || p.vendor_name, ''),
               CASE p.status WHEN 'partial' THEN 'partly received' ELSE 'sent' END, p.expected_date::timestamptz,
               CASE WHEN p.expected_date < current_date THEN 'late' ELSE 'awaiting receipt' END,
               '/inventory/orders/' || p.purchase_order_id, CASE WHEN p.expected_date < current_date THEN 0 ELSE 1 END, count(*) OVER ()
          FROM mcp_purchase_orders p WHERE p.owner_member_id = me AND p.status IN ('sent', 'partial')
         ORDER BY 10, p.expected_date NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work purchase_orders: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'signatures_out', false, 'signature_request', s.signature_request_id, s.subject,
               s.signed_count || ' of ' || s.signer_count || ' signed' || coalesce(' · ' || s.organization_name, ''), s.expires_at,
               CASE s.status WHEN 'partially_signed' THEN 'partly signed' ELSE 'sent' END,
               '/signatures/' || s.signature_request_id, 0, count(*) OVER ()
          FROM mcp_signature_requests s WHERE s.owner_member_id = me AND s.status IN ('sent', 'partially_signed')
         ORDER BY s.expires_at NULLS LAST, s.sent_at LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work signatures_out: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'leave_mine', false, 'leave_request', l.leave_request_id, l.leave_type,
               to_char(l.start_date, 'DD Mon') || ' – ' || to_char(l.end_date, 'DD Mon') || ' · ' || l.days || ' d', l.start_date::timestamptz,
               l.status, '/people/leave/' || l.leave_request_id, 0, count(*) OVER ()
          FROM mcp_leave_requests l
         WHERE l.member_id = me AND ((l.status = 'approved' AND l.end_date >= current_date AND l.start_date <= current_date + horizon) OR l.status = 'requested')
         ORDER BY l.start_date LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work leave_mine: %', SQLERRM; END;

    BEGIN RETURN QUERY
        SELECT 'duties', false, 'agent_duty', d.duty_id, d.name, d.schedule_cron, d.next_run_at, 'scheduled'::text,
               '/agents/' || d.agent_member_id, 0, count(*) OVER ()
          FROM mcp_agent_duties d WHERE d.agent_member_id = me AND d.active
         ORDER BY d.next_run_at NULLS LAST LIMIT lim;
    EXCEPTION WHEN OTHERS THEN RAISE WARNING 'app_my_work duties: %', SQLERRM; END;
END;
$fn$;

REVOKE ALL ON FUNCTION app_my_work(integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_my_work(integer, integer) TO app_rw, app_records_ro;

COMMIT;
