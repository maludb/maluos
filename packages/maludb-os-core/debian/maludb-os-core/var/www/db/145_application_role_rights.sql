-- 145: application roles published by the application, several per grant (2026-09-27 —
-- docs/build-specs/kernel-application-roles.md).
--
-- An application from us publishes its roles through its own MCP server (tool `app_roles`): each
-- role's name, description, the rights it gives inside the application and the kernel capability it
-- amounts to. The kernel keeps a copy, refreshed on demand, and a super-admin grants a person a SET
-- of roles. A role the application stops publishing is withdrawn, never deleted, so the grants that
-- still hold it can be shown and fixed. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/145_application_role_rights.sql

BEGIN;

-- 1. What a role says about itself ---------------------------------------------------------------

ALTER TABLE application_roles ADD COLUMN description text;
ALTER TABLE application_roles ADD COLUMN rights jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(rights) = 'array');
ALTER TABLE application_roles ADD COLUMN withdrawn_at timestamptz;
ALTER TABLE application_roles ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE application_roles ADD CONSTRAINT application_roles_withdrawn_not_admin CHECK (withdrawn_at IS NULL OR NOT is_admin);
COMMENT ON COLUMN application_roles.rights IS 'What the role lets its holder do inside the application, as the application published it: [{key, description}]. The application enforces them; the kernel shows them and passes the keys on.';
COMMENT ON COLUMN application_roles.withdrawn_at IS 'The application no longer publishes this role. Kept while grants hold it, so they can be shown and changed; never granted anew.';

ALTER TABLE applications ADD COLUMN roles_synced_at timestamptz;
COMMENT ON COLUMN applications.roles_synced_at IS 'When the roles were last read from the application''s own MCP server (app_roles); NULL = set by hand, or none.';

-- 2. Several roles on one grant ----------------------------------------------------------------------

CREATE TABLE application_access_roles (
    application_access_id bigint NOT NULL REFERENCES application_access(id) ON DELETE CASCADE,
    application_id        bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    role_key              text   NOT NULL,
    PRIMARY KEY (application_access_id, role_key)
);
CREATE INDEX application_access_roles_role_idx ON application_access_roles (application_id, role_key);
COMMENT ON TABLE application_access_roles IS 'The roles one grant gives. application_access.role_key stays the highest of them (its capability is the grant''s), for everything that reads one role.';

CREATE FUNCTION application_access_roles_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE g_app bigint; w timestamptz; found boolean;
BEGIN
    SELECT application_id INTO g_app FROM application_access WHERE id = NEW.application_access_id;
    IF g_app IS DISTINCT FROM NEW.application_id THEN
        RAISE EXCEPTION 'That grant belongs to another application';
    END IF;
    SELECT true, withdrawn_at INTO found, w FROM application_roles
     WHERE application_id = NEW.application_id AND role_key = NEW.role_key;
    IF found IS NULL THEN
        RAISE EXCEPTION '% is not one of this application''s roles', NEW.role_key;
    END IF;
    IF w IS NOT NULL THEN
        RAISE EXCEPTION 'The application no longer offers the role %', NEW.role_key;
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER application_access_roles_check BEFORE INSERT ON application_access_roles
    FOR EACH ROW EXECUTE FUNCTION application_access_roles_check();

-- Every grant that names a role today holds that one role.
INSERT INTO application_access_roles (application_access_id, application_id, role_key)
SELECT id, application_id, role_key FROM application_access WHERE role_key IS NOT NULL;

-- A role held by a live grant (as its one role or among several) cannot be deleted or re-keyed.
CREATE OR REPLACE FUNCTION application_roles_in_use() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (TG_OP = 'DELETE' OR NEW.role_key <> OLD.role_key)
       AND (EXISTS (SELECT 1 FROM application_access WHERE application_id = OLD.application_id
                       AND role_key = OLD.role_key AND revoked_at IS NULL)
            OR EXISTS (SELECT 1 FROM application_access_roles x JOIN application_access ac ON ac.id = x.application_access_id
                        WHERE x.application_id = OLD.application_id AND x.role_key = OLD.role_key AND ac.revoked_at IS NULL)) THEN
        RAISE EXCEPTION 'The role % is held by live grants — revoke them before removing it', OLD.role_key;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END$$;

-- A role's capability change: each live grant holding it takes the highest capability among its
-- roles again, and its role_key the role that gives it.
CREATE OR REPLACE FUNCTION application_roles_capability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.capability <> OLD.capability THEN
        PERFORM app_grant_settle(ac.id)
           FROM application_access ac
          WHERE ac.application_id = NEW.application_id AND ac.revoked_at IS NULL
            AND (ac.role_key = NEW.role_key OR EXISTS (SELECT 1 FROM application_access_roles x
                  WHERE x.application_access_id = ac.id AND x.role_key = NEW.role_key));
    END IF;
    RETURN NEW;
