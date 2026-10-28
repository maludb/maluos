-- 076_tool_grant_id_in_view.sql
-- Revoking an agent's tool grant has never worked.
--
-- Found reviewing db/075's follow-up, and it predates that migration: `mcp_agent_tool_grants`
-- has never selected the grant's own primary key. It exposed
-- (agent_member_id, server, tool_name, constraints, granted_by, created_at) before, and the
-- endpoint columns after — but never `id`. So the Tools tab's revoke button has always posted
-- `grant=0`, the lookup found nothing, and the revoke silently did not happen.
--
-- A read view that cannot identify its own rows cannot support any per-row action. Adding the
-- key is the fix; it is also worth stating as a rule, because this is the second time a view's
-- omission has quietly disabled a feature (db/073 was the first).
--
-- Nothing else changes: the view still filters revoked_at IS NULL and still hides rows from
-- non-insiders.

BEGIN;

CREATE OR REPLACE VIEW mcp_agent_tool_grants AS
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
        g.created_at,
        -- Appended rather than placed first: CREATE OR REPLACE VIEW may only add columns at the
        -- end, and a drop would take the grants with it.
        g.id AS agent_tool_grant_id
   FROM agent_tool_grants g
   JOIN application_endpoints e ON e.id = g.application_endpoint_id
   JOIN applications a ON a.id = e.application_id
  WHERE g.revoked_at IS NULL
    AND app_is_insider();

COMMIT;
