-- 016_activity_ingest_state.sql
-- Checkpoint for the MaluDB activity-memory ingestion bridge (mcp/activity_ingest.py).
-- One row: the highest activity_log.id already shipped to the tenant's MaluDB memory.
-- The bridge polls activity_log past this id and POSTs each row to the MaluDB API
-- as an 'activity' episode, then advances the checkpoint in the same run.

BEGIN;

CREATE TABLE IF NOT EXISTS activity_ingest_state (
    id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),   -- singleton row
    last_id     bigint NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO activity_ingest_state (id, last_id) VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- The bridge connects as app_rw (reads activity_log, advances the checkpoint).
GRANT SELECT, UPDATE ON activity_ingest_state TO app_rw;

COMMIT;
