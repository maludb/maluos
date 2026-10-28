-- 075_uniform_mcp_registry.sql
-- One registry for every MCP server an agent can use — including our own.
--
-- Decided 2026-09-18. The estate already models technical assets properly: `applications` has
-- `database` and `storage` categories, an owning department, a location, criticality, health and
-- what it costs; `application_endpoints` carries `kind = 'mcp'`, an `auth_kind`, a `secret_id`
-- holding only a REFERENCE, an `agent_reachable` flag and `mcp_surface_version`; and
-- `application_access` grants to a member or a department with read/write/admin, expiry and
-- revocation. Nothing about that needed inventing.
--
-- What blocked it: `agent_tool_grants.server` was a hard-coded CHECK over
-- ('records','activity','actions','desk'). However well a new asset was registered — a data
-- lake, a warehouse, a vector store — no agent could be granted a tool on it, because the grant
-- had nowhere to point. The inventory and the thing agents actually use were two systems.
--
-- So the grant now references an endpoint, and OUR OWN servers are registered like everyone
-- else's. The alternative (keep the four, add an optional endpoint reference) would have left
-- two ways to name a server, which is the "two sources of truth" mistake this project has
-- already paid for three times.
--
-- Safe to do now: agent_tool_grants holds zero rows, so there is nothing to convert.

BEGIN;

-- --------------------------------------------------------------------------
-- 1. Our own MCP servers, as endpoints of the platform application
-- --------------------------------------------------------------------------
INSERT INTO application_endpoints
    (application_id, name, kind, url, auth_kind, agent_reachable, mcp_surface_version, notes)
SELECT a.id, v.name, 'mcp', v.url, 'bearer', true, v.ver, v.notes
  FROM applications a,
       (VALUES
         ('Records MCP', 'http://localhost/mcp/records', '1.0',
          'Read-only record memory over PostgreSQL. Reverse-proxied by Apache to 127.0.0.1:8811.'),
         ('Activity MCP', 'http://localhost/mcp/activity', '1.0',
          'Read-only activity memory over MaluDB. Reverse-proxied by Apache to 127.0.0.1:8812.'),
         ('Actions MCP', 'http://127.0.0.1:8813/mcp', '1.0',
          'The action surface: every built action in the manifest. Signed action tokens, not '
          'bearer MCP tokens. Not Apache-proxied today — localhost only.')
       ) AS v(name, url, ver, notes)
 WHERE a.app_key = 'platform'
   AND NOT EXISTS (SELECT 1 FROM application_endpoints e
                    WHERE e.application_id = a.id AND e.name = v.name);

-- The desk MCP surface is deliberately NOT registered: it arrives with the desktop companion
-- (phase 6). An endpoint row claiming an active server that does not exist would be a lie the
-- agent-tool picker would faithfully offer.

-- --------------------------------------------------------------------------
-- 2. The technical assets that are here by default
-- --------------------------------------------------------------------------
INSERT INTO applications
    (name, app_key, category, description, vendor, is_self_hosted, is_builtin,
     location_id, criticality, status, health_status)
SELECT v.name, v.app_key, v.category, v.description, v.vendor, true, false,
       (SELECT id FROM locations WHERE kind = 'office' ORDER BY id LIMIT 1),
       v.criticality, 'active', 'unknown'
  FROM (VALUES
     ('PostgreSQL 17', 'postgres', 'database',
      'The record memory: every business record this platform keeps. Agents reach it through '
      'the Records MCP server, never directly.', 'PostgreSQL', 'critical'),
     ('MaluDB memory', 'maludb', 'database',
      'The activity memory: what happened, as episodes. Agents reach it through the Activity '
      'MCP server. Activity memory cannot be backfilled.', 'MaluDB', 'critical')
   ) AS v(name, app_key, category, description, vendor, criticality)
 WHERE NOT EXISTS (SELECT 1 FROM applications a WHERE a.app_key = v.app_key);

-- Their own endpoints. agent_reachable = false on purpose: an agent does not open a database
-- connection, it asks an MCP server. Recording the endpoint is how we know what the MCP server
-- is standing in front of, and where its credential lives once tenant_secrets has a writer.
INSERT INTO application_endpoints
    (application_id, name, kind, url, auth_kind, agent_reachable, notes)
