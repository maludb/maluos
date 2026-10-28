-- 015_mcp_member_role.sql
-- Lets the read MCP servers accept the assistant's action token as an alternative to a
-- personal MCP access token: the server verifies the action token's HMAC locally, then
-- calls this SECURITY DEFINER function to get the member's role (the read roles cannot read
-- the members table directly). Returns NULL for a missing/suspended member.

BEGIN;

CREATE OR REPLACE FUNCTION mcp_member_role(p_member_id bigint)
RETURNS text
LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
    SELECT role FROM members WHERE id = p_member_id AND status = 'active';
$$;

REVOKE ALL ON FUNCTION mcp_member_role(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mcp_member_role(bigint) TO app_records_ro, app_activity_ro;

COMMIT;
