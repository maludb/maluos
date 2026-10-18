-- 009_notifications_tokens.sql
-- Notification (M8; delivered through MaluMail) + personal tokens: the MCP access token
-- (a member's own AI reads community memory AS that member) and the calendar feed token
-- (personal iCal subscription URL, §8.7). Tokens are hashed and revocable (plan §3.1).

BEGIN;

-- --------------------------------------------------------------------------
-- Notification — a message the app sent
-- --------------------------------------------------------------------------
CREATE TABLE notifications (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id     bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,   -- recipient
    kind          text   NOT NULL
                     CHECK (kind IN ('issue_reply','plan_comment','reply_accepted',
                                     'event_changed','event_cancelled','event_reminder',
                                     'exam_reminder','cert_expiring','invite','digest')),
    -- Loose reference to the record that triggered it (no hard FK: entity_type varies).
    entity_type   text,
    entity_id     bigint,
    title         text   NOT NULL,
    body          text,
    email_sent_at timestamptz,                             -- when MaluMail accepted it
    read_at       timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_member_idx ON notifications (member_id, created_at DESC);
CREATE INDEX notifications_unread_idx ON notifications (member_id) WHERE read_at IS NULL;

-- --------------------------------------------------------------------------
-- MCP access token — a member's personal bearer token for the read MCP servers.
-- The server sets app.member_id / app.role from the token, so the member's own AI
-- sees exactly what the member sees in the UI (SaaS Plus+, plan §6).
-- --------------------------------------------------------------------------
CREATE TABLE mcp_access_tokens (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id    bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    label        text   NOT NULL,                          -- "Claude Desktop on my laptop"
    token_hash   text   NOT NULL UNIQUE,                   -- sha256 of the shown-once token
    last_used_at timestamptz,
    expires_at   timestamptz,                              -- null = no expiry
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mcp_tokens_member_idx ON mcp_access_tokens (member_id) WHERE revoked_at IS NULL;

-- --------------------------------------------------------------------------
-- Calendar feed token — serves a personal iCal subscription URL (§8.7).
-- Read-only, single purpose, revocable. The feed shows what this member may see.
-- --------------------------------------------------------------------------
CREATE TABLE calendar_feed_tokens (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id    bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_hash   text   NOT NULL UNIQUE,
    last_fetched_at timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX calendar_feed_member_idx ON calendar_feed_tokens (member_id) WHERE revoked_at IS NULL;

COMMIT;
