-- 049_rls_triggers_business.sql
-- Same design as 011_rls.sql and 013_triggers.sql, applied to every Business OS table:
-- RLS enabled with one permissive policy for app_rw (the read MCP roles have no
-- base-table grants and no policy, so RLS denies them every row even if a grant slips in),
-- and updated_at maintenance wherever the column exists.

BEGIN;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        -- 030 foundation
        'business_settings','departments','department_members','module_grants','record_shares',
        'tags','taggings','record_comments','tenant_secrets','document_sequences',
        -- 031 contacts
        'organizations','contacts','pipelines','deal_stages','deals','interactions',
        -- 032 projects
        'projects','project_members','milestones','tasks','task_dependencies','task_checklist_items',
        -- 033 scheduling
        'appointment_types','bookable_resources','appointments','appointment_assignees',
        'appointment_resources','availability_blocks',
        -- 034 tickets
        'ticket_categories','sla_policies','tickets','ticket_messages',
        -- 035 documents
        'folders','documents','document_versions','document_links',
        -- 036 time
        'time_entries',
        -- 037 sales
        'tax_rates','catalog_items','quotes','quote_lines','invoices','invoice_lines',
        'payments','payment_allocations','credit_notes',
        -- 038 online payments
        'payment_providers','payment_links','payouts','provider_payments','provider_events',
        'refunds','disputes',
        -- 039 expenses
        'expense_categories','recurring_expenses','expenses','accountant_exports',
        -- 040 content
        'channels','campaigns','content_items','content_variants','content_variant_media',
        'content_metrics',
        -- 041 notifications
        'notification_preferences','email_messages','email_suppressions','digest_sends',
        -- 042 agent HR
        'model_registry','agent_profiles','agent_config_versions','agent_tool_grants',
        'agent_duties','hr_events','performance_reviews','agent_escalations',
        -- 043 locations
        'locations','location_residents','consent_grants','location_tasks',
        -- 044 approvals
        'approval_policies','approval_requests',
        -- 045 ledger
        'agent_runs','prompt_ledger','prompt_payloads',
        -- 046 evals
        'eval_sets','eval_cases','eval_runs','eval_results','trace_grades',
        -- 047 ops
        'backup_runs','restore_rehearsals','data_exports'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
            t || '_app_rw', t);
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = t AND column_name = 'updated_at') THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                t || '_touch', t);
        END IF;
    END LOOP;
END$$;

-- The ledger and HR history are append-only for the app: no UPDATE/DELETE except the
-- payload-archival columns, no DELETE on the audit trails.
REVOKE UPDATE, DELETE ON prompt_ledger, hr_events, agent_config_versions, provider_events FROM app_rw;
GRANT UPDATE (payload_archived_at) ON prompt_ledger TO app_rw;
GRANT UPDATE (gating_eval_run_id, activated_at, activated_by) ON agent_config_versions TO app_rw;
GRANT UPDATE (processed_at, processing_error, payment_link_id, provider_payment_id) ON provider_events TO app_rw;
REVOKE DELETE ON prompt_payloads FROM app_rw;

COMMIT;
