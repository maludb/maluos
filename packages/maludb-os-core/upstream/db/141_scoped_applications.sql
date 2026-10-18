-- 141: scoped applications (phase 7 Part C, C1, 2026-09-25 — docs/build-specs/kernel-scoped-applications.md).
--
-- One installation of an application may serve several sites (a restaurant each) or several
-- departments (each its own project plans). The application declares which (scope_kind) and its own
-- roles, each carrying the kernel capability it amounts to. A grant names a scope and a role and goes
-- to a member, a department, or the residents of a site. A site is a new location kind: a place the
-- business trades from, not a machine. Application users are not OS users: nothing is granted by
-- default. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/141_scoped_applications.sql

BEGIN;

-- 1. Sites ---------------------------------------------------------------------------------------

ALTER TABLE locations DROP CONSTRAINT locations_kind_check;
ALTER TABLE locations ADD CONSTRAINT locations_kind_check CHECK (kind IN ('building', 'office', 'desk', 'site'));
ALTER TABLE locations DROP CONSTRAINT locations_siting_by_kind;
ALTER TABLE locations ADD CONSTRAINT locations_siting_by_kind CHECK ((kind IN ('building', 'site')) = (siting IS NULL));
ALTER TABLE locations ADD COLUMN address text;
ALTER TABLE locations ADD COLUMN timezone text;
ALTER TABLE locations ADD CONSTRAINT locations_site_shape CHECK (
    kind <> 'site' OR (parent_location_id IS NULL AND platform IS NULL AND hostname IS NULL
                       AND ip_address IS NULL AND cpu_cores IS NULL AND memory_mb IS NULL
                       AND storage_gb IS NULL AND owner_member_id IS NULL));
ALTER TABLE locations ADD CONSTRAINT locations_site_fields CHECK (kind = 'site' OR (address IS NULL AND timezone IS NULL));
COMMENT ON COLUMN locations.kind IS 'building: a host; office: a VM; desk: an enrolled desktop; site: a place the business trades from (a restaurant, a shop, a branch) — not a machine.';
COMMENT ON COLUMN locations.address IS 'A site''s street address.';
COMMENT ON COLUMN locations.timezone IS 'A site''s IANA time zone.';

CREATE FUNCTION locations_site_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'site' AND NEW.timezone IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = NEW.timezone) THEN
        RAISE EXCEPTION '% is not a time zone — use a name like America/New_York', NEW.timezone;
    END IF;
    IF NEW.parent_location_id IS NOT NULL
       AND (SELECT kind FROM locations WHERE id = NEW.parent_location_id) = 'site' THEN
        RAISE EXCEPTION 'A site is a place the business trades from, not a machine: nothing sits inside one';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.kind <> OLD.kind AND (OLD.kind = 'site' OR NEW.kind = 'site') THEN
        RAISE EXCEPTION 'A site cannot become a machine, or a machine a site — add a new location instead';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER locations_site_rules BEFORE INSERT OR UPDATE ON locations
    FOR EACH ROW EXECUTE FUNCTION locations_site_rules();

CREATE FUNCTION applications_not_at_site() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.location_id IS NOT NULL AND (SELECT kind FROM locations WHERE id = NEW.location_id) = 'site' THEN
        RAISE EXCEPTION 'An application runs on an office, not at a site — it serves sites through its scopes';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER applications_not_at_site BEFORE INSERT OR UPDATE OF location_id ON applications
    FOR EACH ROW EXECUTE FUNCTION applications_not_at_site();

-- 2. The application's scope kind and its roles ---------------------------------------------------

ALTER TABLE applications ADD COLUMN scope_kind text NOT NULL DEFAULT 'none'
    CHECK (scope_kind IN ('none', 'location', 'department'));
COMMENT ON COLUMN applications.scope_kind IS 'none: one installation, one set of data; location: one per site it serves; department: one per department it serves.';

