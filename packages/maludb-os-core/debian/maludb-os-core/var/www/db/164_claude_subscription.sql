-- 164: Claude subscription (Max plan) login for agents — the owner's own install only (2026-09-29).
--
-- docs/build-specs/claude-subscription-auth.md. A model row says what it bills to: 'api_key' (every row so far) or
-- 'claude_subscription' (a Claude model reached with the owner's Max login — off unless the runner's switch is on).
-- The ledger keeps money and notional apart: a subscription call is stored with cost = 0 (nothing was paid) and the
-- price the API WOULD have charged in notional_cost, so every dollar total and statement that sums `cost` is right
-- without a change; budgets count both (owner, 2026-09-29). Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/164_claude_subscription.sql

BEGIN;

ALTER TABLE model_registry
    ADD COLUMN auth_mode text NOT NULL DEFAULT 'api_key'
        CHECK (auth_mode IN ('api_key', 'claude_subscription')),
    ADD CONSTRAINT model_registry_subscription_scope
        CHECK (auth_mode = 'api_key' OR (provider = 'anthropic' AND harness IN ('claude_agent_sdk', 'hermes')));
COMMENT ON COLUMN model_registry.auth_mode IS 'What the model bills to: api_key (a provider key held by the ledger proxy) or claude_subscription (the owner''s Max login; only Anthropic models on the claude_agent_sdk and hermes harnesses; refused unless the runner''s ALLOW_CLAUDE_SUBSCRIPTION switch is on).';

ALTER TABLE prompt_ledger
    ADD COLUMN billing       text NOT NULL DEFAULT 'api' CHECK (billing IN ('api', 'subscription')),
    ADD COLUMN notional_cost numeric(14,6) NOT NULL DEFAULT 0 CHECK (notional_cost >= 0);
COMMENT ON COLUMN prompt_ledger.billing IS 'api = paid per token (cost is real); subscription = drawn on a flat-rate plan (cost is 0, notional_cost is what the API would have charged).';
COMMENT ON COLUMN prompt_ledger.notional_cost IS 'List-price cost of a subscription call. Never money paid; never in a statement; counted by an agent''s monthly budget.';

-- mcp_prompt_ledger gains the two columns LAST; the rest is db/160's definition, unchanged.
CREATE OR REPLACE VIEW mcp_prompt_ledger WITH (security_barrier = true) AS
SELECT pl.id AS ledger_id, pl.occurred_at, pl.agent_run_id, pl.agent_member_id, pl.acting_member_id, pl.location_id,
       pl.harness, pl.sdk_version, pl.provider, pl.model_id, pl.provider_model_id, pl.request_id, pl.call_kind,
       pl.status, pl.error_code, pl.error_message, pl.input_tokens, pl.output_tokens, pl.cache_read_tokens,
       pl.cache_write_tokens, pl.latency_ms, pl.cost, pl.currency, pl.payload_archived_at, pl.application_id,
       pl.billing, pl.notional_cost
  FROM prompt_ledger pl
 WHERE (SELECT app_is_insider())
   AND ((SELECT app_has_module('ledger'))
        OR pl.acting_member_id = (SELECT app_current_member_id())
        OR (pl.agent_member_id IS NOT NULL
            AND ((SELECT app_has_module('hr'))
                 OR pl.agent_member_id = (SELECT app_current_member_id())
                 OR pl.agent_member_id IN (SELECT ap.member_id FROM agent_profiles ap
                                            WHERE ap.manager_member_id = app_current_member_id()))));

-- The Max-plan twins of the Claude rows in use, priced as their API originals (that price IS the notional cost).
-- Separate rows, never a flag on an existing one, so an agent's model says plainly what it bills to. Inert until
-- the switch is on: hiring or activating an agent onto one is refused by name without it.
INSERT INTO model_registry (model_key, display_name, provider, provider_model_id, harness, endpoint_url, config, context_window_tokens,
                            price_input_per_mtok, price_output_per_mtok, price_cache_read_per_mtok, price_cache_write_per_mtok, currency, status, auth_mode)
SELECT m.model_key || '@max', m.display_name || ' · Max plan', m.provider, m.provider_model_id, m.harness, m.endpoint_url, m.config,
       m.context_window_tokens, m.price_input_per_mtok, m.price_output_per_mtok, m.price_cache_read_per_mtok, m.price_cache_write_per_mtok,
       m.currency, 'active', 'claude_subscription'
  FROM model_registry m
 WHERE m.model_key IN ('claude-fable-5-1', 'hermes:claude-fable-5-1', 'hermes:claude-sonnet-5')
   AND m.auth_mode = 'api_key'
ON CONFLICT (model_key) DO NOTHING;

COMMIT;
