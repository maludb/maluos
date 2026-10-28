-- 142: a person's default application (2026-09-26 — the owner's direction; docs/build-specs/kernel-default-application.md).
--
-- Arriving at app.<domain>/ or just after signing in, a person who is not a super-admin is taken
-- straight into their default application (and scope, on a scoped one) when they still hold it; with
-- no usable default and exactly one application, into that one; with several, the launcher; with
-- none, the launcher saying so. Set by the person in their settings or by whoever may administer
-- them (app_can_admin_member). Only an application — and scope — the person holds may be named;
-- the default is advice to the landing page, never a grant. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/142_default_application.sql

BEGIN;
ALTER TABLE members ADD COLUMN default_application_id bigint REFERENCES applications(id) ON DELETE SET NULL;
ALTER TABLE members ADD COLUMN default_scope_id bigint REFERENCES application_scopes(id) ON DELETE SET NULL;
ALTER TABLE members ADD CONSTRAINT members_default_scope_needs_application
    CHECK (default_scope_id IS NULL OR default_application_id IS NOT NULL);
COMMENT ON COLUMN members.default_application_id IS 'Where app.<domain>/ takes this person after sign-in, while they still hold it. Advice to the landing page, never a grant.';
COMMENT ON COLUMN members.default_scope_id IS 'On a scoped default application: the site or department to open.';

-- The scope must be one of the default application's.
CREATE FUNCTION members_default_scope_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.default_scope_id IS NOT NULL
       AND (SELECT application_id FROM application_scopes WHERE id = NEW.default_scope_id) IS DISTINCT FROM NEW.default_application_id THEN
        RAISE EXCEPTION 'That site or department is not one this application serves';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER members_default_scope_check BEFORE INSERT OR UPDATE OF default_application_id, default_scope_id ON members
    FOR EACH ROW EXECUTE FUNCTION members_default_scope_check();

-- The caller's own default, for the read servers (they see views, not members).
CREATE FUNCTION app_my_default_application_id() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT default_application_id FROM members WHERE id = app_current_member_id();
$$;
GRANT EXECUTE ON FUNCTION app_my_default_application_id() TO app_rw, app_records_ro, app_runner;
COMMIT;
