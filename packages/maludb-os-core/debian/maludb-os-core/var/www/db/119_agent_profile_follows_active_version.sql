-- 119: an agent's profile shows the model and budget of its ACTIVE configuration version.
--
-- agent_profiles.model_id and .monthly_budget_amount are what mcp_agents, the agents list, the
-- dashboard cards and find_agents report as the agent's current model and budget. Activating a
-- version moved current_config_version_id and nothing else, so an agent moved to another model
-- went on showing the one it was hired on (found 2026-09-20: Jack, Becky and Sasha run on
-- hermes:claude-sonnet-5 and were shown as claude-fable-5-1 on the claude_agent_sdk harness).
-- Nothing ran on the wrong model — the runner and the ledger proxy read the version — only the
-- display and the read tools were wrong.
--
-- app/features/agents/hiring.php (activate_config_version) now carries both over. This brings
-- the existing rows in line, once. A version with no budget of its own leaves the profile's alone.
--
-- Data repair only; no structure changes. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/119_agent_profile_follows_active_version.sql

BEGIN;

UPDATE agent_profiles ap
   SET model_id = cv.model_id,
       monthly_budget_amount = COALESCE(cv.monthly_budget_amount, ap.monthly_budget_amount),
       updated_at = now()
  FROM agent_config_versions cv
 WHERE cv.id = ap.current_config_version_id
   AND (ap.model_id IS DISTINCT FROM cv.model_id
        OR (cv.monthly_budget_amount IS NOT NULL
            AND ap.monthly_budget_amount IS DISTINCT FROM cv.monthly_budget_amount));

COMMIT;
