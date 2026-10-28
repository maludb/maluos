-- 104_memory_endpoint.sql
-- Stage H4 (docs/build-specs/agent-memory.md): shared memory on MaluDB.
--
-- 1. The Memory MCP server joins the uniform registry (db/075) as an endpoint of the platform
--    application, so its tools can be granted to agents like any other. It is registered HERE, in
--    the migration that ships the server: db/075's own rule is that an endpoint row for a server
--    that does not exist is a lie the tool-grant picker would faithfully offer.
-- 2. Two approval policies (the second is item 3 below). An agent may remember anything for ITSELF; what it writes into a
--    department's or the organisation's memory is read by every colleague's next run as something
--    the business knows. A person reads it first.

BEGIN;

INSERT INTO application_endpoints
    (application_id, name, kind, url, auth_kind, agent_reachable, mcp_surface_version, notes)
SELECT a.id, 'Memory MCP', 'mcp', 'http://127.0.0.1:8814/mcp', 'bearer', true, '1.0',
       'Read-only shared memory over MaluDB: recall, core_memory, session_search. Holds the tenant''s '
       'MaluDB token and resolves each caller''s scope (self, its departments, the organisation); no '
       'agent or person holds that token. Writes are manifest actions through PHP. Localhost only.'
  FROM applications a
 WHERE a.app_key = 'platform'
   AND NOT EXISTS (SELECT 1 FROM application_endpoints e WHERE e.application_id = a.id AND e.name = 'Memory MCP');

INSERT INTO approval_policies (name, category, action_pattern, applies_to, expires_after_hours, active)
SELECT 'Agents: writing shared memory', 'other', 'memory.remember_shared', 'agents', 72, true
 WHERE NOT EXISTS (SELECT 1 FROM approval_policies WHERE action_pattern = 'memory.remember_shared');

-- 3. An agent's CORE memory is rendered into its own system prompt on every run. A poisoned
--    document that talked an agent into "remembering" an instruction there would persist across
--    runs; so an agent changing its own standing memory is read by a person first too. (Ordinary
--    private memory is only ever returned by recall, as information — that stays free.)
INSERT INTO approval_policies (name, category, action_pattern, applies_to, expires_after_hours, active)
SELECT 'Agents: changing their own core memory', 'other', 'memory.core_set', 'agents', 72, true
 WHERE NOT EXISTS (SELECT 1 FROM approval_policies WHERE action_pattern = 'memory.core_set');

COMMIT;
