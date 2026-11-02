-- 193: the Memory MCP published to desks (maluos: docs/phase13-slice4b-memory.md, decisions 6 and 7). The MCP servers
-- resolve a bearer token with mcp_resolve_token(), which maps any live non-node token to its member: a desk's token
-- (db/187) reads as its owner, which is right for records and activity but lets the Memory MCP answer a desk from the
-- owner's whole department set, outside the estate memory policy of db/192. The resolver now also says what the token
-- is (its scope: mcp, api, application, desk) and which location it belongs to, so the Memory MCP can answer a desk's
-- recall by relaying to the desks memory query, under the policy. A node token still never resolves.
--
-- Additive: the resolver's answer gains two columns (its callers select by name).
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/193_memory_mcp_desks.sql
BEGIN;

DROP FUNCTION IF EXISTS mcp_resolve_token(text);
CREATE FUNCTION mcp_resolve_token(p_hash text)
RETURNS TABLE(member_id bigint, member_role text, token_scope text, location_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE mcp_access_tokens
       SET last_used_at = now()
     WHERE token_hash = p_hash AND revoked_at IS NULL AND scope <> 'node'
       AND (expires_at IS NULL OR expires_at > now());

    RETURN QUERY
        SELECT m.id, m.role, t.scope, t.location_id
        FROM mcp_access_tokens t
        JOIN members m ON m.id = t.member_id
        WHERE t.token_hash = p_hash AND t.revoked_at IS NULL AND t.scope <> 'node'
          AND (t.expires_at IS NULL OR t.expires_at > now())
          AND m.status = 'active';
END$$;
COMMENT ON FUNCTION mcp_resolve_token(text) IS
    'The MCP servers'' token resolver: a live non-node token to its member, its role, its scope and its location (a desk token names its desk). db/193.';
REVOKE ALL ON FUNCTION mcp_resolve_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mcp_resolve_token(text) TO app_records_ro, app_activity_ro;

COMMIT;
