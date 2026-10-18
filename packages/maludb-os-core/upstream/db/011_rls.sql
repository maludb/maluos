-- 011_rls.sql
-- Row-level security. Design (see 000 header):
--   * app_rw is the single base-table reader/writer (trusted tier). RLS is ENABLED on
--     every data table with one permissive ALL policy for app_rw, so the app operates
--     normally; the app enforces per-member UI visibility in its query WHERE clauses.
--   * The read MCP roles have NO base-table grants. They read only the mcp_* views
--     (012), which embed the §3.2 visibility rules. RLS here is defense-in-depth: even
--     if a base grant were added by mistake, the read roles have no permissive policy,
--     so RLS denies every row.
--
-- We do NOT FORCE RLS: the migration/owner role manages schema and seeds freely.

BEGIN;

-- Enable RLS + grant app_rw an all-access policy on every data table.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'members','auth_identities','totp_recovery_codes','password_reset_tokens',
        'email_verification_tokens','login_attempts','invitations',
        'community_settings','exams','exam_domains','exam_attempts',
        'study_plans','plan_items','plan_comments','study_sessions',
        'study_issues','replies','community_events','event_rsvps',
        'resources','resource_exams','resource_domains','resource_endorsements',
        'notifications','mcp_access_tokens','calendar_feed_tokens','activity_log'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
            t || '_app_rw', t);
    END LOOP;
END$$;

COMMIT;
