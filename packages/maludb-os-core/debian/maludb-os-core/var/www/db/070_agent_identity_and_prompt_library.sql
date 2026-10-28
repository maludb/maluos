-- 070_agent_identity_and_prompt_library.sql
--
-- *** NOT YET APPLIED — this migration waits for the Agent HR slice to land, so the build and
--     the revision do not edit the same files at once. Decided 2026-09-18. ***
--
-- Two changes to how an agent is described.
--
-- 1. IDENTITY. An agent gains a description, a role key and a picture. Its *name* already
--    exists as members.display_name, its *tools* as agent_tool_grants, and its *modules* as
--    module_grants — which is member-keyed and so already works for agents exactly as it does
--    for humans. Those three are deliberately NOT duplicated here: a second source of truth for
--    what an agent may touch is how an agent ends up with two different answers to "what am I
--    allowed to do", one of which the MCP servers ignore.
--
-- 2. A PROMPT LIBRARY. Until now the system prompt lived inline in
--    agent_config_versions.job_description — fine for one agent, unmaintainable for a fleet,
--    where improving a shared instruction means editing every copy of it. Prompts become their
--    own versioned objects, and a config version points at one.
--
--    The important part: agent_config_versions KEEPS the resolved text. The pointer says which
--    library prompt and which version was used; job_description holds what the agent was
--    actually told. Editing a library prompt afterwards must never change the record of what a
--    past configuration said, because the config history is what the eval gate and the audit
--    trail both rest on — the same principle as a posted journal entry in db/056, or an issued
--    invoice's number in db/066. History is written, never rewritten.

BEGIN;

-- --------------------------------------------------------------------------
-- The prompt library
-- --------------------------------------------------------------------------
CREATE TABLE system_prompts (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prompt_key      citext NOT NULL UNIQUE,              -- 'bookkeeper'
    name            text NOT NULL,
    description     text,
    role_key        text,                                -- pairs with eval_sets.role_key
    current_version integer NOT NULL DEFAULT 1 CHECK (current_version > 0),
    archived_at     timestamptz,
    created_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX system_prompts_role_idx ON system_prompts (role_key) WHERE archived_at IS NULL;

COMMENT ON TABLE system_prompts IS
    'Reusable system prompts. One prompt, many agents: "the bookkeeper prompt", improved once.';

CREATE TABLE system_prompt_versions (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prompt_id   bigint NOT NULL REFERENCES system_prompts(id) ON DELETE RESTRICT,
    version_no  integer NOT NULL CHECK (version_no > 0),
    body        text NOT NULL,
    change_note text,
    created_by  bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (prompt_id, version_no)
);

COMMENT ON TABLE system_prompt_versions IS
    'Immutable prompt text per version. A new wording is a new version, never an edit — an '
    'agent configuration references one of these and keeps its own copy of the resolved body.';

-- A version's body never changes once written; that immutability is what lets a config version
-- cite it. Same shape as gl_lines_immutable() in db/056.
CREATE OR REPLACE FUNCTION system_prompt_versions_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.body IS DISTINCT FROM NEW.body THEN
        RAISE EXCEPTION
            'A prompt version''s text cannot be edited; write a new version instead';
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER system_prompt_versions_no_edit
    BEFORE UPDATE ON system_prompt_versions
    FOR EACH ROW EXECUTE FUNCTION system_prompt_versions_immutable();

-- --------------------------------------------------------------------------
-- An agent configuration cites a library prompt, and keeps the text it resolved to
-- --------------------------------------------------------------------------
ALTER TABLE agent_config_versions
    ADD COLUMN system_prompt_id      bigint REFERENCES system_prompts(id) ON DELETE RESTRICT,
    ADD COLUMN system_prompt_version integer CHECK (system_prompt_version > 0);

-- Either both or neither: a pointer without a version cannot be resolved back to the text.
ALTER TABLE agent_config_versions ADD CONSTRAINT agent_config_prompt_ref_complete CHECK (
    (system_prompt_id IS NULL AND system_prompt_version IS NULL)
 OR (system_prompt_id IS NOT NULL AND system_prompt_version IS NOT NULL)
);

COMMENT ON COLUMN agent_config_versions.job_description IS
    'The system prompt as this configuration actually used it. When system_prompt_id is set '
    'this is the resolved copy of that library version''s body — kept deliberately, so that '
    'editing the library later never changes the record of what a past configuration said.';
COMMENT ON COLUMN agent_config_versions.system_prompt_id IS
    'The library prompt this configuration drew from. NULL = the prompt was written inline for '
    'this agent alone, which stays permitted.';

-- --------------------------------------------------------------------------
-- Agent identity
-- --------------------------------------------------------------------------
ALTER TABLE agent_profiles
    ADD COLUMN description     text,
    ADD COLUMN role_key        text,
    ADD COLUMN profile_pic_url text;

COMMENT ON COLUMN agent_profiles.description IS
    'A sentence about what this agent is for, in a person''s words. Distinct from the job '
    'description, which is the system prompt the model receives.';
COMMENT ON COLUMN agent_profiles.role_key IS
    'The agent''s functional role, e.g. "bookkeeper". Pairs with eval_sets.role_key, so an eval '
    'set written for a role applies to every agent holding it.';
COMMENT ON COLUMN agent_profiles.profile_pic_url IS
    'A URL to the agent''s picture. A URL rather than an upload because this server has no file '
    'storage yet — the Documents slice (phase 4) brings that, and will fill this same column.';

-- --------------------------------------------------------------------------
-- Read views. New columns are appended, so CREATE OR REPLACE keeps grants intact.
-- --------------------------------------------------------------------------
CREATE VIEW mcp_system_prompts AS
 SELECT p.id AS system_prompt_id, p.prompt_key, p.name, p.description, p.role_key,
        p.current_version, p.archived_at, p.created_at, p.updated_at,
        ( SELECT count(*) FROM system_prompt_versions v WHERE v.prompt_id = p.id) AS version_count,
        ( SELECT count(*) FROM agent_config_versions c WHERE c.system_prompt_id = p.id) AS used_by_configs
   FROM system_prompts p
  WHERE app_is_insider();

CREATE VIEW mcp_system_prompt_versions AS
 SELECT v.id AS system_prompt_version_id, v.prompt_id AS system_prompt_id, p.prompt_key,
        v.version_no, v.body, v.change_note, v.created_by, m.display_name AS created_by_name,
        v.created_at
   FROM system_prompt_versions v
   JOIN system_prompts p ON p.id = v.prompt_id
   LEFT JOIN members m ON m.id = v.created_by
  WHERE app_is_insider();

ALTER VIEW mcp_system_prompts SET (security_barrier = true);
ALTER VIEW mcp_system_prompt_versions SET (security_barrier = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_system_prompts, mcp_system_prompt_versions TO app_rw;
GRANT SELECT ON mcp_system_prompts, mcp_system_prompt_versions TO app_records_ro;

COMMIT;
