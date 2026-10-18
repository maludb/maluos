-- 121: Fireworks AI as a model provider.
--
-- Fireworks hosts many open models (DeepSeek, Kimi, GLM, Qwen, Llama, Nemotron …) behind one
-- OpenAI-compatible API and one key, so it is a PROVIDER in the registry's sense — the party the
-- ledger proxy calls and whose key it holds — not a model family. `other` would have worked only
-- with an endpoint_url on every row and no key: the runner maps a provider to its key.
--
-- Widens one CHECK; every existing row stays valid. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/121_model_provider_fireworks.sql

BEGIN;

ALTER TABLE model_registry DROP CONSTRAINT model_registry_provider_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_provider_check
    CHECK (provider = ANY (ARRAY['anthropic', 'openai', 'deepseek', 'zhipu', 'moonshot', 'qwen',
                                 'fireworks', 'local', 'other']));

COMMIT;
