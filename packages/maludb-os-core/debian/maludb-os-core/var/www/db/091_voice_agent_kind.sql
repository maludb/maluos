-- 091_voice_agent_kind.sql
-- A third kind of agent: the voice agent that answers the phone.
--
-- Decided 2026-09-18 (owner). Until now an agent was an orchestrator (holds a roster and
-- delegates) or a subagent (does the work, never re-delegates). A voice agent is neither: it
-- is the business's voice on an inbound call, and its system prompt is what the telephony
-- provider (RetellAI) reads when a call arrives. It employs nobody and is employed by nobody,
-- so it stays outside the delegation tree entirely — which also means the one-level rule that
-- makes delegation cycle-free (db/072) is untouched.
--
-- It is an ordinary agent in every other respect: an employment profile, a manager, a model, a
-- prompt version, tool grants, a budget, evals and a prompt ledger. Nothing here is telephony
-- configuration; wiring a voice agent to a phone number is its own slice.

BEGIN;

ALTER TABLE agent_profiles DROP CONSTRAINT agent_profiles_agent_kind_check;
ALTER TABLE agent_profiles ADD CONSTRAINT agent_profiles_agent_kind_check CHECK (
    agent_kind IN ('orchestrator', 'subagent', 'voice')
);

COMMENT ON COLUMN agent_profiles.agent_kind IS
    'orchestrator = may hold a roster of subagents and delegate to them; subagent = does the '
    'work and never re-delegates; voice = answers inbound calls, its system prompt read by the '
    'telephony provider when a call arrives, and takes no part in delegation. Default subagent: '
    'most agents do a job rather than hand it on.';

-- --------------------------------------------------------------------------
-- The roster rules now have three kinds to name, so they name them. Without this a voice
-- agent added to a roster would be refused as "an orchestrator", which is simply untrue.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION agent_subagents_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE ok text; sk text; oname text; sname text;
BEGIN
    SELECT p.agent_kind, m.display_name INTO ok, oname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id
     WHERE p.member_id = NEW.orchestrator_member_id;
    SELECT p.agent_kind, m.display_name INTO sk, sname
      FROM agent_profiles p JOIN members m ON m.id = p.member_id
     WHERE p.member_id = NEW.subagent_member_id;

    IF ok = 'voice' THEN
        RAISE EXCEPTION
            '% is a voice agent: it answers calls and manages nobody', coalesce(oname, 'That agent');
    END IF;
    IF ok <> 'orchestrator' THEN
        RAISE EXCEPTION '% is a subagent, so it cannot manage other agents', coalesce(oname, 'That agent');
    END IF;
    IF sk = 'voice' THEN
        RAISE EXCEPTION
            '% is a voice agent: it answers calls and is not delegated to', coalesce(sname, 'That agent');
    END IF;
    IF sk <> 'subagent' THEN
        RAISE EXCEPTION
            '% is an orchestrator, so it cannot be managed by another one — delegation is one level deep',
            coalesce(sname, 'That agent');
    END IF;
    RETURN NEW;
END$$;

COMMIT;