CREATE TABLE application_roles (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    role_key       text   NOT NULL CHECK (role_key ~ '^[a-z][a-z0-9_]{0,39}$'),
    name           text   NOT NULL CHECK (btrim(name) <> ''),
    capability     text   NOT NULL CHECK (capability IN ('read', 'write', 'admin')),
    is_admin       boolean NOT NULL DEFAULT false,
    sort_order     integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, role_key),
    CHECK (NOT is_admin OR capability = 'admin')
);
CREATE UNIQUE INDEX application_roles_one_admin ON application_roles (application_id) WHERE is_admin;
COMMENT ON TABLE application_roles IS 'An application''s own roles, declared in its maludb-os.json; each amounts to a kernel capability. The is_admin role is the one a super-admin holds everywhere.';

-- 3. Scopes --------------------------------------------------------------------------------------

CREATE TABLE application_scopes (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    location_id    bigint REFERENCES locations(id),
    department_id  bigint REFERENCES departments(id),
    added_by       bigint NOT NULL REFERENCES members(id),
    added_at       timestamptz NOT NULL DEFAULT now(),
    removed_at     timestamptz,
    removed_by     bigint REFERENCES members(id),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((location_id IS NULL) <> (department_id IS NULL))
);
CREATE UNIQUE INDEX application_scopes_live_location ON application_scopes (application_id, location_id)
    WHERE removed_at IS NULL AND location_id IS NOT NULL;
CREATE UNIQUE INDEX application_scopes_live_department ON application_scopes (application_id, department_id)
    WHERE removed_at IS NULL AND department_id IS NOT NULL;
CREATE INDEX application_scopes_location_idx ON application_scopes (location_id) WHERE location_id IS NOT NULL;
CREATE INDEX application_scopes_department_idx ON application_scopes (department_id) WHERE department_id IS NOT NULL;
COMMENT ON TABLE application_scopes IS 'The sites or departments one installation of a scoped application serves. The kernel owns them; the application materialises each on its next directory sync.';

CREATE FUNCTION application_scopes_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sk text; lk text; ls text; da timestamptz;
BEGIN
    SELECT scope_kind INTO sk FROM applications WHERE id = NEW.application_id;
    IF sk = 'none' THEN
        RAISE EXCEPTION 'This application is not scoped — set it to serve sites or departments first';
    END IF;
    IF sk = 'location' AND NEW.location_id IS NULL THEN
        RAISE EXCEPTION 'This application is scoped by site — pick a site, not a department';
    END IF;
    IF sk = 'department' AND NEW.department_id IS NULL THEN
        RAISE EXCEPTION 'This application is scoped by department — pick a department, not a site';
    END IF;
    IF TG_OP = 'INSERT' OR NEW.removed_at IS NULL THEN
        IF NEW.location_id IS NOT NULL THEN
            SELECT kind, status INTO lk, ls FROM locations WHERE id = NEW.location_id;
            IF lk IS DISTINCT FROM 'site' THEN
                RAISE EXCEPTION 'An application serves sites — a building, office or desk is a machine';
            END IF;
            IF TG_OP = 'INSERT' AND ls <> 'active' THEN
                RAISE EXCEPTION 'That site is retired';
            END IF;
        ELSIF TG_OP = 'INSERT' THEN
            SELECT archived_at INTO da FROM departments WHERE id = NEW.department_id;
            IF da IS NOT NULL THEN
                RAISE EXCEPTION 'That department is archived';
            END IF;
        END IF;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END$$;
CREATE TRIGGER application_scopes_check BEFORE INSERT OR UPDATE ON application_scopes
    FOR EACH ROW EXECUTE FUNCTION application_scopes_check();

-- Removing a scope revokes every live grant on it, in the same transaction.
CREATE FUNCTION application_scopes_removed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.removed_at IS NOT NULL AND OLD.removed_at IS NULL THEN
        UPDATE application_access SET revoked_at = NEW.removed_at, revoked_by = COALESCE(NEW.removed_by, NEW.added_by)
         WHERE scope_id = NEW.id AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER application_scopes_removed AFTER UPDATE OF removed_at ON application_scopes
    FOR EACH ROW EXECUTE FUNCTION application_scopes_removed();

