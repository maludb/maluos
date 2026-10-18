-- 030_business_foundation.sql
-- Business OS foundation: business roles on members, business settings, departments,
-- module grants, record sharing for External members, tags, tenant secrets, document
-- numbering, and the visibility helpers every later mcp_* view is built on.
-- Questions: A1–A6, H1, H11 (docs/business-os-questions.md); schema design notes in
-- docs/business-os-schema.md.
--
-- Cert-study compatibility: members.role ('member'/'organizer') is left untouched so the
-- fork's modules keep working. Business visibility keys on the NEW members.business_role.
-- When the cert-study modules are retired, members.role goes with them.

BEGIN;

-- --------------------------------------------------------------------------
-- Members: business identity (humans and AI agents share one identity space)
-- --------------------------------------------------------------------------
-- Three roles, and only three:
--   super_admin  administers the entire system
--   dept_admin   administers the departments they are an admin of, and is an ordinary user
--                everywhere else
--   user         works here; sees what their module grants and departments allow
-- "External" (the accountant, a customer with a portal login) is NOT a fourth role: it is a
-- flag on a user, because an outsider is a user whose reach is limited to what is granted or
-- shared with them. A human can belong to many departments (department_members).
ALTER TABLE members
    ADD COLUMN member_kind   text NOT NULL DEFAULT 'human'
                                 CHECK (member_kind IN ('human', 'agent')),
    ADD COLUMN business_role text NOT NULL DEFAULT 'user'
                                 CHECK (business_role IN ('super_admin', 'dept_admin', 'user')),
    ADD COLUMN is_external   boolean NOT NULL DEFAULT false,
    ADD COLUMN job_title     text,
    ADD COLUMN phone         text,
    ADD COLUMN offboarded_at timestamptz,
    -- Agents are always plain users: they act with a user's rights, never administer.
    ADD CONSTRAINT members_agent_is_user_check
        CHECK (member_kind = 'human' OR business_role = 'user'),
    -- An external person is never an administrator.
    ADD CONSTRAINT members_external_is_user_check
        CHECK (NOT is_external OR business_role = 'user');

-- Offboarded members keep their row and trail forever (agent HR: never delete).
ALTER TABLE members DROP CONSTRAINT members_status_check;
ALTER TABLE members ADD CONSTRAINT members_status_check
    CHECK (status IN ('active', 'suspended', 'offboarded'));

CREATE INDEX members_business_role_idx ON members (business_role, member_kind) WHERE status = 'active';
CREATE INDEX members_external_idx ON members (is_external) WHERE is_external AND status = 'active';

ALTER TABLE invitations
    ADD COLUMN business_role_granted text NOT NULL DEFAULT 'user'
        CHECK (business_role_granted IN ('super_admin', 'dept_admin', 'user')),
    ADD COLUMN is_external_granted   boolean NOT NULL DEFAULT false,
    ADD COLUMN department_id         bigint;      -- FK added after departments, below