END$$;

-- 3. Who holds what ------------------------------------------------------------------------------------

-- The highest of a grant's roles becomes its role_key; the access trigger then sets its capability.
CREATE FUNCTION app_grant_settle(p_access bigint) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path TO 'public' AS $$
    UPDATE application_access ac
       SET role_key = top.role_key
      FROM (SELECT x.role_key FROM application_access_roles x
              JOIN application_roles r ON r.application_id = x.application_id AND r.role_key = x.role_key
             WHERE x.application_access_id = p_access
             ORDER BY app_capability_rank(r.capability) DESC, r.sort_order, r.id LIMIT 1) top
     WHERE ac.id = p_access AND ac.revoked_at IS NULL;
$$;

-- Every role that reaches a member on an application, per scope (NULL on an unscoped one), through
-- any grant and any route; withdrawn roles are left out. A super-admin holds the admin role on an
-- unscoped application and in every live scope of a scoped one.
CREATE FUNCTION app_member_role_keys(p_application bigint, p_member bigint)
RETURNS TABLE (scope_id bigint, role_key text, capability text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH app AS (
        SELECT id, scope_kind FROM applications WHERE id = p_application
    ), reached AS (
        SELECT g.scope_id, COALESCE(x.role_key, g.role_key) AS role_key
          FROM app_member_grants(p_application, p_member) g
          LEFT JOIN application_access_roles x ON x.application_access_id = g.application_access_id
        UNION
        SELECT s.id, r.role_key
          FROM app, members m, application_roles r, application_scopes s
         WHERE app.scope_kind <> 'none' AND m.id = p_member AND m.status = 'active' AND m.business_role = 'super_admin'
           AND r.application_id = p_application AND r.is_admin
           AND s.application_id = p_application AND s.removed_at IS NULL
        UNION
        SELECT NULL::bigint, r.role_key
          FROM app, members m, application_roles r
         WHERE app.scope_kind = 'none' AND m.id = p_member AND m.status = 'active' AND m.business_role = 'super_admin'
           AND r.application_id = p_application AND r.is_admin
    )
    SELECT h.scope_id, h.role_key, r.capability
      FROM reached h
      JOIN application_roles r ON r.application_id = p_application AND r.role_key = h.role_key AND r.withdrawn_at IS NULL
     ORDER BY h.scope_id NULLS FIRST, r.sort_order, r.id;
$$;

GRANT EXECUTE ON FUNCTION app_member_role_keys(bigint, bigint) TO app_rw, app_records_ro, app_runner;
GRANT EXECUTE ON FUNCTION app_grant_settle(bigint) TO app_rw;

-- 4. Views ------------------------------------------------------------------------------------------------

CREATE OR REPLACE VIEW mcp_application_roles WITH (security_barrier = true) AS
 SELECT r.id AS application_role_id, r.application_id, a.name AS application_name, r.role_key, r.name,
        r.capability, r.is_admin, r.sort_order,
        ( SELECT count(DISTINCT ac.id) FROM application_access ac
           LEFT JOIN application_access_roles x ON x.application_access_id = ac.id
           WHERE ac.application_id = r.application_id AND ac.revoked_at IS NULL
             AND (ac.role_key = r.role_key OR x.role_key = r.role_key)) AS live_grant_count,
        r.description, r.rights, r.withdrawn_at
   FROM application_roles r
   JOIN applications a ON a.id = r.application_id
  WHERE app_is_insider();

-- Each grant's roles, as keys and names, beside what mcp_application_access already says.
CREATE VIEW mcp_application_access_roles WITH (security_barrier = true) AS
 SELECT x.application_access_id, x.application_id, x.role_key, r.name AS role_name, r.capability,
        r.withdrawn_at IS NOT NULL AS withdrawn
   FROM application_access_roles x
   JOIN application_access ac ON ac.id = x.application_access_id AND ac.revoked_at IS NULL
   JOIN application_roles r ON r.application_id = x.application_id AND r.role_key = x.role_key
  WHERE app_is_insider();

-- 5. Access ---------------------------------------------------------------------------------------------

ALTER TABLE application_access_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY application_access_roles_app_rw ON application_access_roles TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_access_roles_runner ON application_access_roles FOR SELECT TO app_runner USING (true);
GRANT SELECT, INSERT, DELETE ON application_access_roles TO app_rw;
GRANT SELECT ON application_access_roles TO app_runner;
GRANT SELECT ON mcp_application_roles, mcp_application_access_roles TO app_rw, app_records_ro;

COMMIT;