-- scope_kind is frozen while the application has scopes or live grants.
CREATE FUNCTION applications_scope_kind_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.scope_kind <> OLD.scope_kind AND (
        EXISTS (SELECT 1 FROM application_scopes WHERE application_id = NEW.id AND removed_at IS NULL)
        OR EXISTS (SELECT 1 FROM application_access WHERE application_id = NEW.id AND revoked_at IS NULL)) THEN
        RAISE EXCEPTION 'What this application is scoped by cannot change while it has scopes or live grants — remove them first';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER applications_scope_kind_frozen BEFORE UPDATE OF scope_kind ON applications
    FOR EACH ROW EXECUTE FUNCTION applications_scope_kind_frozen();

-- 4. Grants per scope, with a role, to a member, a department or a site's residents ---------------

ALTER TABLE application_access ADD COLUMN scope_id bigint REFERENCES application_scopes(id);
ALTER TABLE application_access ADD COLUMN role_key text;
ALTER TABLE application_access ADD COLUMN resident_location_id bigint REFERENCES locations(id);
ALTER TABLE application_access DROP CONSTRAINT application_access_one_grantee;
ALTER TABLE application_access ADD CONSTRAINT application_access_one_grantee
    CHECK (num_nonnulls(member_id, department_id, resident_location_id) = 1);
