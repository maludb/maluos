-- 048_activity_log_business.sql
-- Extends the append-only activity stream for the agent workforce: new sources, and the
-- links that make agent work auditable — where it ran, which run produced it, and which
-- approval allowed it (AP8, SM13, PL2, L7, DB7, H6, X3).
-- mcp/activity_ingest.py selects explicit columns, so these additions do not change what
-- MaluDB ingests; adding them to the episode payload is a separate bridge change.

BEGIN;

ALTER TABLE activity_log DROP CONSTRAINT activity_log_source_check;
ALTER TABLE activity_log ADD CONSTRAINT activity_log_source_check
    CHECK (source IN ('web', 'assistant', 'mcp', 'cron',      -- existing
                      'agent',                                -- an agent run (agent_run_id set)
                      'desk',                                 -- desktop companion
                      'webhook',                              -- payment provider / MaluMail / platform callbacks
                      'portal'));                             -- External member portal

-- No FKs on purpose: the log must never block deleting or archiving anything else, and
-- archived log partitions must not carry constraints into other tables.
ALTER TABLE activity_log
    ADD COLUMN location_id          bigint,
    ADD COLUMN agent_run_id         bigint,
    ADD COLUMN approval_request_id  bigint,
    ADD COLUMN department_id        bigint;

CREATE INDEX activity_agent_run_idx ON activity_log (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX activity_approval_idx  ON activity_log (approval_request_id) WHERE approval_request_id IS NOT NULL;
CREATE INDEX activity_location_idx  ON activity_log (location_id, occurred_at DESC) WHERE location_id IS NOT NULL;
CREATE INDEX activity_source_time_idx ON activity_log (source, occurred_at DESC);

COMMIT;