SELECT a.id, v.name, v.kind, v.url, v.auth, false, v.notes
  FROM applications a,
       (VALUES
         ('postgres', 'Primary database', 'database', 'postgresql://localhost:5432/' || current_database(),
          'basic', 'Roles: app_rw (the app), app_records_ro and app_activity_ro (the MCP read '
          'servers, views only, no base-table grants).'),
         ('maludb', 'MaluDB API', 'http_api', 'http://localhost:8000',
          'bearer', 'Tenant memory database maludb_os_memory; token minted by POST /v1/tokens.')
       ) AS v(app_key, name, kind, url, auth, notes)
 WHERE a.app_key = v.app_key
   AND NOT EXISTS (SELECT 1 FROM application_endpoints e
                    WHERE e.application_id = a.id AND e.name = v.name);

-- --------------------------------------------------------------------------
-- 3. A tool grant points at a registered endpoint
-- --------------------------------------------------------------------------
ALTER TABLE agent_tool_grants
    ADD COLUMN application_endpoint_id bigint REFERENCES application_endpoints(id) ON DELETE RESTRICT;

-- Nothing to convert (zero rows), so the column goes straight to NOT NULL and the old
-- vocabulary goes away rather than lingering as a second way to say the same thing.
ALTER TABLE agent_tool_grants DROP CONSTRAINT agent_tool_grants_server_check;
-- The read view selects `server`, so it goes before the column does; it is rebuilt in step 4
-- against the endpoint instead.
DROP VIEW mcp_agent_tool_grants;
ALTER TABLE agent_tool_grants DROP COLUMN server;
ALTER TABLE agent_tool_grants ALTER COLUMN application_endpoint_id SET NOT NULL;

DROP INDEX IF EXISTS agent_tool_grants_live_idx;
CREATE UNIQUE INDEX agent_tool_grants_live_idx
    ON agent_tool_grants (agent_member_id, application_endpoint_id, tool_name)
    WHERE revoked_at IS NULL;

COMMENT ON COLUMN agent_tool_grants.application_endpoint_id IS
    'The registered MCP endpoint this tool lives on. Any application in the inventory may '
    'expose one — ours and a future data lake alike — so granting an agent a new capability is '
    'registration plus a grant, never a migration.';

-- An agent can only be granted a tool on something that is an MCP server, is meant for agents,
-- and is still live. The picker should never offer otherwise, and the database should not trust
-- that it doesn't.
CREATE OR REPLACE FUNCTION agent_tool_grant_endpoint_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE k text; reachable boolean; st text; nm text;
BEGIN
    SELECT kind, agent_reachable, status, name
      INTO k, reachable, st, nm
      FROM application_endpoints WHERE id = NEW.application_endpoint_id;
    IF k <> 'mcp' THEN
        RAISE EXCEPTION '% is a % endpoint, not an MCP server — an agent is granted MCP tools',
            coalesce(nm, 'That endpoint'), coalesce(k, 'unknown');
    END IF;
    IF NOT reachable THEN
        RAISE EXCEPTION '% is not marked agent-reachable', coalesce(nm, 'That endpoint');
    END IF;
    IF st <> 'active' THEN
        RAISE EXCEPTION '% is %, so no new tool can be granted on it', coalesce(nm, 'That endpoint'), st;
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER agent_tool_grants_endpoint_valid
    BEFORE INSERT OR UPDATE OF application_endpoint_id ON agent_tool_grants
    FOR EACH ROW EXECUTE FUNCTION agent_tool_grant_endpoint_check();

-- --------------------------------------------------------------------------
-- 4. The view follows the grant (dropped above, before its column went)
-- --------------------------------------------------------------------------
CREATE VIEW mcp_agent_tool_grants AS
 SELECT g.agent_member_id,
        g.application_endpoint_id,
        e.name AS endpoint_name,
        e.url  AS endpoint_url,
        e.mcp_surface_version,
        a.id   AS application_id,
        a.name AS application_name,
        a.category AS application_category,
        g.tool_name,
        g.constraints,
        g.granted_by,
        g.created_at
   FROM agent_tool_grants g
   JOIN application_endpoints e ON e.id = g.application_endpoint_id
   JOIN applications a ON a.id = e.application_id
  WHERE g.revoked_at IS NULL
    AND app_is_insider();

ALTER VIEW mcp_agent_tool_grants SET (security_barrier = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agent_tool_grants TO app_rw;
GRANT SELECT ON mcp_agent_tool_grants TO app_records_ro;

COMMIT;
