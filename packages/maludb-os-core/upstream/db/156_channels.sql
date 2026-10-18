-- 156: a person's channels to their assistant — Telegram, SMS, email (owner-approved 2026-09-27;
-- docs/build-specs/assistants-and-messaging.md §6, build step 6).
--
-- A channel message becomes an ordinary agent message (db/155) from the person to their own assistant,
-- and so an ordinary run of it. Only a VERIFIED identity is heard: member_channel_identities links a
-- Telegram account, a phone number or an email address to a person by a one-time code; anything from an
-- unlinked sender is dropped and logged. agent_channel_endpoints says which bot, number or mailbox is an
-- agent's, and its credential is a tenant secret (by reference only). A message to a person is delivered
-- on the channel of their latest message on that thread, else their preferred channel, else it waits in
-- the OS; delivered_at / delivery_error record what happened. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/156_channels.sql

BEGIN;

CREATE TABLE member_channel_identities (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id       bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    channel         text NOT NULL CHECK (channel IN ('telegram', 'sms', 'email')),
    address         text,                       -- Telegram user id, E.164 phone, email — set when verified (Telegram) or entered (sms/email)
    chat_ref        text,                       -- where to write back (a Telegram chat id)
    label           text,                       -- what the person sees (@username, the number, the address)
    verify_code_hash text,
    code_expires_at timestamptz,
    verified_at     timestamptz,
    preferred       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    removed_at      timestamptz
);
CREATE UNIQUE INDEX member_channel_identities_live ON member_channel_identities (channel, address)
    WHERE removed_at IS NULL AND verified_at IS NOT NULL;
CREATE UNIQUE INDEX member_channel_identities_one_preferred ON member_channel_identities (member_id)
    WHERE preferred AND removed_at IS NULL;
CREATE INDEX member_channel_identities_member ON member_channel_identities (member_id) WHERE removed_at IS NULL;
COMMENT ON TABLE member_channel_identities IS 'A person''s linked channel identities (db/156). Only a verified one is heard.';

CREATE TABLE agent_channel_endpoints (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    channel         text NOT NULL CHECK (channel IN ('telegram', 'sms', 'email')),
    address         text NOT NULL,              -- the bot's @username, the phone number, the mailbox address
    secret_id       bigint REFERENCES tenant_secrets(id),
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- non-secret settings (a poll offset, a Twilio account SID)
    active          boolean NOT NULL DEFAULT true,
    created_by      bigint REFERENCES members(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX agent_channel_endpoints_live ON agent_channel_endpoints (channel, address) WHERE active;
COMMENT ON TABLE agent_channel_endpoints IS 'Which bot, number or mailbox belongs to which agent (db/156). The credential is a tenant secret, by reference.';

ALTER TABLE agent_messages ADD COLUMN delivery_channel text CHECK (delivery_channel IN ('web', 'telegram', 'sms', 'email'));
ALTER TABLE agent_messages ADD COLUMN delivered_at timestamptz;
ALTER TABLE agent_messages ADD COLUMN delivery_error text;
ALTER TABLE agent_messages ADD COLUMN delivery_attempts integer NOT NULL DEFAULT 0;
CREATE INDEX agent_messages_to_deliver ON agent_messages (created_at)
    WHERE delivered_at IS NULL AND delivery_channel IN ('telegram', 'sms', 'email');

ALTER TABLE member_channel_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_channel_endpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY member_channel_identities_app_rw ON member_channel_identities TO app_rw USING (true) WITH CHECK (true);
CREATE POLICY agent_channel_endpoints_app_rw ON agent_channel_endpoints TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON member_channel_identities, agent_channel_endpoints TO app_rw;

-- Where a message to a PERSON goes: the channel of their latest message on that thread (telegram, sms,
-- email), else their preferred verified channel, else the OS ('web'). Set on insert, for every path.
CREATE FUNCTION agent_messages_delivery_channel() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ch text;
BEGIN
    IF NEW.delivery_channel IS NOT NULL OR (SELECT member_kind FROM members WHERE id = NEW.to_member_id) <> 'human' THEN
        RETURN NEW;
    END IF;
    SELECT m.channel INTO ch FROM agent_messages m
     WHERE m.thread_id = NEW.thread_id AND m.from_member_id = NEW.to_member_id AND m.channel IN ('telegram', 'sms', 'email')
     ORDER BY m.created_at DESC LIMIT 1;
    IF ch IS NULL THEN
        SELECT i.channel INTO ch FROM member_channel_identities i
         WHERE i.member_id = NEW.to_member_id AND i.preferred AND i.verified_at IS NOT NULL AND i.removed_at IS NULL LIMIT 1;
    END IF;
    NEW.delivery_channel := COALESCE(ch, 'web');
    IF NEW.delivery_channel = 'web' THEN
        NEW.delivered_at := now();                  -- the OS is where it is read; nothing to send
    END IF;
    RETURN NEW;
END$$;
CREATE TRIGGER agent_messages_delivery_channel BEFORE INSERT ON agent_messages
    FOR EACH ROW EXECUTE FUNCTION agent_messages_delivery_channel();

COMMIT;
