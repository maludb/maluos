-- 093_voice_agent_phone.sql
-- The number a voice agent answers on, so an inbound call can find it.
--
-- Decided 2026-09-18 (owner, "prompt webhook only"). RetellAI's inbound-call webhook tells us
-- the number that was dialled (`to_number`) and expects an answer within 10 seconds; that is
-- the whole of the identification problem, so one E.164 number on the agent solves it. Nothing
-- about Retell itself is modelled here: no credentials (they live in config/.env), no call
-- records, no provider ids. Those belong to whatever the call-integration slice turns out to
-- need, and inventing them now would be guessing.
--
-- Numbering: 092 is left free for another session's avatar fold, which has to sit on db/090's
-- mcp_agents.

BEGIN;

ALTER TABLE agent_profiles ADD COLUMN phone_number text;

-- One number answers as one agent: two agents on a number is not a routing choice we could
-- resolve at call time, so the database refuses it rather than picking one.
CREATE UNIQUE INDEX agent_profiles_phone_idx ON agent_profiles (phone_number)
    WHERE phone_number IS NOT NULL;

-- E.164, because that is what the provider sends: a leading + and up to fifteen digits. Stored
-- exactly as dialled so the webhook can match on equality rather than normalising at call time.
ALTER TABLE agent_profiles ADD CONSTRAINT agent_phone_is_e164 CHECK (
    phone_number IS NULL OR phone_number ~ '^\+[1-9][0-9]{6,14}$'
);

-- Only a voice agent answers calls. An orchestrator with a phone number would be a promise the
-- platform does not keep.
ALTER TABLE agent_profiles ADD CONSTRAINT agent_phone_is_voice_only CHECK (
    phone_number IS NULL OR agent_kind = 'voice'
);

COMMENT ON COLUMN agent_profiles.phone_number IS
    'E.164 number this voice agent answers, e.g. "+14155550123". Matched against the inbound '
    'webhook''s to_number to decide whose system prompt the call is answered with. NULL for '
    'every other kind of agent, and for a voice agent whose number is not connected yet.';

-- --------------------------------------------------------------------------
-- The view carries it: "which number does this agent answer?" is an ordinary question, and
-- the column is appended so the view's grants and the rest of its shape survive.
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW mcp_agents AS
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
    (SELECT count(*) FROM agent_subagents s
      WHERE s.orchestrator_member_id = ap.member_id AND s.removed_at IS NULL) AS subagent_count,
    (SELECT count(*) FROM agent_subagents s
      WHERE s.subagent_member_id = ap.member_id AND s.removed_at IS NULL) AS orchestrator_count,
    ap.phone_number
   FROM agent_profiles ap
   JOIN members m ON m.id = ap.member_id
   JOIN members mm ON mm.id = ap.manager_member_id
   JOIN model_registry mr ON mr.id = ap.model_id
  WHERE app_is_insider();

COMMIT;
