-- 161: kernel services for applications — SMS (K6) and application reads (K7) (owner, 2026-09-28;
-- docs/build-specs/kernel-app-services.md). Additive.
--
-- K6: an application texts a member through the kernel. The business's notification number is a
-- notification_endpoints row (its Twilio auth token a tenant secret, by reference); a text waits in
-- application_notifications until the channels worker sends it; a member may turn one application's texts off.
-- K7: a provider application shares named read tools (application_shares, from its maludb-os.json); a consumer asks
-- the kernel to call one over a connection a super-admin approved (application_connections).
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/161_app_services.sql

BEGIN;

-- ---- K6 -----------------------------------------------------------------------------------------------------------
CREATE TABLE notification_endpoints (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel     text NOT NULL CHECK (channel IN ('sms')),
    address     text NOT NULL,                        -- the sending number, E.164
    secret_id   bigint REFERENCES tenant_secrets(id), -- the Twilio auth token, by reference
    config      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"account_sid": "AC…"} — nothing secret
    active      boolean NOT NULL DEFAULT true,
    created_by  bigint REFERENCES members(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX notification_endpoints_one_live ON notification_endpoints (channel) WHERE active;
COMMENT ON TABLE notification_endpoints IS 'The business''s number applications'' texts are sent from (db/161, K6). One live per channel.';

CREATE TABLE application_notifications (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    channel         text NOT NULL DEFAULT 'sms' CHECK (channel IN ('sms')),
    body            text NOT NULL CHECK (char_length(body) <= 520),
    reference       text CHECK (reference IS NULL OR char_length(reference) <= 120),
    created_at      timestamptz NOT NULL DEFAULT now(),
    attempts        integer NOT NULL DEFAULT 0,
    sent_at         timestamptz,
    failed_at       timestamptz,
    error           text
);
CREATE INDEX application_notifications_to_send ON application_notifications (created_at)
    WHERE sent_at IS NULL AND failed_at IS NULL;
CREATE INDEX application_notifications_member_day ON application_notifications (application_id, member_id, created_at);
COMMENT ON TABLE application_notifications IS 'Texts applications asked the kernel to send (db/161, K6). The body is kept to send it; the activity log never carries it.';

-- A member turns one application's texts off (or the carrier's STOP turns them all off: application_id NULL).
CREATE TABLE member_notification_optouts (
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    application_id  bigint REFERENCES applications(id) ON DELETE CASCADE,   -- NULL = every application
    channel         text NOT NULL DEFAULT 'sms' CHECK (channel IN ('sms')),
    reason          text NOT NULL CHECK (reason IN ('member', 'carrier_stop')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX member_notification_optouts_key ON member_notification_optouts
    (member_id, COALESCE(application_id, 0), channel);

-- ---- K7 -----------------------------------------------------------------------------------------------------------
CREATE TABLE application_shares (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    tool            text NOT NULL CHECK (tool ~ '^[a-z][a-z0-9_]{0,63}$'),
    description     text NOT NULL DEFAULT '',
    scoped          boolean NOT NULL DEFAULT false,
    withdrawn_at    timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, tool)
);
COMMENT ON TABLE application_shares IS 'Read tools a provider application shares with others through the kernel (db/161, K7), from its maludb-os.json shares[].';

CREATE TABLE application_connections (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consumer_id         bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    provider_id         bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    tool                text NOT NULL,
    why                 text NOT NULL DEFAULT '',
    proposed_at         timestamptz NOT NULL DEFAULT now(),
    proposed_by         text NOT NULL DEFAULT 'installer',
    approved_by         bigint REFERENCES members(id),
    approved_at         timestamptz,
    revoked_by          bigint REFERENCES members(id),
    revoked_at          timestamptz,
    CHECK (consumer_id <> provider_id),
    CHECK (approved_at IS NULL OR approved_by IS NOT NULL)
);
CREATE UNIQUE INDEX application_connections_live ON application_connections (consumer_id, provider_id, tool)
    WHERE revoked_at IS NULL;
COMMENT ON TABLE application_connections IS 'Consumer may call provider''s shared tool through the kernel once a super-admin approved it (db/161, K7). Revoked, never deleted.';

-- ---- access -------------------------------------------------------------------------------------------------------
ALTER TABLE notification_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_notification_optouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_connections ENABLE ROW LEVEL SECURITY;
CREATE POLICY notification_endpoints_app_rw ON notification_endpoints TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_notifications_app_rw ON application_notifications TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY member_notification_optouts_app_rw ON member_notification_optouts TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_shares_app_rw ON application_shares TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY application_connections_app_rw ON application_connections TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON notification_endpoints, application_notifications, application_shares, application_connections TO app_rw;
GRANT SELECT, INSERT, DELETE ON member_notification_optouts TO app_rw;

-- What the agents and the screens read: the connections and the queue, super-admins only (the queue without bodies).
CREATE VIEW mcp_application_connections WITH (security_barrier = true) AS
 SELECT c.id AS connection_id, c.consumer_id, ca.name AS consumer_name, c.provider_id, pa.name AS provider_name,
        c.tool, s.description AS tool_description, s.scoped, c.why,
        CASE WHEN c.revoked_at IS NOT NULL THEN 'revoked' WHEN c.approved_at IS NOT NULL THEN 'approved' ELSE 'proposed' END AS state,
        c.proposed_at, c.approved_at, c.approved_by, c.revoked_at
   FROM application_connections c
   JOIN applications ca ON ca.id = c.consumer_id
   JOIN applications pa ON pa.id = c.provider_id
   LEFT JOIN application_shares s ON s.application_id = c.provider_id AND s.tool = c.tool
  WHERE (SELECT app_is_super_admin());
CREATE VIEW mcp_application_notifications WITH (security_barrier = true) AS
 SELECT n.id AS notification_id, n.application_id, a.name AS application_name, n.member_id, m.display_name AS member_name,
        n.channel, n.reference, n.created_at, n.attempts, n.sent_at, n.failed_at, n.error,
        CASE WHEN n.sent_at IS NOT NULL THEN 'sent' WHEN n.failed_at IS NOT NULL THEN 'failed' ELSE 'queued' END AS status
   FROM application_notifications n
   JOIN applications a ON a.id = n.application_id
   JOIN members m ON m.id = n.member_id
  WHERE (SELECT app_is_super_admin());
GRANT SELECT ON mcp_application_connections, mcp_application_notifications TO app_rw, app_records_ro;

COMMIT;
