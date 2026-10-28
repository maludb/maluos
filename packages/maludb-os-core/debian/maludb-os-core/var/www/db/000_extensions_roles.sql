-- 000_extensions_roles.sql
-- MaluDB OS — extensions, database roles, and the RLS request context.
-- PostgreSQL 17. Run first; every later file depends on the roles and helpers here.
--
-- Two-memory architecture (see docs/plan.md §6 and the mcp-servers skill):
--   * app_rw          — the PHP application (trusted tier). Full DML on base tables.
--                       It sets app.member_id / app.role per request and enforces
--                       per-member visibility in its own query WHERE clauses; it is the
--                       tier that produces the activity log.
--   * app_records_ro  — the record-memory MCP server. NO base-table access; reads only
--                       the mcp_* views (012), which embed §3.2 visibility.
--   * app_activity_ro — the activity-memory MCP server. NO base-table access; reads only
--                       the mcp_activity_* views (012).
--
-- BYPASSRLS is never granted to the read roles. Because those roles can see only the
-- visibility-encoding views, no MCP tool — including the arbitrary-SELECT search tools —
-- can leak past a member's row-level rights.

BEGIN;

-- --------------------------------------------------------------------------
-- Extensions
-- --------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email column type
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram indexes for fuzzy member/resource search

-- MaluDB activity-memory extension. MaluDB ships as a set of PostgreSQL extensions;
-- the ingestion wiring lives in 010_activity_log.sql. Guarded so this file still runs
-- on a plain PostgreSQL 17 host during early development (a warning, not a failure).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS maludb;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'maludb extension not available (%) — activity ingestion wiring in 010 will be a no-op until it is', SQLERRM;
END$$;

-- --------------------------------------------------------------------------
-- Roles
-- --------------------------------------------------------------------------
-- Passwords are set per-environment out of band (ALTER ROLE ... PASSWORD / .pgpass),
-- never committed. NOLOGIN group roles could be used, but the app + MCP servers each
-- connect directly, so these are LOGIN roles.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_records_ro') THEN
        CREATE ROLE app_records_ro LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_activity_ro') THEN
        CREATE ROLE app_activity_ro LOGIN;
    END IF;
END$$;

-- Schema. Everything lives in the default `public` schema for simplicity; the roles'
-- grants are what scope access, not schema separation.
GRANT USAGE ON SCHEMA public TO app_rw, app_records_ro, app_activity_ro;

-- Default privileges: the migration owner grants full DML on base tables to app_rw
-- only. The read MCP roles are deliberately given NOTHING on base tables — they read
-- the world exclusively through the visibility-encoding `mcp_*` views in 012_views.sql
-- (security-definer, embedding the §3.2 rules keyed on app.member_id / app.role). Because
-- their only readable objects are those views, even the arbitrary-SELECT search tools
-- (records_search / activity_search) cannot leak past a member's row-level rights.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rw;

-- --------------------------------------------------------------------------
-- Request context (the RLS key)
-- --------------------------------------------------------------------------
-- Every connection, on every request, declares who it is acting as:
--     SELECT set_config('app.member_id', '42',        true);   -- transaction-scoped
--     SELECT set_config('app.role',      'organizer',  true);
-- The PHP app sets these from $_SESSION after auth; the record MCP server sets them
-- from the caller's personal token. When unset (a raw psql session), the helpers
-- below return NULL / 'anon' and RLS denies everything a member would need to own.

CREATE OR REPLACE FUNCTION app_current_member_id() RETURNS bigint
    LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.member_id', true), '')::bigint $$;

CREATE OR REPLACE FUNCTION app_current_role() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.role', true), ''), 'anon') $$;

CREATE OR REPLACE FUNCTION app_is_organizer() RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT app_current_role() = 'organizer' $$;

-- Let the read roles read the helpers (they are SECURITY INVOKER; they only read GUCs).
GRANT EXECUTE ON FUNCTION app_current_member_id(), app_current_role(), app_is_organizer()
    TO app_rw, app_records_ro, app_activity_ro;

COMMIT;
