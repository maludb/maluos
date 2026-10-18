-- 106: what the Time module needs that db/036 did not give it (additive;
-- docs/build-specs/time.md, owner's decisions of 2026-09-19).
--
--  * time_entries.rejection_reason — the manifest's timesheet_reject takes a REQUIRED reason and
--    the table had nowhere to keep it, so the member could not be told why.
--  * business_settings.default_hourly_rate — the owner's answer to "what is time worth when the
--    project has no rate": project rate → this → no amount (never invoiced at zero).
-- Both are appended to their read views (CREATE OR REPLACE may only add columns at the end).

BEGIN;

ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS rejection_reason text;

ALTER TABLE business_settings
    ADD COLUMN IF NOT EXISTS default_hourly_rate numeric(12,2) CHECK (default_hourly_rate >= 0);

CREATE OR REPLACE VIEW mcp_time_entries WITH (security_barrier = true) AS
 SELECT te.id AS time_entry_id,
    te.member_id,
    m.display_name AS member_name,
    te.entry_date,
    te.started_at,
    te.ended_at,
    te.minutes,
    round(te.minutes::numeric / 60.0, 2) AS hours,
    te.project_id,
    te.task_id,
    te.organization_id,
    te.ticket_id,
    te.appointment_id,
    te.campaign_id,
    te.department_id,
    te.description,
    te.billable,
        CASE
            WHEN app_can_admin_member(te.member_id) OR app_is_external() THEN te.hourly_rate
            ELSE NULL::numeric
        END AS hourly_rate,
    te.currency,
    te.status,
    te.approved_by,
    te.approved_at,
    te.locked_at,
    te.invoice_line_id,
    te.created_at,
    te.updated_at,
    te.rejection_reason,
    -- Whether a rate was snapshotted at all — NOT the rate. Anyone who may see the entry may
    -- know it is unpriced; only someone who administers the member may know the number.
    (te.hourly_rate IS NOT NULL) AS has_rate
   FROM time_entries te
     JOIN members m ON m.id = te.member_id
  WHERE app_can_see('time'::text, te.member_id, te.department_id, 'time_entry'::text, te.id, NULL::bigint);

CREATE OR REPLACE VIEW mcp_business_settings WITH (security_barrier = true) AS
 SELECT business_name, legal_name, base_currency, timezone, fiscal_year_start_month,
        default_payment_terms_days, deal_quiet_days, prompt_payload_retention_days,
        default_hourly_rate
   FROM business_settings
  WHERE app_current_member_id() IS NOT NULL;

COMMIT;
