-- 137: the ledger's period statement (A5, 2026-09-22).
--
-- docs/business-os-integration.md, "Token accounting": the kernel keeps token accounting only, with
-- dollar costs, and exports it. Each calendar month the ledger rolls up into one statement per
-- provider, model, department, agent, application and currency; a super-admin closes a period, a
-- closed statement never changes, and a call that arrives late for a closed period lands in the
-- open period with a note. The roll-up table that used to feed the books keeps this job; its
-- books vocabulary goes.
--
--   * ai_periods — one row per month: open or closed, and the ledger high-water mark at close
--     (a call above it for a closed month is "late").
--   * ai_usage_postings — status open/closed/void (was draft/posted/void), posted_* renamed
--     closed_*, plus application_id, currency in the key, and late_calls.
--   * prompt_ledger.application_id and agent_runs.application_id — the application a chat run
--     was made for (A6 writes it); NULL for the kernel's own runs.
-- The view mcp_ai_usage_postings is recreated (a renamed column cannot be replaced in place);
-- mcp_prompt_ledger and mcp_agent_runs gain application_id appended last.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/137_ai_periods.sql

BEGIN;

CREATE TABLE ai_periods (
    period_start        date PRIMARY KEY,
    period_end          date NOT NULL CHECK (period_end >= period_start),
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_at           timestamptz,
    closed_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    ledger_high_water   bigint,                       -- the last prompt_ledger.id counted at close
    rolled_up_at        timestamptz,
    note                text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ai_periods IS 'One calendar month of the AI ledger: open (statement rows are recomputed) or closed (frozen; later calls for it are late and land in the open month).';
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_periods TO app_rw;
GRANT SELECT ON ai_periods TO app_records_ro;

ALTER TABLE prompt_ledger ADD COLUMN application_id bigint REFERENCES applications(id) ON DELETE SET NULL;
ALTER TABLE agent_runs ADD COLUMN application_id bigint REFERENCES applications(id) ON DELETE SET NULL;
COMMENT ON COLUMN prompt_ledger.application_id IS 'The application a chat run was made for (A6); NULL for the kernel''s own runs.';

DROP VIEW mcp_ai_usage_postings;
ALTER TABLE ai_usage_postings RENAME COLUMN posted_at TO closed_at;
ALTER TABLE ai_usage_postings RENAME COLUMN posted_by TO closed_by;
ALTER TABLE ai_usage_postings
    ADD COLUMN application_id bigint REFERENCES applications(id) ON DELETE SET NULL,
    ADD COLUMN late_calls integer NOT NULL DEFAULT 0 CHECK (late_calls >= 0);
ALTER TABLE ai_usage_postings DROP CONSTRAINT ai_usage_postings_status_check;
UPDATE ai_usage_postings SET status = CASE status WHEN 'draft' THEN 'open' WHEN 'posted' THEN 'closed' ELSE status END;
ALTER TABLE ai_usage_postings ADD CONSTRAINT ai_usage_postings_status_check CHECK (status IN ('open', 'closed', 'void'));
DROP INDEX ai_usage_postings_period_idx;
CREATE UNIQUE INDEX ai_usage_postings_period_idx ON ai_usage_postings
    (period_start, period_end, provider, model_id, department_id, agent_member_id, application_id, currency) NULLS NOT DISTINCT;
COMMENT ON TABLE ai_usage_postings IS 'The period statement: the prompt ledger rolled up per month × provider × model × department × agent × application × currency. Exported, never posted (2026-09-22).';

CREATE VIEW mcp_ai_usage_postings WITH (security_barrier = true) AS
SELECT p.id AS ai_usage_posting_id, p.period_start, p.period_end, p.provider, p.model_id,
       mr.display_name AS model_name, p.department_id, d.name::text AS department_name,
       p.agent_member_id, m.display_name AS agent_name, p.call_count, p.input_tokens, p.output_tokens,
       p.cache_read_tokens, p.cache_write_tokens, p.amount, p.currency, p.status, p.closed_at, p.note,
       p.application_id, a.name AS application_name, p.late_calls, p.closed_by
  FROM ai_usage_postings p
  LEFT JOIN model_registry mr ON mr.id = p.model_id
  LEFT JOIN departments d ON d.id = p.department_id
  LEFT JOIN members m ON m.id = p.agent_member_id
  LEFT JOIN applications a ON a.id = p.application_id
 WHERE app_is_insider() AND (app_has_module('ledger') OR app_is_super_admin());
GRANT SELECT ON mcp_ai_usage_postings TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_ai_usage_postings TO app_rw;

CREATE VIEW mcp_ai_periods WITH (security_barrier = true) AS
SELECT p.period_start, p.period_end, to_char(p.period_start, 'YYYY-MM') AS period, p.status, p.closed_at, p.closed_by,
       cb.display_name AS closed_by_name, p.ledger_high_water, p.rolled_up_at, p.note
  FROM ai_periods p LEFT JOIN members cb ON cb.id = p.closed_by
 WHERE app_is_insider() AND (app_has_module('ledger') OR app_is_super_admin());
GRANT SELECT ON mcp_ai_periods TO app_records_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_ai_periods TO app_rw;

CREATE OR REPLACE VIEW mcp_prompt_ledger WITH (security_barrier = true) AS
SELECT id AS ledger_id, occurred_at, agent_run_id, agent_member_id, acting_member_id, location_id,
       harness, sdk_version, provider, model_id, provider_model_id, request_id, call_kind, status,
       error_code, error_message, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
       latency_ms, cost, currency, payload_archived_at,
       application_id
  FROM prompt_ledger pl
 WHERE app_can_see_run(agent_member_id, acting_member_id);

CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id,
       r.location_id, r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id,
       r.harness, r.sdk_version, r.request_id, r.status, r.error,
       r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens, r.cost, r.currency,
       r.started_at, r.finished_at, r.instructions, r.result, r.parent_run_id, r.requested_by,
       r.approval_request_id,
       r.application_id
  FROM agent_runs r LEFT JOIN members am ON am.id = r.agent_member_id
 WHERE app_can_see_run(r.agent_member_id, r.acting_member_id);

COMMIT;
