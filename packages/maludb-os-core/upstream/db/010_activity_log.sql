-- 010_activity_log.sql
-- Activity memory — the single append-only stream every actor's every action writes to
-- (plan §3.4). Logging exists from day one; activity memory cannot be backfilled.
-- The activity-memory MCP server reads this table (read-only role). MaluDB ingests it
-- continuously (wiring at the bottom, guarded so it is a no-op before MaluDB is set up).

BEGIN;

CREATE TABLE activity_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    actor_member_id bigint REFERENCES members(id) ON DELETE SET NULL,   -- null for anon/cron
    source          text NOT NULL DEFAULT 'web'
                        CHECK (source IN ('web','assistant','mcp','cron')),
    action          text NOT NULL,                          -- 'attempt.reschedule', 'issue.create', ...
    screen          text,                                   -- screen id: 'attempts-edit'
    route           text,                                   -- 'POST /attempts/save.php'
    entity_type     text,                                   -- 'exam_attempt'
    entity_id       bigint,
    before          jsonb,                                  -- prior values on a change
    after           jsonb,                                  -- new values on a change
    request_id      text,                                   -- trace one request / assistant turn
    session_id      text,
    ip_address      inet,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- Append-only in practice; these indexes serve the activity questions (M16-M19, O12-O15).
CREATE INDEX activity_actor_time_idx  ON activity_log (actor_member_id, occurred_at DESC);
CREATE INDEX activity_entity_idx      ON activity_log (entity_type, entity_id, occurred_at DESC);
CREATE INDEX activity_action_time_idx ON activity_log (action, occurred_at DESC);
CREATE INDEX activity_time_idx        ON activity_log (occurred_at DESC);
CREATE INDEX activity_request_idx     ON activity_log (request_id);

-- The app writes and reads; no UPDATE/DELETE in normal operation (retention handled by
-- a partition-drop / archival job, out of scope here). The activity read role gets NO
-- base-table grant — it reads only the mcp_activity_* views (012), which encode who may
-- see whose trail. The record read role never sees the activity stream at all.
GRANT INSERT, SELECT ON activity_log TO app_rw;
REVOKE ALL ON activity_log FROM app_records_ro, app_activity_ro;

-- --------------------------------------------------------------------------
-- MaluDB ingestion wiring
-- --------------------------------------------------------------------------
-- MaluDB ingests the activity stream continuously. Preferred path: a logical-replication
-- publication MaluDB subscribes to, so inserts flow without a polling job. Guarded so
-- this file runs on a plain PostgreSQL 17 host during early development.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'maludb') THEN
        -- Publication of the append-only stream for MaluDB's subscriber.
        IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'maludb_activity_pub') THEN
            EXECUTE 'CREATE PUBLICATION maludb_activity_pub FOR TABLE activity_log';
        END IF;
        -- Register the stream with MaluDB's ingestion catalog. The exact function name
        -- follows the installed MaluDB version; wrapped so a signature mismatch does not
        -- abort the migration — the DBA finalizes it against the deployed MaluDB.
        BEGIN
            PERFORM maludb_ingest_register('activity_log', 'occurred_at');
        EXCEPTION WHEN undefined_function THEN
            RAISE NOTICE 'maludb_ingest_register not found — register activity_log manually per the deployed MaluDB version';
        END;
    ELSE
        RAISE NOTICE 'maludb extension absent — activity_log will be ingested once MaluDB is installed';
    END IF;
END$$;

COMMIT;
