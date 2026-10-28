-- 071_prompt_version_parameters.sql
-- Model parameters belong to the prompt version.
--
-- Decided 2026-09-18. db/070 gave prompts their own versioned objects so an eval run could pin
-- a (prompt version, model, harness) triple. But the parameters that shape behaviour as much as
-- the wording does — temperature, max tokens, a thinking budget — were still sitting in
-- agent_config_versions.harness_config as unconstrained jsonb, per agent. That left the obvious
-- question unanswerable: "we changed temperature and the scores moved" could not be told apart
-- from "we changed the prompt and the scores moved".
--
-- So parameters move onto system_prompt_versions, and a version becomes the whole instruction
-- unit: this wording, at these settings. Changing temperature is a new version, exactly as
-- changing a sentence is — which is the point, because both change what you are measuring.
--
-- Consequence, stated plainly: two agents that need different temperatures need two prompt
-- versions (or two prompts). That is deliberate. If per-agent tuning is wanted later, the
-- mirror trigger below is the single place to relax.

BEGIN;

ALTER TABLE system_prompt_versions
    ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}'
        CHECK (jsonb_typeof(parameters) = 'object');

COMMENT ON COLUMN system_prompt_versions.parameters IS
    'Model parameters for this version: temperature, max_tokens, top_p, thinking_budget, '
    'stop_sequences and whatever else the harness takes. jsonb because harnesses differ; the '
    'two that get compared most often are lifted into generated columns beside it.';

-- The two people actually compare across runs, lifted out so "did temperature change between
-- these versions?" is a query rather than a jsonb excavation. Generated, so they cannot drift
-- from the jsonb they come from.
ALTER TABLE system_prompt_versions
    ADD COLUMN temperature numeric(4,3)
        GENERATED ALWAYS AS (NULLIF(parameters->>'temperature', '')::numeric) STORED,
    ADD COLUMN max_tokens integer
        GENERATED ALWAYS AS (NULLIF(parameters->>'max_tokens', '')::integer) STORED;

-- Parameters are as immutable as the body: a version is a thing an eval result cites, and a
-- citation that can change underneath is not a citation. db/070's trigger guarded the body
-- only, which would have left the settings editable in place — the very drift this migration
-- exists to prevent.
CREATE OR REPLACE FUNCTION system_prompt_versions_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.body IS DISTINCT FROM NEW.body THEN
        RAISE EXCEPTION
            'A prompt version''s text cannot be edited; write a new version instead';
    END IF;
    IF OLD.parameters IS DISTINCT FROM NEW.parameters THEN
        RAISE EXCEPTION
            'A prompt version''s model parameters cannot be edited; write a new version instead';
    END IF;
    RETURN NEW;
END$$;

-- --------------------------------------------------------------------------
-- A configuration citing a prompt version carries that version's parameters,
-- and nothing else. Same rule as job_description already follows for the body:
-- the pointer says which version, the copy says what was actually used.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION agent_config_harness_mirror() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE p jsonb;
BEGIN
    IF NEW.system_prompt_id IS NULL THEN
        RETURN NEW;                      -- an inline prompt keeps its own settings
    END IF;
    SELECT parameters INTO p
      FROM system_prompt_versions
     WHERE prompt_id = NEW.system_prompt_id AND version_no = NEW.system_prompt_version;
    IF p IS NULL THEN
        RAISE EXCEPTION 'Prompt version %/% does not exist',
            NEW.system_prompt_id, NEW.system_prompt_version;
    END IF;
    -- Resolved, not asserted: whatever the caller sent is replaced by the cited version's
    -- settings, so a configuration can never claim parameters its prompt version did not have.
    NEW.harness_config := p;
    RETURN NEW;
END$$;

CREATE TRIGGER agent_config_versions_harness_mirror
    BEFORE INSERT OR UPDATE OF system_prompt_id, system_prompt_version, harness_config
    ON agent_config_versions
    FOR EACH ROW EXECUTE FUNCTION agent_config_harness_mirror();

COMMENT ON COLUMN agent_config_versions.harness_config IS
    'The model parameters this configuration actually used. When system_prompt_id is set this '
    'is the resolved copy of that prompt version''s parameters, written by trigger and not '
    'settable independently — parameters are managed on the prompt version (db/071). With no '
    'library prompt it is the inline configuration''s own settings.';

-- The views carry them; new columns are appended so grants survive.
CREATE OR REPLACE VIEW mcp_system_prompt_versions AS
 SELECT v.id AS system_prompt_version_id, v.prompt_id AS system_prompt_id, p.prompt_key,
        v.version_no, v.body, v.change_note, v.created_by, m.display_name AS created_by_name,
        v.created_at,
        v.parameters, v.temperature, v.max_tokens
   FROM system_prompt_versions v
   JOIN system_prompts p ON p.id = v.prompt_id
   LEFT JOIN members m ON m.id = v.created_by
  WHERE app_is_insider();

COMMIT;
