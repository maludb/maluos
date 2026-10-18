-- 100_runner_member_columns.sql
-- 097 granted app_runner SELECT on the whole of `members`, which includes password_hash and
-- totp_secret. The runner renders a persona and checks that an agent is active; it has no business
-- reading a credential. Column-level SELECT instead — found while building the runner, before it
-- ever connected.

BEGIN;

REVOKE SELECT ON members FROM app_runner;
GRANT SELECT (id, display_name, status, member_kind, business_role, job_title, timezone)
    ON members TO app_runner;

COMMIT;
