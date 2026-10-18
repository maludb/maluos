-- 079_avatar_fallback.sql
--
-- *** WRITTEN, NOT APPLIED — held for coordination. db/090 (another session, same day) is
--     actively reshaping agent photos and mcp_agents; applying a view change underneath that
--     would clobber it. See the note at the end. ***
--
-- The gap this closes: db/090 made an agent's photo a real uploaded file under the tenant
-- storage root, served as /agents/photo.php?agent=N, and mcp_agents derives profile_pic_url
-- from it — NULL when nothing has been uploaded. That is right for a photo. It leaves two
-- things unmet:
--
--   1. The owner's requirement that agents ALL have avatars. An agent hired a minute ago has no
--      photo, so today it has no face at all.
--   2. Humans have no avatar of any kind, and the APEX org graph puts a human at the CENTRE.
--
-- So this adds a fallback, not a second store. An uploaded photo always wins; where there is
-- none, a deterministic avatar from a shipped set stands in. Nothing is stored, nothing is
-- duplicated, and the API never has to return null.
--
-- The set is html/assets/img/avatars/avatar-01.svg .. avatar-12.svg — geometric rather than
-- photographic. Replacing them with real artwork is dropping files at those paths.

BEGIN;

CREATE OR REPLACE FUNCTION default_avatar_url(p_member_id bigint)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT '/assets/img/avatars/avatar-'
        || lpad((((p_member_id - 1) % 12) + 1)::text, 2, '0') || '.svg';
$$;

COMMENT ON FUNCTION default_avatar_url(bigint) IS
    'The stand-in avatar for a member with no uploaded photo. Deterministic, so the same member '
    'always looks the same, and spread across the shipped set so a department is not monochrome.';

COMMIT;

-- Deliberately NOT done here, because mcp_agents and mcp_team_directory belong to work in
-- flight in another session:
--
--   * mcp_agents.profile_pic_url should become
--       COALESCE(<the db/090 photo url>, default_avatar_url(ap.member_id))
--     leaving has_profile_photo as the honest signal of whether a real photo exists.
--   * mcp_team_directory should gain the same derived column for humans.
--
-- Both are one-line changes to a view that session owns. Agreed there rather than raced here.