-- --------------------------------------------------------------------------
-- Business settings (singleton row; this database IS one tenant)
-- --------------------------------------------------------------------------
CREATE TABLE business_settings (
    id                          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    business_name               text NOT NULL,
    legal_name                  text,
    tax_id                      text,
    base_currency               char(3) NOT NULL DEFAULT 'USD',   -- ISO 4217; no FX conversion in v1
    timezone                    text NOT NULL DEFAULT 'UTC',
    fiscal_year_start_month     smallint NOT NULL DEFAULT 1 CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    address                     jsonb,
    email                       citext,
    phone                       text,
    website                     text,
    default_payment_terms_days  integer NOT NULL DEFAULT 30 CHECK (default_payment_terms_days >= 0),
    deal_quiet_days             integer NOT NULL DEFAULT 14 CHECK (deal_quiet_days > 0),    -- C6
    prompt_payload_retention_days integer CHECK (prompt_payload_retention_days > 0),        -- PL8; null = keep
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Departments + membership (humans and agents alike)
-- --------------------------------------------------------------------------
CREATE TABLE departments (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               citext NOT NULL UNIQUE,
    description        text,
    parent_id          bigint REFERENCES departments(id) ON DELETE SET NULL,
    manager_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    handbook_document_id bigint,                                  -- FK added in 035_documents.sql
    -- The three standing departments every tenant always has (seeded in 055, protected by
    -- a trigger there): HR tracks people and agents, Accounting owns the books and AI token
    -- spend, Audit runs the evals. Renameable, never deletable.
    is_system          boolean NOT NULL DEFAULT false,
    system_key         text UNIQUE CHECK (system_key IN ('hr', 'accounting', 'audit')),
    home_location_id   bigint,                                    -- FK added in 043 (the office/VM it works in)
    monthly_budget_amount numeric(14,2) CHECK (monthly_budget_amount >= 0),
    budget_currency    char(3) NOT NULL DEFAULT 'USD',
    archived_at        timestamptz,
    CONSTRAINT departments_system_key_flag CHECK ((system_key IS NOT NULL) = is_system),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX departments_manager_idx ON departments (manager_member_id);
ALTER TABLE invitations
    ADD CONSTRAINT invitations_department_fk
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL;
CREATE INDEX invitations_department_idx ON invitations (department_id);

CREATE TABLE department_members (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    department_id  bigint NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    member_id      bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    is_primary     boolean NOT NULL DEFAULT false,
    -- Which of this member's departments they administer. Only meaningful for a
    -- dept_admin; the department's named manager counts as an admin of it as well.
    is_admin       boolean NOT NULL DEFAULT false,
    joined_at      timestamptz NOT NULL DEFAULT now(),
    left_at        timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX department_members_live_idx ON department_members (department_id, member_id)
    WHERE left_at IS NULL;
CREATE UNIQUE INDEX department_members_primary_idx ON department_members (member_id)
    WHERE is_primary AND left_at IS NULL;
CREATE INDEX department_members_member_idx ON department_members (member_id) WHERE left_at IS NULL;

-- --------------------------------------------------------------------------
-- Module grants. Owner/Manager implicitly have every module. Staff see a granted module
-- within their departments. External members see a granted module whole — this is how an
-- accountant sees all invoices, payments and expenses (read access only). A super_admin
-- implicitly holds every module. A dept_admin needs no grant to reach records IN the
-- departments they administer (app_can_see handles that), but outside them they are an
-- ordinary user and need grants like anyone else -- otherwise every record nobody gave a
-- department to would be open to every dept_admin.
-- --------------------------------------------------------------------------
CREATE TABLE module_grants (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    module      text NOT NULL CHECK (module IN (
                    'contacts', 'sales', 'expenses', 'projects', 'scheduling', 'tickets',
                    'documents', 'time', 'content', 'hr', 'locations', 'applications',
                    'approvals', 'ledger', 'evals',
                    -- back-office modules (056-062)
                    'books', 'inbox', 'people', 'inventory', 'signatures', 'portal', 'reports')),
    access      text NOT NULL DEFAULT 'write' CHECK (access IN ('read', 'write')),
    granted_by  bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (member_id, module)
);

-- --------------------------------------------------------------------------
-- Record shares — how an External member sees individual records (A6, C16, DC5);
-- module grants (above) are the other way.
-- Sharing an organization exposes that organization's invoices, quotes, projects and
-- tickets to the member (the views apply it); other entity types share one record.
-- --------------------------------------------------------------------------
CREATE TABLE record_shares (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type  text   NOT NULL,                     -- 'organization', 'document', 'project', ...
    entity_id    bigint NOT NULL,
    member_id    bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    access       text   NOT NULL DEFAULT 'read' CHECK (access IN ('read', 'comment')),
    shared_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    expires_at   timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX record_shares_live_idx ON record_shares (entity_type, entity_id, member_id)
    WHERE revoked_at IS NULL;
CREATE INDEX record_shares_member_idx ON record_shares (member_id) WHERE revoked_at IS NULL;

-- --------------------------------------------------------------------------
-- Tags (any record) — C3, SM10
-- --------------------------------------------------------------------------
CREATE TABLE tags (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        citext NOT NULL UNIQUE,
    color       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE taggings (
    tag_id       bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    entity_type  text   NOT NULL,
    entity_id    bigint NOT NULL,
    created_by   bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tag_id, entity_type, entity_id)
);
CREATE INDEX taggings_entity_idx ON taggings (entity_type, entity_id);

-- --------------------------------------------------------------------------
-- Comments on any record (projects, tasks, deals, documents, content)
-- --------------------------------------------------------------------------
CREATE TABLE record_comments (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type       text   NOT NULL,
    entity_id         bigint NOT NULL,
    author_member_id  bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    body              text   NOT NULL,                  -- markdown
    deleted_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX record_comments_entity_idx ON record_comments (entity_type, entity_id, created_at);

-- --------------------------------------------------------------------------
-- Tenant secrets — provider API keys, payment and channel credentials.
-- Encrypted at rest (libsodium secretbox, key in config/.env, like TOTP secrets).
-- NEVER exposed through any mcp_* view; the read roles get nothing on this table.
-- --------------------------------------------------------------------------
CREATE TABLE tenant_secrets (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,                  -- 'anthropic-default', 'stripe-live'
    purpose      text NOT NULL CHECK (purpose IN ('model_provider', 'payment_provider',
                                                  'channel', 'email', 'application', 'other')),
    provider     text,
    ciphertext   text NOT NULL,
    key_version  integer NOT NULL DEFAULT 1,
    last4        text,                                  -- display hint only
    created_by   bigint REFERENCES members(id) ON DELETE SET NULL,
    rotated_at   timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON tenant_secrets FROM app_records_ro, app_activity_ro;

-- --------------------------------------------------------------------------
-- Document numbering (INV-00042, Q-00007, T-00123, ...)
-- --------------------------------------------------------------------------
CREATE TABLE document_sequences (
    kind        text PRIMARY KEY CHECK (kind IN ('quote', 'invoice', 'credit_note', 'ticket',
                                                 'project', 'expense', 'journal_entry',
                                                 'purchase_order', 'pay_run')),
    prefix      text NOT NULL,
    next_value  bigint NOT NULL DEFAULT 1 CHECK (next_value > 0),
    padding     smallint NOT NULL DEFAULT 5 CHECK (padding BETWEEN 1 AND 12),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Row lock via UPDATE ... RETURNING: concurrent callers serialize, no gaps on commit.
CREATE OR REPLACE FUNCTION next_document_number(p_kind text) RETURNS text
    LANGUAGE sql AS $$
    UPDATE document_sequences
       SET next_value = next_value + 1, updated_at = now()
     WHERE kind = p_kind
    RETURNING prefix || lpad((next_value - 1)::text, padding, '0');
$$;
REVOKE ALL ON FUNCTION next_document_number(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION next_document_number(text) TO app_rw;

-- --------------------------------------------------------------------------
-- Visibility helpers (the business RLS key)
-- --------------------------------------------------------------------------
-- The request context still carries only app.member_id (set by the PHP app from the
-- session, and by the MCP servers from the token). The business role, departments,
-- grants and shares are looked up from that id, so no server change is needed and a
-- role change takes effect on the next query. SECURITY DEFINER because the read roles
-- have no base-table access.

CREATE OR REPLACE FUNCTION app_business_role() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(
        (SELECT business_role FROM members
          WHERE id = app_current_member_id() AND status = 'active'),
        'anon');
$$;

CREATE OR REPLACE FUNCTION app_is_super_admin() RETURNS boolean
    LANGUAGE sql STABLE AS $$ SELECT app_business_role() = 'super_admin' $$;

CREATE OR REPLACE FUNCTION app_is_dept_admin() RETURNS boolean
    LANGUAGE sql STABLE AS $$ SELECT app_business_role() = 'dept_admin' $$;

-- Any administrator. Use this only where the rows are already scoped some other way
-- (the caller's own records, a department column the view filters on); where a row is
-- tenant-wide, ask app_is_super_admin() instead.
CREATE OR REPLACE FUNCTION app_is_admin() RETURNS boolean
    LANGUAGE sql STABLE AS $$ SELECT app_business_role() IN ('super_admin', 'dept_admin') $$;

CREATE OR REPLACE FUNCTION app_is_external() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE((SELECT is_external FROM members
                      WHERE id = app_current_member_id() AND status = 'active'), false);
$$;

CREATE OR REPLACE FUNCTION app_member_kind() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT member_kind FROM members WHERE id = app_current_member_id() AND status = 'active';
$$;

-- Signed in and not external (user, dept_admin or super_admin -- human or agent).
CREATE OR REPLACE FUNCTION app_is_insider() RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT app_business_role() <> 'anon' AND NOT app_is_external();
$$;

-- The departments this member administers: the ones they are flagged admin of, plus any
-- they are the named manager of. A super_admin administers every department.
CREATE OR REPLACE FUNCTION app_admin_department_ids() RETURNS bigint[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT CASE
        WHEN app_is_super_admin() THEN
            COALESCE((SELECT array_agg(id) FROM departments WHERE archived_at IS NULL), '{}')
        WHEN app_is_dept_admin() THEN
            COALESCE((SELECT array_agg(DISTINCT d.id)
                        FROM departments d
                        LEFT JOIN department_members dm
                               ON dm.department_id = d.id
                              AND dm.member_id = app_current_member_id()
                              AND dm.left_at IS NULL
                       WHERE d.archived_at IS NULL
                         AND (d.manager_member_id = app_current_member_id()
                              OR dm.is_admin)), '{}')
        ELSE '{}'
    END;
$$;

-- Do I administer this department? (A record with no department is nobody's to administer:
-- it belongs to the whole business, so only a super_admin administers it.)
CREATE OR REPLACE FUNCTION app_is_admin_of(p_department_id bigint) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT app_is_super_admin()
        OR (p_department_id IS NOT NULL AND p_department_id = ANY (app_admin_department_ids()));
$$;

-- Do I administer this person? True for a super_admin, and for a dept_admin when the member
-- belongs to one of the departments they administer. This is the rule behind "a dept-admin
-- administers their departments" for everything about people: grants, tokens, invitations,
-- contact details, time and leave.
CREATE OR REPLACE FUNCTION app_can_admin_member(p_member_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_is_super_admin()
        OR p_member_id = app_current_member_id()
        OR (app_is_dept_admin() AND EXISTS (
                SELECT 1 FROM department_members dm
                 WHERE dm.member_id = p_member_id
                   AND dm.left_at IS NULL
                   AND dm.department_id = ANY (app_admin_department_ids())));
$$;

CREATE OR REPLACE FUNCTION app_my_department_ids() RETURNS bigint[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(array_agg(department_id), '{}')
      FROM department_members
     WHERE member_id = app_current_member_id() AND left_at IS NULL;
$$;

CREATE OR REPLACE FUNCTION app_has_module(p_module text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT app_is_super_admin()
        OR EXISTS (SELECT 1 FROM module_grants
                    WHERE member_id = app_current_member_id() AND module = p_module);
$$;

CREATE OR REPLACE FUNCTION app_is_shared_with_me(p_entity_type text, p_entity_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM record_shares
         WHERE member_id = app_current_member_id()
           AND entity_type = p_entity_type AND entity_id = p_entity_id
           AND revoked_at IS NULL
           AND (expires_at IS NULL OR expires_at > now()));
$$;

-- The one visibility rule for department-scoped business records:
--   * super_admin: everything.
--   * dept_admin: everything in the departments they administer; elsewhere they fall through
--     to the ordinary user rule, so administering Sales does not reveal Finance.
--   * user: module granted AND (record has no department, or it is one of mine), or I own it.
--   * external: module granted (the accountant), or shared directly, or via the record's
--     organization.
--   * anyone: records they own.
CREATE OR REPLACE FUNCTION app_can_see(
    p_module          text,
    p_owner_member_id bigint,
    p_department_id   bigint,
    p_entity_type     text,
    p_entity_id       bigint,
    p_organization_id bigint DEFAULT NULL
) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN app_current_member_id() IS NULL THEN false
        WHEN p_owner_member_id IS NOT NULL AND p_owner_member_id = app_current_member_id() THEN true
        WHEN app_is_super_admin() THEN true
        WHEN app_is_external() THEN
             app_has_module(p_module)
             OR app_is_shared_with_me(p_entity_type, p_entity_id)
             OR (p_organization_id IS NOT NULL
                 AND app_is_shared_with_me('organization', p_organization_id))
        WHEN app_is_dept_admin()
             AND p_department_id IS NOT NULL
             AND p_department_id = ANY (app_admin_department_ids()) THEN true
        ELSE
             app_has_module(p_module)
             AND (p_department_id IS NULL OR p_department_id = ANY (app_my_department_ids()))
    END;
$$;

GRANT EXECUTE ON FUNCTION
    app_business_role(), app_is_super_admin(), app_is_dept_admin(), app_is_admin(),
    app_is_external(), app_member_kind(), app_is_insider(),
    app_my_department_ids(), app_admin_department_ids(), app_is_admin_of(bigint),
    app_can_admin_member(bigint), app_has_module(text), app_is_shared_with_me(text, bigint),
    app_can_see(text, bigint, bigint, text, bigint, bigint)
TO app_rw, app_records_ro, app_activity_ro;

COMMIT;
