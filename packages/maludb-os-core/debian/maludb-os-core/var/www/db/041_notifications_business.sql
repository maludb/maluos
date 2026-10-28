-- 041_notifications_business.sql
-- Notifications & digest for the business modules. The cert-study notification kinds are
-- kept (their modules still run); business kinds are added. Per-kind preferences replace
-- the four notify_* booleans for business notifications. Email delivery state comes from
-- MaluMail (sends + bounce/complaint events) and feeds the suppression list.
-- Questions: N1–N5, DB2.

BEGIN;

ALTER TABLE notifications DROP CONSTRAINT notifications_kind_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN (
    -- cert-study (unchanged)
    'issue_reply', 'plan_comment', 'reply_accepted', 'event_changed', 'event_cancelled',
    'event_reminder', 'exam_reminder', 'cert_expiring', 'invite', 'digest',
    -- business
    'mention', 'comment', 'task_assigned', 'task_due', 'task_overdue',
    'ticket_assigned', 'ticket_reply', 'ticket_sla_warning', 'ticket_sla_breach',
    'appointment_assigned', 'appointment_changed',
    'deal_assigned', 'deal_quiet',
    'invoice_viewed', 'invoice_overdue', 'payment_received', 'payment_failed',
    'refund_requested', 'dispute_opened', 'bill_due',
    'expense_submitted', 'expense_decided',
    'content_review', 'content_published', 'content_failed', 'channel_disconnected',
    'approval_requested', 'approval_decided', 'approval_expiring',
    'agent_escalation', 'agent_budget_warning', 'eval_regression',
    'location_task_update', 'desk_consent_request', 'document_shared',
    'backup_failed', 'system'));

ALTER TABLE notifications
    ADD COLUMN priority      text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    ADD COLUMN action_url    text,                                  -- canonical screen URL
    ADD COLUMN actor_member_id bigint REFERENCES members(id) ON DELETE SET NULL;

-- Per member, per kind: where it goes (N3). Absent row = the kind's default in the app.
CREATE TABLE notification_preferences (
    member_id   bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind        text   NOT NULL,
    channel     text   NOT NULL CHECK (channel IN ('in_app', 'email', 'digest', 'off')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, kind)
);

-- Every email handed to MaluMail and what happened to it (N4, N5).
CREATE TABLE email_messages (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id             bigint REFERENCES members(id) ON DELETE SET NULL,
    to_email              citext NOT NULL,
    notification_id       bigint REFERENCES notifications(id) ON DELETE SET NULL,
    template              text NOT NULL,                        -- 'invoice_send', 'digest', ...
    entity_type           text,
    entity_id             bigint,
    subject               text,
    malumail_message_id   text UNIQUE,
    status                text NOT NULL DEFAULT 'queued'
                              CHECK (status IN ('queued', 'sent', 'delivered', 'opened', 'bounced',
                                                'complained', 'suppressed', 'failed')),
    error                 text,
    sent_at               timestamptz,
    delivered_at          timestamptz,
    opened_at             timestamptz,
    bounced_at            timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX email_messages_member_idx ON email_messages (member_id, created_at DESC);
CREATE INDEX email_messages_entity_idx ON email_messages (entity_type, entity_id);
CREATE INDEX email_messages_problem_idx ON email_messages (created_at DESC)
    WHERE status IN ('bounced', 'complained', 'failed');

CREATE TABLE email_suppressions (
    email          citext PRIMARY KEY,
    reason         text NOT NULL CHECK (reason IN ('bounce', 'complaint', 'unsubscribe', 'manual')),
    source         text NOT NULL DEFAULT 'malumail' CHECK (source IN ('malumail', 'manual')),
    suppressed_at  timestamptz NOT NULL DEFAULT now(),
    lifted_at      timestamptz,
    lifted_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- What went into each digest (N2 "what was in my digest this morning?").
CREATE TABLE digest_sends (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    period_start      timestamptz NOT NULL,
    period_end        timestamptz NOT NULL,
    content           jsonb NOT NULL,                           -- sections + item refs
    email_message_id  bigint REFERENCES email_messages(id) ON DELETE SET NULL,
    sent_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX digest_sends_member_idx ON digest_sends (member_id, sent_at DESC);

COMMIT;
