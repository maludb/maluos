-- 099_agent_tool_grant_check.sql
-- What the MCP servers ask before listing or running a tool for an agent (spec:
-- docs/build-specs/agent-runtime-hermes.md, "Tool grants are enforced before the first run").
--
-- Until now agent_tool_grants was advisory: a member-scoped token saw every tool on a server and
-- only row visibility was enforced. The read roles hold no base-table grants, so the servers
-- cannot read the grant table themselves; this SECURITY DEFINER function answers one narrow
-- question and nothing else:
--
--   {"is_agent": false}                                   -> a person: the server filters nothing
--   {"is_agent": true, "tools": {"find_contacts": {...}}} -> an agent: ONLY these tools, each with
--                                                            its constraints (e.g. {"max_amount": 500})
--
-- A grant counts only while it is live AND its endpoint is still an active, agent-reachable MCP
-- endpoint — the same rule the db/075 trigger applies when a grant is made. (098 is the skills
-- migration, still a draft until stage H5; migration numbers already have gaps.)

BEGIN;

CREATE FUNCTION mcp_agent_tool_grants_for(p_member_id bigint, p_endpoint_name text)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM members m WHERE m.id = p_member_id AND m.member_kind = 'agent')
            THEN jsonb_build_object('is_agent', false)
        ELSE jsonb_build_object(
            'is_agent', true,
            'tools', COALESCE((
                SELECT jsonb_object_agg(g.tool_name, g.constraints)
                  FROM agent_tool_grants g
                  JOIN application_endpoints e ON e.id = g.application_endpoint_id
                  JOIN applications a          ON a.id = e.application_id
                 WHERE g.agent_member_id = p_member_id
                   AND g.revoked_at IS NULL
                   AND a.app_key = 'platform'
                   AND e.name = p_endpoint_name
                   AND e.kind = 'mcp' AND e.agent_reachable AND e.status = 'active'
            ), '{}'::jsonb))
    END
$$;

REVOKE ALL ON FUNCTION mcp_agent_tool_grants_for(bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mcp_agent_tool_grants_for(bigint, text) TO app_records_ro, app_activity_ro;

COMMIT;
