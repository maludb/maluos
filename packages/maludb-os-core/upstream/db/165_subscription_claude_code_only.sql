-- 165: Claude subscription login is for the Claude Code harness ONLY (2026-09-29).
--
-- db/164 allowed the hermes harness too. Hermes, given a subscription token, presents itself as Claude Code (a claude-code
-- user-agent, x-app: cli, and "You are Claude Code, Anthropic's official CLI" prepended to the system prompt) — impersonating
-- Anthropic's client to use a subscription. The official CLI does not: it IS the client. So the feature is limited to
-- claude_agent_sdk, and the two Hermes "Max plan" twin rows db/164 seeded are removed (nothing referenced them).
-- Additive in effect: no agent ever used them. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/165_subscription_claude_code_only.sql

BEGIN;

DELETE FROM model_registry m
 WHERE m.auth_mode = 'claude_subscription' AND m.harness = 'hermes'
   AND NOT EXISTS (SELECT 1 FROM agent_config_versions v WHERE v.model_id = m.id)
   AND NOT EXISTS (SELECT 1 FROM agent_profiles p WHERE p.model_id = m.id)
   AND NOT EXISTS (SELECT 1 FROM agent_runs r WHERE r.model_id = m.id)
   AND NOT EXISTS (SELECT 1 FROM agent_lead_proposals l WHERE l.model_id = m.id);

ALTER TABLE model_registry DROP CONSTRAINT model_registry_subscription_scope;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_subscription_scope
    CHECK (auth_mode = 'api_key' OR (provider = 'anthropic' AND harness = 'claude_agent_sdk'));
COMMENT ON COLUMN model_registry.auth_mode IS 'What the model bills to: api_key (a provider key held by the ledger proxy) or claude_subscription (the owner''s Max login; only Anthropic models on the claude_agent_sdk harness — the official CLI; refused unless the runner''s ALLOW_CLAUDE_SUBSCRIPTION switch is on).';

COMMIT;
