-- 184: K57 — the Sovereign LLM Manager in the catalog (D1/D16 of /srv/apps/sovereign_llm_manager/docs/sovereign-llm-manager-design.md
-- §12–13, the owner approved 2026-10-17): the business's window on the machines that run its models — every node running
-- maluos-local-llm-server (the queue in front of a machine with Ollama: one local inference at a time, cloud models beside it,
-- the OpenAI and Anthropic faces for anything on the network) on one set of screens: the fleet's health, each node's queue live,
-- the run history with its numbers (queue wait, time to first token, tokens per second, load time, fallbacks), token usage by
-- period, caller, model and lane, the models on each node (pull, warm, unload, keep warm, the cloud fallback a model may take),
-- the keys callers hold, the policies the node enforces. Category 'platform' is already admitted by both checks, so nothing is
-- widened. Seeded so every installation shows it under Technology & Infrastructure ("from us, not installed") and the installer's
-- apply finds its row. On request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/184_k57_sovereign_llm_manager_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'sovereign_llm_manager', 'Sovereign LLM Manager',
       'The business''s window on the machines that run its own models. Every node running the local LLM server — a Mac, a GPU box, a desk — on one set of screens: the fleet''s health, each node''s queue live, the run history with its numbers (queue wait, time to first token, tokens per second, load time, fallbacks to the cloud), token usage by period, caller, model and lane with a notional price, the models on each node (pull, warm, unload, keep warm, the cloud fallback a model may take and who allowed it), the keys callers hold, the policies the node enforces and any drift from them. Operators act on the queue; admins hold the nodes, keys and policies; a prompt leaves a machine only when a person said it may. The LLM Ops expert answers from the command bar; the Fleet Watcher''s morning note names what is down, backed up or slow. Shares usage with the ledger. Optional; installed on request.',
       'feather-cpu', g.id, 'ours', NULL, 'platform', 1
  FROM nav_groups g WHERE g.name = 'Technology & Infrastructure'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
