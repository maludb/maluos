-- 090_agent_profile_photos.sql
-- An agent's photo becomes a file we hold, not a link to somebody else's server.
--
-- Decided 2026-09-18 (owner). db/070 gave agent_profiles a `profile_pic_url`, with the build
-- spec's own note that a URL was a stand-in "rather than an upload, because this server has no
-- file storage yet". That stand-in has three problems in a business platform: the picture is
-- only as durable as a site nobody here controls, it leaks a request to that site from every
-- screen the agent appears on, and it cannot be exported with the tenant's data.
--
-- So the photo is uploaded and stored under the tenant's storage root, exactly as db/035
-- describes for documents ("files live on disk under the tenant's storage root; the database
-- holds metadata"). This is the first use of that root, so it establishes the shape: the row
-- carries the relative path, the media type, the size and the sha256, and the bytes sit
-- outside the document root and are served only through a gated PHP endpoint.
--
-- Numbering: 077-079 are reserved by another session for review fixes and 080+ by a third for
-- phase 3, so this slice takes 090 and 091 to avoid a collision. The gap is deliberate.

BEGIN;

-- The view reads the column being dropped, so it goes first and is rebuilt below.
DROP VIEW mcp_agents;

ALTER TABLE agent_profiles
    DROP COLUMN profile_pic_url,
    ADD COLUMN profile_photo_path       text,
    ADD COLUMN profile_photo_mime       text,
    ADD COLUMN profile_photo_size_bytes bigint CHECK (profile_photo_size_bytes >= 0),
    ADD COLUMN profile_photo_sha256     text,
    ADD COLUMN profile_photo_updated_at timestamptz;

-- A photo is all of its facts or none of them: a path with no media type cannot be served,
-- and a media type with no path names nothing.
ALTER TABLE agent_profiles ADD CONSTRAINT agent_profile_photo_complete CHECK (
    num_nulls(profile_photo_path, profile_photo_mime, profile_photo_sha256,
              profile_photo_size_bytes, profile_photo_updated_at) IN (0, 5)
);

-- Only what a browser will render inline without a plugin, and what the upload path verifies
-- by reading the file's own bytes rather than trusting the client.
ALTER TABLE agent_profiles ADD CONSTRAINT agent_profile_photo_mime CHECK (
    profile_photo_mime IS NULL
    OR profile_photo_mime IN ('image/jpeg', 'image/png', 'image/webp', 'image/gif')
);

COMMENT ON COLUMN agent_profiles.profile_photo_path IS
    'Path relative to the tenant storage root (config STORAGE_ROOT, default <app>/storage), '
    'e.g. "agent-photos/27/3f9a….jpg". The bytes live outside the document root and are served '
    'only by /agents/photo.php, which applies the same visibility rule as the agent record.';
COMMENT ON COLUMN agent_profiles.profile_photo_sha256 IS
    'Of the stored bytes: names the file, serves as the ETag, and makes a re-upload of the same '
    'picture recognisable.';

-- --------------------------------------------------------------------------
-- The view keeps offering a URL, because that is what a reader wants: the app-relative
-- address that serves the photo, rather than a storage path no client can fetch.
-- --------------------------------------------------------------------------
CREATE VIEW mcp_agents AS
 SELECT ap.member_id AS agent_member_id,
    m.display_name,
    m.job_title,
    ap.status,
    ap.agent_kind,
    ap.is_office_manager,
    ap.description,
    ap.role_key,
    CASE WHEN ap.profile_photo_path IS NOT NULL
         THEN '/agents/photo.php?agent=' || ap.member_id::text END AS profile_pic_url,
    (ap.profile_photo_path IS NOT NULL) AS has_profile_photo,
    ap.profile_photo_mime,
    ap.profile_photo_size_bytes,
    ap.profile_photo_sha256,
    ap.profile_photo_updated_at,
    ap.manager_member_id,
    mm.display_name AS manager_name,
    ap.home_location_id,
    mr.model_key,
    mr.harness,
        CASE WHEN app_can_see_agent(ap.member_id) THEN ap.current_config_version_id
             ELSE NULL::bigint END AS current_config_version_id,
        CASE WHEN app_can_see_agent(ap.member_id) THEN ap.monthly_budget_amount
             ELSE NULL::numeric END AS monthly_budget_amount,
    ap.budget_currency,
    ap.hired_at,
    ap.suspended_at,
    ap.offboarded_at,
    -- How many subagents this orchestrator manages, and how many rosters this subagent is on.
    -- Both are zero for the other kind, which is the honest answer rather than NULL.
    (SELECT count(*) FROM agent_subagents s
      WHERE s.orchestrator_member_id = ap.member_id AND s.removed_at IS NULL) AS subagent_count,
    (SELECT count(*) FROM agent_subagents s
      WHERE s.subagent_member_id = ap.member_id AND s.removed_at IS NULL) AS orchestrator_count
   FROM agent_profiles ap
   JOIN members m ON m.id = ap.member_id
   JOIN members mm ON mm.id = ap.manager_member_id
   JOIN model_registry mr ON mr.id = ap.model_id
  WHERE app_is_insider();

GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_agents TO app_rw;
GRANT SELECT ON mcp_agents TO app_records_ro;

COMMENT ON VIEW mcp_agents IS
    'The agents we employ. profile_pic_url is derived: the address that serves the stored '
    'photo, or NULL when there is none (db/090 replaced the external URL with an upload).';

COMMIT;
