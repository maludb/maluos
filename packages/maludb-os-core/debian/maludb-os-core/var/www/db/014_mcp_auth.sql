-- 014_mcp_auth.sql
-- Token authentication for the read MCP servers. The read roles (app_records_ro,
-- app_activity_ro) have NO base-table access, so they cannot read mcp_access_tokens
-- directly. This SECURITY DEFINER function (owned by the migration superuser) resolves a
-- token hash to its member + role and stamps last_used_at, exposing nothing else. The
-- server then sets app.member_id / app.role and every mcp_* view scopes to that member.

BEGIN;

CREATE OR REPLACE FUNCTION mcp_resolve_token(p_hash text)
RETURNS TABLE(member_id bigint, member_role text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE mcp_access_tokens
       SET last_used_at = now()
     WHERE token_hash = p_hash AND revoked_at IS NULL
       AND (expires_at IS NULL OR expires_at > now());

    RETURN QUERY
        SELECT m.id, m.role
        FROM mcp_access_tokens t
        JOIN members m ON m.id = t.member_id
        WHERE t.token_hash = p_hash AND t.revoked_at IS NULL
          AND (t.expires_at IS NULL OR t.expires_at > now())
          AND m.status = 'active';
END$$;

REVOKE ALL ON FUNCTION mcp_resolve_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mcp_resolve_token(text) TO app_records_ro, app_activity_ro;

COMMIT;
