-- 166: mcp_model_registry carries auth_mode (docs/build-specs/claude-subscription-auth.md), appended LAST so PHP can refuse
-- to hire or activate an agent onto a subscription model while the runner's switch is off. Additive.
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/166_model_auth_mode_view.sql
BEGIN;
CREATE OR REPLACE VIEW mcp_model_registry WITH (security_barrier = true) AS
SELECT id AS model_id, model_key, display_name, provider, provider_model_id, harness, context_window_tokens,
       price_input_per_mtok, price_output_per_mtok, price_cache_read_per_mtok, price_cache_write_per_mtok,
       currency, status, auth_mode
  FROM model_registry
 WHERE app_is_insider();
COMMIT;
