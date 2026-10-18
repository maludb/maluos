-- 047_ops_audit.sql
-- Operability records for the owner: nightly backups, restore rehearsals, and self-serve
-- SaaS Plus+ exports. Questions: X5, X6.

BEGIN;

CREATE TABLE backup_runs (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind           text NOT NULL CHECK (kind IN ('nightly', 'manual', 'pre_migration')),
    scope          text[] NOT NULL DEFAULT ARRAY['database','memory','documents']
                       CHECK (scope <@ ARRAY['database','memory','documents']::text[]),
    status         text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    storage_path   text,
    size_bytes     bigint CHECK (size_bytes >= 0),
    sha256         text,
    error          text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);
CREATE INDEX backup_runs_time_idx ON backup_runs (started_at DESC);

CREATE TABLE restore_rehearsals (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    backup_run_id   bigint NOT NULL REFERENCES backup_runs(id) ON DELETE RESTRICT,
    status          text NOT NULL CHECK (status IN ('passed', 'failed')),
    checks          jsonb NOT NULL DEFAULT '{}',                -- row counts, smoke queries
    notes           text,
    performed_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    performed_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX restore_rehearsals_time_idx ON restore_rehearsals (performed_at DESC);

-- Full tenant export: SQL dump + activity stream + documents archive (owner only).
CREATE TABLE data_exports (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requested_by     bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    includes         text[] NOT NULL DEFAULT ARRAY['database','activity','documents']
                         CHECK (includes <@ ARRAY['database','activity','documents','prompt_payloads']::text[]),
    status           text NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'running', 'ready', 'failed', 'expired', 'cancelled')),
    storage_path     text,
    size_bytes       bigint CHECK (size_bytes >= 0),
    sha256           text,
    error            text,
    requested_at     timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz,
    downloaded_at    timestamptz,
    expires_at       timestamptz
);
CREATE INDEX data_exports_time_idx ON data_exports (requested_at DESC);

-- Foreign-key lookup indexes
CREATE INDEX restore_rehearsals_backup_idx ON restore_rehearsals (backup_run_id);

COMMIT;
