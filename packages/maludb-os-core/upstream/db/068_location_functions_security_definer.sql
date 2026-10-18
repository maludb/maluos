-- 068_location_functions_security_definer.sql
-- Fixes a defect introduced by db/067, found in review the same day.
--
-- db/067 added location_effective_control() and location_allows_resident() as plain
-- SECURITY INVOKER SQL functions that read the base `locations` table, and had mcp_locations
-- call them per row. The records MCP server connects as `app_records_ro`, which by design holds
-- SELECT on the mcp_* VIEWS and on **no base table at all** — that separation is the point of
-- the role. So the moment a query touched control / effective_control / siting / allows_agents,
-- Postgres raised:
--
--     ERROR: permission denied for table locations
--     CONTEXT: SQL function "location_effective_control" statement 1
--
-- which broke the estate tools (`estate`, `locations`, `get_location`) for every agent and MCP
-- client, while leaving the screens working — PHP connects as `app_rw`, which has table grants.
-- A view gated for one reader and broken for another is exactly the screen-versus-data split
-- this project keeps finding, arriving this time by my own hand.
--
-- The fix follows the pattern already established here: `app_has_module()` is SECURITY DEFINER
-- with a pinned search_path for precisely this reason. The alternative — granting
-- `app_records_ro` SELECT on `locations` — would be the wrong trade: it hands the read-only
-- role its first base table and erodes "agents read views, never tables", to save one keyword.
--
-- Both functions stay STABLE and read-only, take an id and return a fact the view already
-- exposes to any insider, and pin search_path so the definer right cannot be redirected.

BEGIN;

CREATE OR REPLACE FUNCTION location_effective_control(p_location_id bigint)
RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    WITH RECURSIVE chain AS (
        SELECT id, parent_location_id, control, 0 AS depth
          FROM locations WHERE id = p_location_id
        UNION ALL
        SELECT l.id, l.parent_location_id, l.control, c.depth + 1
          FROM locations l JOIN chain c ON l.id = c.parent_location_id
         WHERE c.control IS NULL AND c.depth < 10
    )
    SELECT coalesce((SELECT control FROM chain WHERE control IS NOT NULL ORDER BY depth LIMIT 1),
                    'unmanaged');
$$;

CREATE OR REPLACE FUNCTION location_allows_resident(p_location_id bigint, p_member_kind text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public' AS $$
    SELECT CASE
        WHEN (SELECT kind FROM locations WHERE id = p_location_id) = 'building' THEN false
        WHEN p_member_kind = 'human' THEN true
        WHEN p_member_kind = 'agent'
            THEN location_effective_control(p_location_id) = 'managed'
        ELSE false
    END;
$$;

-- EXECUTE is public by default; state it so a later role addition inherits the intent.
GRANT EXECUTE ON FUNCTION location_effective_control(bigint) TO app_rw, app_records_ro;
GRANT EXECUTE ON FUNCTION location_allows_resident(bigint, text) TO app_rw, app_records_ro;

COMMIT;
