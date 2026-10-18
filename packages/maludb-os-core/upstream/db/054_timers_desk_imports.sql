-- 054_timers_desk_imports.sql
-- Two gaps found while designing the action manifest (build plan 1.6):
--   * timer_start / timer_stop need a running timer; a time entry can't hold one because
--     time_entries.minutes must be positive. One running timer per member.
--   * desk_import_confirm needs a staged import: a file dropped on a desk waits here until
--     the desk owner confirms it into Documents (nothing reaches Documents silently).

BEGIN;

CREATE TABLE time_timers (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id        bigint NOT NULL UNIQUE REFERENCES members(id) ON DELETE CASCADE,  -- one per member
    started_at       timestamptz NOT NULL DEFAULT now(),
    project_id       bigint REFERENCES projects(id) ON DELETE SET NULL,
    task_id          bigint REFERENCES tasks(id) ON DELETE SET NULL,
    organization_id  bigint REFERENCES organizations(id) ON DELETE SET NULL,
    ticket_id        bigint REFERENCES tickets(id) ON DELETE SET NULL,
    description      text,
    billable         boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE desk_imports (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id         bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    member_id           bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,   -- desk owner
    original_filename   text NOT NULL,
    mime_type           text,
    size_bytes          bigint CHECK (size_bytes >= 0),
    sha256              text NOT NULL,
    staged_path         text NOT NULL,                  -- server-side staging, purged on reject/expiry
    suggested_folder_id bigint REFERENCES folders(id) ON DELETE SET NULL,
    suggested_link_type text,
    suggested_link_id   bigint,
    status              text NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'confirmed', 'rejected', 'expired')),
    document_id         bigint REFERENCES documents(id) ON DELETE SET NULL,          -- set on confirm
    decided_at          timestamptz,
    expires_at          timestamptz NOT NULL DEFAULT now() + interval '7 days',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX desk_imports_pending_idx ON desk_imports (member_id, created_at) WHERE status = 'pending';
CREATE INDEX desk_imports_location_idx ON desk_imports (location_id);
CREATE INDEX desk_imports_document_idx ON desk_imports (document_id);

-- RLS + updated_at, as in 049.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['time_timers', 'desk_imports'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- Read views: your own timer (managers see who is on the clock); your own desk's imports.
CREATE OR REPLACE VIEW mcp_time_timers WITH (security_barrier = true) AS
SELECT tt.member_id, m.display_name, tt.started_at,
       (extract(epoch FROM now() - tt.started_at) / 60)::integer AS running_minutes,
       tt.project_id, tt.task_id, tt.organization_id, tt.ticket_id, tt.description, tt.billable
FROM time_timers tt JOIN members m ON m.id = tt.member_id
WHERE app_can_admin_member(tt.member_id) AND app_is_insider();

CREATE OR REPLACE VIEW mcp_desk_imports WITH (security_barrier = true) AS
SELECT di.id AS desk_import_id, di.location_id, l.name AS location_name, di.original_filename,
       di.mime_type, di.size_bytes, di.status, di.suggested_folder_id, di.suggested_link_type,
       di.suggested_link_id, di.document_id, di.decided_at, di.expires_at, di.created_at
FROM desk_imports di JOIN locations l ON l.id = di.location_id
WHERE di.member_id = app_current_member_id() OR app_is_super_admin();

GRANT SELECT ON mcp_time_timers, mcp_desk_imports TO app_records_ro;

COMMIT;