DROP INDEX application_access_member_live_idx;
DROP INDEX application_access_dept_live_idx;
CREATE UNIQUE INDEX application_access_member_live_idx ON application_access
    (application_id, member_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND member_id IS NOT NULL;
CREATE UNIQUE INDEX application_access_dept_live_idx ON application_access
    (application_id, department_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND department_id IS NOT NULL;
CREATE UNIQUE INDEX application_access_residents_live_idx ON application_access
    (application_id, resident_location_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND resident_location_id IS NOT NULL;
CREATE INDEX application_access_scope_idx ON application_access (scope_id) WHERE scope_id IS NOT NULL;
CREATE INDEX application_access_residents_idx ON application_access (resident_location_id) WHERE revoked_at IS NULL;
COMMENT ON COLUMN application_access.scope_id IS 'The scope (site or department) this grant admits to, on a scoped application; NULL on an unscoped one.';
COMMENT ON COLUMN application_access.role_key IS 'The application''s own role, when it declares roles; capability is then the role''s, set by trigger.';
COMMENT ON COLUMN application_access.resident_location_id IS 'Grantee: everyone residing at this site or office.';

CREATE FUNCTION application_access_scope_role() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sk text; s_app bigint; s_removed timestamptz; has_roles boolean; cap text; rk text;
BEGIN
    IF NEW.revoked_at IS NOT NULL AND TG_OP = 'UPDATE' THEN
        RETURN NEW;                                  -- revoking touches nothing else
    END IF;
    SELECT scope_kind INTO sk FROM applications WHERE id = NEW.application_id;
    IF sk = 'none' AND NEW.scope_id IS NOT NULL THEN
        RAISE EXCEPTION 'This application is not scoped — grant it without a scope';
    END IF;
    IF sk <> 'none' THEN
        IF NEW.scope_id IS NULL THEN
            RAISE EXCEPTION 'This application serves several % — pick the one this grant is for',
                CASE sk WHEN 'location' THEN 'sites' ELSE 'departments' END;
        END IF;
        SELECT application_id, removed_at INTO s_app, s_removed FROM application_scopes WHERE id = NEW.scope_id;
        IF s_app IS DISTINCT FROM NEW.application_id THEN
            RAISE EXCEPTION 'That scope belongs to another application';
        END IF;
        IF s_removed IS NOT NULL THEN
            RAISE EXCEPTION 'That scope was removed from this application';
        END IF;
    END IF;
    has_roles := EXISTS (SELECT 1 FROM application_roles WHERE application_id = NEW.application_id);
    IF has_roles THEN
        IF NEW.role_key IS NULL THEN
            SELECT string_agg(role_key, ', ' ORDER BY sort_order, id) INTO rk FROM application_roles WHERE application_id = NEW.application_id;
            RAISE EXCEPTION 'Pick a role: %', rk;
        END IF;
        SELECT capability INTO cap FROM application_roles WHERE application_id = NEW.application_id AND role_key = NEW.role_key;
        IF cap IS NULL THEN
            RAISE EXCEPTION '% is not one of this application''s roles', NEW.role_key;
        END IF;
        NEW.capability := cap;
    ELSIF NEW.role_key IS NOT NULL THEN
        RAISE EXCEPTION 'This application declares no roles — grant a capability instead';
    END IF;
    IF NEW.resident_location_id IS NOT NULL
       AND (SELECT kind FROM locations WHERE id = NEW.resident_location_id) NOT IN ('site', 'office') THEN
        RAISE EXCEPTION 'Grant to the residents of a site or an office — a building has none, and a desk has one person';
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER application_access_scope_role BEFORE INSERT OR UPDATE ON application_access
    FOR EACH ROW EXECUTE FUNCTION application_access_scope_role();

-- A role in use by a live grant cannot be dropped or re-keyed.
CREATE FUNCTION application_roles_in_use() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (TG_OP = 'DELETE' OR NEW.role_key <> OLD.role_key)
       AND EXISTS (SELECT 1 FROM application_access WHERE application_id = OLD.application_id
                      AND role_key = OLD.role_key AND revoked_at IS NULL) THEN
        RAISE EXCEPTION 'The role % is held by live grants — revoke them before removing it', OLD.role_key;
    END IF;
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END$$;
CREATE TRIGGER application_roles_in_use BEFORE UPDATE OR DELETE ON application_roles
    FOR EACH ROW EXECUTE FUNCTION application_roles_in_use();

-- A role's capability change carries through to its live grants.
CREATE FUNCTION application_roles_capability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.capability <> OLD.capability THEN
        UPDATE application_access SET capability = NEW.capability
         WHERE application_id = NEW.application_id AND role_key = NEW.role_key AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER application_roles_capability AFTER UPDATE OF capability ON application_roles
    FOR EACH ROW EXECUTE FUNCTION application_roles_capability();

-- 5. Who holds what -----------------------------------------------------------------------------

CREATE FUNCTION app_capability_rank(p text) RETURNS integer LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE p WHEN 'admin' THEN 3 WHEN 'write' THEN 2 WHEN 'read' THEN 1 ELSE 0 END;
$$;

-- Every live grant on an application that reaches a member, through each of the three routes.
CREATE FUNCTION app_member_grants(p_application bigint, p_member bigint)
RETURNS TABLE (application_access_id bigint, scope_id bigint, role_key text, capability text, route text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT ac.id, ac.scope_id, ac.role_key, ac.capability,
           CASE WHEN ac.member_id IS NOT NULL THEN 'member'
                WHEN ac.department_id IS NOT NULL THEN 'department' ELSE 'residents' END
      FROM application_access ac
      JOIN members m ON m.id = p_member AND m.status = 'active'
     WHERE ac.application_id = p_application
       AND ac.revoked_at IS NULL
       AND (ac.expires_at IS NULL OR ac.expires_at > now())
       AND (ac.scope_id IS NULL OR EXISTS (SELECT 1 FROM application_scopes s WHERE s.id = ac.scope_id AND s.removed_at IS NULL))
       AND (ac.member_id = p_member
            OR ac.department_id IN (SELECT dm.department_id FROM department_members dm
                                     WHERE dm.member_id = p_member AND dm.left_at IS NULL)
            OR ac.resident_location_id IN (SELECT r.location_id FROM location_residents r
                                            WHERE r.member_id = p_member AND r.removed_at IS NULL));
$$;

-- One row per scope the member holds on a scoped application: the highest capability, then the role
-- declared first. A super-admin holds the is_admin role in every live scope. Inactive: nothing.
CREATE FUNCTION app_member_application_scopes(p_application bigint, p_member bigint)
RETURNS TABLE (scope_id bigint, scope_kind text, location_id bigint, department_id bigint, scope_name text,
               role_key text, role_name text, capability text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH app AS (
        SELECT a.id, a.scope_kind FROM applications a WHERE a.id = p_application AND a.scope_kind <> 'none'
    ), who AS (
        SELECT m.business_role = 'super_admin' AS is_super FROM members m WHERE m.id = p_member AND m.status = 'active'
    ), admin_role AS (
        SELECT r.role_key, r.name FROM application_roles r WHERE r.application_id = p_application AND r.is_admin
    ), held AS (
        SELECT g.scope_id, g.role_key, g.capability FROM app_member_grants(p_application, p_member) g
         WHERE g.scope_id IS NOT NULL
        UNION ALL
        SELECT s.id, (SELECT role_key FROM admin_role), 'admin'
          FROM application_scopes s, who
         WHERE who.is_super AND s.application_id = p_application AND s.removed_at IS NULL
    ), best AS (
        SELECT DISTINCT ON (h.scope_id) h.scope_id, h.role_key, h.capability
          FROM held h
          LEFT JOIN application_roles r ON r.application_id = p_application AND r.role_key = h.role_key
         ORDER BY h.scope_id, app_capability_rank(h.capability) DESC, r.sort_order NULLS LAST, r.id NULLS LAST
    )
    SELECT s.id, app.scope_kind, s.location_id, s.department_id,
           COALESCE(l.name, d.name::text), b.role_key, r.name, b.capability
      FROM best b
      JOIN app ON true
      JOIN application_scopes s ON s.id = b.scope_id AND s.removed_at IS NULL
      LEFT JOIN locations l ON l.id = s.location_id
      LEFT JOIN departments d ON d.id = s.department_id
      LEFT JOIN application_roles r ON r.application_id = p_application AND r.role_key = b.role_key
     ORDER BY COALESCE(l.name, d.name::text), s.id;
$$;

-- The member's holding on an unscoped application: the highest capability and its role.
CREATE FUNCTION app_member_application_role(p_application bigint, p_member bigint)
RETURNS TABLE (role_key text, role_name text, capability text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH held AS (
        SELECT g.role_key, g.capability FROM app_member_grants(p_application, p_member) g WHERE g.scope_id IS NULL
        UNION ALL
        SELECT (SELECT r.role_key FROM application_roles r WHERE r.application_id = p_application AND r.is_admin), 'admin'
          FROM members m WHERE m.id = p_member AND m.status = 'active' AND m.business_role = 'super_admin'
    )
    SELECT h.role_key, r.name, h.capability
      FROM held h
      LEFT JOIN application_roles r ON r.application_id = p_application AND r.role_key = h.role_key
     ORDER BY app_capability_rank(h.capability) DESC, r.sort_order NULLS LAST, r.id NULLS LAST
     LIMIT 1;
$$;

-- Any live grant, through any route (the residents route is new).
CREATE OR REPLACE FUNCTION app_can_use_application(p_application_id bigint)
 RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT app_is_super_admin()
        OR EXISTS (SELECT 1 FROM applications ap
                    WHERE ap.id = p_application_id AND ap.is_builtin
                      AND ap.module IS NOT NULL AND app_has_module(ap.module))
        OR EXISTS (SELECT 1 FROM app_member_grants(p_application_id, app_current_member_id()));
$$;

GRANT EXECUTE ON FUNCTION app_capability_rank(text), app_member_grants(bigint, bigint),
    app_member_application_scopes(bigint, bigint), app_member_application_role(bigint, bigint)
    TO app_rw, app_records_ro, app_runner;

-- 6. Views ----------------------------------------------------------------------------------------

-- The launcher's list: capability now through all three routes and ranked (max() on the text ranked
-- 'write' above 'admin'); scope_kind appended.
CREATE OR REPLACE VIEW mcp_my_applications WITH (security_barrier = true) AS
 SELECT a.id AS application_id,
    a.name,
    a.app_key,
    a.category,
    a.is_builtin,
    a.module,
    a.location_id,
    l.name AS location_name,
    a.url,
    a.status,
    a.health_status,
    COALESCE(( SELECT g.capability FROM app_member_grants(a.id, app_current_member_id()) g
                ORDER BY app_capability_rank(g.capability) DESC LIMIT 1),
        CASE WHEN app_is_super_admin() THEN 'admin'::text ELSE NULL::text END) AS capability,
    ( SELECT count(*) AS count
           FROM application_endpoints e
          WHERE ((e.application_id = a.id) AND (e.status = 'active'::text) AND e.agent_reachable)) AS endpoint_count,
    a.sso_path,
    a.scope_kind
   FROM (applications a
     LEFT JOIN locations l ON ((l.id = a.location_id)))
  WHERE ((a.status <> 'retired'::text) AND app_is_insider() AND app_can_use_application(a.id));

CREATE OR REPLACE VIEW mcp_application_access WITH (security_barrier = true) AS
 SELECT ac.id AS application_access_id,
    ac.application_id,
    a.name AS application_name,
    ac.member_id,
    m.display_name AS member_name,
    m.member_kind,
    ac.department_id,
    (d.name)::text AS department_name,
    ac.capability,
    ac.granted_by,
    ac.granted_at,
    ac.expires_at,
    ac.note,
    ac.scope_id,
    COALESCE(sl.name, (sd.name)::text) AS scope_name,
    ac.role_key,
    ar.name AS role_name,
    ac.resident_location_id,
    rl.name AS resident_location_name
   FROM (((((((application_access ac
     JOIN applications a ON ((a.id = ac.application_id)))
     LEFT JOIN members m ON ((m.id = ac.member_id)))
     LEFT JOIN departments d ON ((d.id = ac.department_id)))
     LEFT JOIN application_scopes s ON ((s.id = ac.scope_id)))
     LEFT JOIN locations sl ON ((sl.id = s.location_id)))
     LEFT JOIN departments sd ON ((sd.id = s.department_id)))
     LEFT JOIN application_roles ar ON ((ar.application_id = ac.application_id) AND (ar.role_key = ac.role_key)))
     LEFT JOIN locations rl ON ((rl.id = ac.resident_location_id))
  WHERE ((ac.revoked_at IS NULL) AND app_is_insider() AND (app_has_module('applications'::text) OR app_is_super_admin()
         OR (ac.member_id = app_current_member_id()) OR (ac.department_id = ANY (app_my_department_ids()))
         OR (ac.resident_location_id IN (SELECT r.location_id FROM location_residents r
                                          WHERE r.member_id = app_current_member_id() AND r.removed_at IS NULL))));

CREATE OR REPLACE VIEW mcp_locations AS
 SELECT l.id AS location_id,
    l.name,
    l.kind,
    l.parent_location_id,
    pl.name AS parent_location_name,
    l.description,
    l.owner_member_id,
    om.display_name AS owner_name,
    l.office_manager_member_id,
    l.status,
    l.presence,
    l.last_seen_at,
    l.siting,
    location_allows_resident(l.id, 'agent'::text) AS allows_agents,
    location_allows_resident(l.id, 'human'::text) AS allows_humans,
    l.platform,
    l.operating_system,
    l.os_version,
    l.ssh_access,
    l.root_access,
    l.external_ref,
    l.hostname,
    host(l.ip_address) AS ip_address,
    l.cpu_cores,
    l.memory_mb,
    l.storage_gb,
    l.is_always_on,
    l.app_version,
    l.os_platform,
    l.mcp_surface_version,
    l.enrolled_at,
    l.retired_at,
    ( SELECT count(*) AS count
           FROM locations c
          WHERE ((c.parent_location_id = l.id) AND (c.status = 'active'::text))) AS child_count,
    ( SELECT count(*) AS count
           FROM location_residents r
          WHERE ((r.location_id = l.id) AND (r.removed_at IS NULL))) AS resident_count,
    ( SELECT count(*) AS count
           FROM departments d
          WHERE ((d.home_location_id = l.id) AND (d.archived_at IS NULL))) AS department_count,
    l.address,
    l.timezone,
    ( SELECT count(*) AS count
           FROM application_scopes s
          WHERE ((s.location_id = l.id) AND (s.removed_at IS NULL))) AS serving_application_count
   FROM ((locations l
     LEFT JOIN members om ON ((om.id = l.owner_member_id)))
     LEFT JOIN locations pl ON ((pl.id = l.parent_location_id)))
  WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_applications WITH (security_barrier = true) AS
 SELECT a.id AS application_id,
    a.name,
    a.app_key,
    a.category,
    a.description,
    a.vendor,
    a.is_self_hosted,
    a.is_builtin,
    a.module,
    a.location_id,
    l.name AS location_name,
    l.kind AS location_kind,
    a.owner_department_id,
    (d.name)::text AS owner_department_name,
    a.owner_member_id,
    om.display_name AS owner_name,
    a.url,
    a.version,
    a.criticality,
    a.status,
    a.health_status,
    a.last_health_check_at,
    app_can_use_application(a.id) AS i_can_use,
    a.notes,
    a.retired_at,
    a.created_at,
    a.catalog_key,
    a.business_area_id,
    g.name AS business_area_name,
    g.sort_order AS business_area_sort,
    ((NOT a.is_builtin) OR app_module_enabled(a.module)) AS module_enabled,
    a.sme_agent_member_id,
    sm.display_name AS sme_agent_name,
    a.sso_path,
    a.sso_logout_path,
    a.directory_writes,
    a.scope_kind,
    ( SELECT count(*) AS count
           FROM application_scopes s
          WHERE ((s.application_id = a.id) AND (s.removed_at IS NULL))) AS scope_count
   FROM (((((applications a
     LEFT JOIN locations l ON ((l.id = a.location_id)))
     LEFT JOIN departments d ON ((d.id = a.owner_department_id)))
     LEFT JOIN members om ON ((om.id = a.owner_member_id)))
     LEFT JOIN nav_groups g ON ((g.id = a.business_area_id)))
     LEFT JOIN members sm ON ((sm.id = a.sme_agent_member_id)))
  WHERE app_is_insider();

CREATE VIEW mcp_application_roles WITH (security_barrier = true) AS
 SELECT r.id AS application_role_id, r.application_id, a.name AS application_name, r.role_key, r.name,
        r.capability, r.is_admin, r.sort_order,
        ( SELECT count(*) FROM application_access ac
           WHERE ac.application_id = r.application_id AND ac.role_key = r.role_key AND ac.revoked_at IS NULL) AS live_grant_count
   FROM application_roles r
   JOIN applications a ON a.id = r.application_id
  WHERE app_is_insider();

CREATE VIEW mcp_application_scopes WITH (security_barrier = true) AS
 SELECT s.id AS scope_id, s.application_id, a.name AS application_name, a.scope_kind,
        s.location_id, l.name AS location_name, l.address, l.timezone,
        s.department_id, (d.name)::text AS department_name,
        COALESCE(l.name, (d.name)::text) AS scope_name,
        s.added_by, ab.display_name AS added_by_name, s.added_at, s.updated_at,
        ( SELECT count(*) FROM application_access ac
           WHERE ac.scope_id = s.id AND ac.revoked_at IS NULL) AS live_grant_count
   FROM application_scopes s
   JOIN applications a ON a.id = s.application_id
   LEFT JOIN locations l ON l.id = s.location_id
   LEFT JOIN departments d ON d.id = s.department_id
   LEFT JOIN members ab ON ab.id = s.added_by
  WHERE s.removed_at IS NULL AND app_is_insider();

-- The launcher's scope picker: every scope the signed-in member holds, per application.
CREATE VIEW mcp_my_application_scopes WITH (security_barrier = true) AS
 SELECT a.application_id, x.scope_id, x.scope_kind, x.location_id, x.department_id, x.scope_name,
        x.role_key, x.role_name, x.capability
   FROM mcp_my_applications a
   CROSS JOIN LATERAL app_member_application_scopes(a.application_id, app_current_member_id()) x
  WHERE a.scope_kind <> 'none';

-- 7. Access ------------------------------------------------------------------------------------------

ALTER TABLE application_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_scopes ENABLE ROW LEVEL SECURITY;
CREATE POLICY application_roles_app_rw ON application_roles TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_scopes_app_rw ON application_scopes TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_roles_runner ON application_roles FOR SELECT TO app_runner USING (true);
CREATE POLICY application_scopes_runner ON application_scopes FOR SELECT TO app_runner USING (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON application_roles, application_scopes TO app_rw;
GRANT SELECT ON application_roles, application_scopes TO app_runner;
GRANT SELECT ON mcp_application_roles, mcp_application_scopes, mcp_my_application_scopes TO app_rw, app_records_ro;

COMMIT;
