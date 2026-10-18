-- 057_inbox_email.sql
-- The shared inbox: mailboxes the business receives on (support@, hello@), threaded
-- conversations, inbound and outbound messages, attachments that can be filed into
-- Documents, and rules that route mail into tickets or assignees.
--
-- Outbound delivery still goes through MaluMail and is logged in email_messages (041);
-- this module is the conversation, that table is the delivery record.
-- Questions: IB1-IB11. Module grant: 'inbox'.

BEGIN;

CREATE TABLE mailboxes (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                     text NOT NULL,
    address                  citext NOT NULL UNIQUE,
    kind                     text NOT NULL DEFAULT 'shared' CHECK (kind IN ('shared', 'personal')),
    department_id            bigint REFERENCES departments(id) ON DELETE SET NULL,
    owner_member_id          bigint REFERENCES members(id) ON DELETE SET NULL,
    inbound_kind             text NOT NULL DEFAULT 'forward'
                                 CHECK (inbound_kind IN ('forward', 'imap', 'malumail')),
    inbound_host             text,
    inbound_secret_id        bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    from_name                text,
    signature                text,
    auto_create_tickets      boolean NOT NULL DEFAULT false,
    default_ticket_category_id bigint REFERENCES ticket_categories(id) ON DELETE SET NULL,
    is_active                boolean NOT NULL DEFAULT true,
    last_sync_at             timestamptz,
    last_sync_error          text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mailboxes_department_idx ON mailboxes (department_id);
CREATE INDEX mailboxes_owner_idx      ON mailboxes (owner_member_id);
CREATE INDEX mailboxes_secret_idx     ON mailboxes (inbound_secret_id);
CREATE INDEX mailboxes_category_idx   ON mailboxes (default_ticket_category_id);

CREATE TABLE mail_threads (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mailbox_id          bigint NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
    subject             text NOT NULL DEFAULT '(no subject)',
    organization_id     bigint REFERENCES organizations(id) ON DELETE SET NULL,
    contact_id          bigint REFERENCES contacts(id) ON DELETE SET NULL,
    ticket_id           bigint REFERENCES tickets(id) ON DELETE SET NULL,
    deal_id             bigint REFERENCES deals(id) ON DELETE SET NULL,
    assigned_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,   -- human or agent
    department_id       bigint REFERENCES departments(id) ON DELETE SET NULL,
    status              text NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'pending', 'closed', 'spam')),
    is_starred          boolean NOT NULL DEFAULT false,
    message_count       integer NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    first_message_at    timestamptz,
    last_message_at     timestamptz,
    last_direction      text CHECK (last_direction IN ('inbound', 'outbound')),
    closed_at           timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mail_threads_box_idx      ON mail_threads (mailbox_id, status, last_message_at DESC);
CREATE INDEX mail_threads_assigned_idx ON mail_threads (assigned_member_id, status);
CREATE INDEX mail_threads_org_idx      ON mail_threads (organization_id);
CREATE INDEX mail_threads_contact_idx  ON mail_threads (contact_id);
CREATE INDEX mail_threads_ticket_idx   ON mail_threads (ticket_id);
CREATE INDEX mail_threads_deal_idx     ON mail_threads (deal_id);
CREATE INDEX mail_threads_dept_idx     ON mail_threads (department_id);

CREATE TABLE mail_messages (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id         bigint NOT NULL REFERENCES mail_threads(id) ON DELETE CASCADE,
    mailbox_id        bigint NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
    direction         text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    message_id        text,                                    -- RFC 5322 Message-ID
    in_reply_to       text,
    from_address      citext NOT NULL,
    from_name         text,
    to_addresses      citext[] NOT NULL DEFAULT '{}',
    cc_addresses      citext[] NOT NULL DEFAULT '{}',
    subject           text,
    body_text         text,
    body_html         text,
    snippet           text,
    sent_at           timestamptz,
    received_at       timestamptz,
    sent_by_member_id bigint REFERENCES members(id) ON DELETE SET NULL,   -- outbound author
    email_message_id  bigint REFERENCES email_messages(id) ON DELETE SET NULL,  -- MaluMail delivery
    is_draft          boolean NOT NULL DEFAULT false,
    has_attachments   boolean NOT NULL DEFAULT false,
    spam_score        numeric(5,2),
    search            tsvector,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX mail_messages_msgid_idx ON mail_messages (mailbox_id, message_id)
    WHERE message_id IS NOT NULL;
CREATE INDEX mail_messages_thread_idx ON mail_messages (thread_id, coalesce(sent_at, received_at));
CREATE INDEX mail_messages_search_idx ON mail_messages USING gin (search);
CREATE INDEX mail_messages_from_idx   ON mail_messages (from_address);
CREATE INDEX mail_messages_box_idx    ON mail_messages (mailbox_id);
CREATE INDEX mail_messages_sender_idx ON mail_messages (sent_by_member_id);
CREATE INDEX mail_messages_delivery_idx ON mail_messages (email_message_id);

CREATE OR REPLACE FUNCTION mail_messages_search_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.search := setweight(to_tsvector('english', coalesce(NEW.subject, '')), 'A')
               || setweight(to_tsvector('english', coalesce(NEW.from_name, '')), 'B')
               || setweight(to_tsvector('english', coalesce(NEW.body_text, '')), 'C');
    RETURN NEW;
END$$;
CREATE TRIGGER mail_messages_search BEFORE INSERT OR UPDATE ON mail_messages
    FOR EACH ROW EXECUTE FUNCTION mail_messages_search_update();

CREATE TABLE mail_attachments (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mail_message_id  bigint NOT NULL REFERENCES mail_messages(id) ON DELETE CASCADE,
    filename         text NOT NULL,
    mime_type        text,
    size_bytes       bigint CHECK (size_bytes >= 0),
    storage_path     text NOT NULL,
    sha256           text,
    document_id      bigint REFERENCES documents(id) ON DELETE SET NULL,   -- filed into Documents
    filed_at         timestamptz,
    filed_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mail_attachments_message_idx  ON mail_attachments (mail_message_id);
CREATE INDEX mail_attachments_document_idx ON mail_attachments (document_id);
CREATE INDEX mail_attachments_filed_by_idx ON mail_attachments (filed_by);

-- Per-member read state: a shared inbox is read by several people.
CREATE TABLE mail_thread_reads (
    thread_id  bigint NOT NULL REFERENCES mail_threads(id) ON DELETE CASCADE,
    member_id  bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    read_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (thread_id, member_id)
);
CREATE INDEX mail_thread_reads_member_idx ON mail_thread_reads (member_id);

CREATE TABLE mail_rules (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mailbox_id     bigint NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
    name           text NOT NULL,
    sort_order     integer NOT NULL DEFAULT 0,
    match_field    text NOT NULL CHECK (match_field IN ('from', 'to', 'subject', 'body', 'any')),
    match_kind     text NOT NULL DEFAULT 'contains'
                       CHECK (match_kind IN ('contains', 'equals', 'starts_with', 'regex')),
    match_value    text NOT NULL,
    action         text NOT NULL CHECK (action IN ('assign', 'tag', 'create_ticket',
                                                   'link_organization', 'close', 'mark_spam')),
    action_params  jsonb NOT NULL DEFAULT '{}',
    stop_after     boolean NOT NULL DEFAULT false,
    active         boolean NOT NULL DEFAULT true,
    created_by     bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mail_rules_box_idx ON mail_rules (mailbox_id, sort_order) WHERE active;
CREATE INDEX mail_rules_created_by_idx ON mail_rules (created_by);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['mailboxes', 'mail_threads', 'mail_messages', 'mail_attachments',
                             'mail_thread_reads', 'mail_rules'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['mailboxes', 'mail_threads', 'mail_messages', 'mail_rules'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- Visibility: the inbox module, narrowed by the mailbox's department; a personal mailbox is
-- its owner's. Assignment always wins, so an agent handling a thread can read it.
CREATE OR REPLACE FUNCTION app_can_see_mailbox(p_mailbox_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM mailboxes m
         WHERE m.id = p_mailbox_id
           AND (app_is_super_admin()
                OR app_is_admin_of(m.department_id)
                OR m.owner_member_id = app_current_member_id()
                OR (app_has_module('inbox')
                    AND (m.department_id IS NULL
                         OR m.department_id = ANY (app_my_department_ids())))));
$$;
GRANT EXECUTE ON FUNCTION app_can_see_mailbox(bigint) TO app_rw, app_records_ro, app_activity_ro;

CREATE OR REPLACE VIEW mcp_mailboxes WITH (security_barrier = true) AS
SELECT m.id AS mailbox_id, m.name, m.address::text, m.kind, m.department_id,
       d.name::text AS department_name, m.owner_member_id, m.inbound_kind, m.from_name,
       m.auto_create_tickets, m.default_ticket_category_id, m.is_active, m.last_sync_at,
       (m.last_sync_error IS NOT NULL) AS has_sync_error,
       (SELECT count(*) FROM mail_threads t
         WHERE t.mailbox_id = m.id AND t.status = 'open') AS open_threads
FROM mailboxes m LEFT JOIN departments d ON d.id = m.department_id
WHERE app_can_see_mailbox(m.id);

CREATE OR REPLACE VIEW mcp_mail_threads WITH (security_barrier = true) AS
SELECT t.id AS mail_thread_id, t.mailbox_id, m.name AS mailbox_name, t.subject,
       t.organization_id, o.name AS organization_name, t.contact_id, t.ticket_id, t.deal_id,
       t.assigned_member_id, am.display_name AS assigned_to, t.department_id, t.status,
       t.is_starred, t.message_count, t.first_message_at, t.last_message_at, t.last_direction,
       (SELECT r.read_at FROM mail_thread_reads r
         WHERE r.thread_id = t.id AND r.member_id = app_current_member_id()) AS my_read_at
FROM mail_threads t
JOIN mailboxes m         ON m.id = t.mailbox_id
LEFT JOIN organizations o ON o.id = t.organization_id
LEFT JOIN members am      ON am.id = t.assigned_member_id
WHERE app_can_see_mailbox(t.mailbox_id) OR t.assigned_member_id = app_current_member_id();

CREATE OR REPLACE VIEW mcp_mail_messages WITH (security_barrier = true) AS
SELECT ms.id AS mail_message_id, ms.thread_id, ms.mailbox_id, ms.direction, ms.from_address::text,
       ms.from_name, ms.to_addresses::text[] AS to_addresses, ms.cc_addresses::text[] AS cc_addresses,
       ms.subject, ms.body_text, ms.snippet, ms.sent_at, ms.received_at, ms.sent_by_member_id,
       ms.is_draft, ms.has_attachments, ms.spam_score
FROM mail_messages ms
JOIN mail_threads t ON t.id = ms.thread_id
WHERE app_can_see_mailbox(ms.mailbox_id) OR t.assigned_member_id = app_current_member_id();

CREATE OR REPLACE VIEW mcp_mail_attachments WITH (security_barrier = true) AS
SELECT a.id AS mail_attachment_id, a.mail_message_id, ms.thread_id, a.filename, a.mime_type,
       a.size_bytes, a.document_id, a.filed_at
FROM mail_attachments a
JOIN mail_messages ms ON ms.id = a.mail_message_id
JOIN mail_threads t   ON t.id = ms.thread_id
WHERE app_can_see_mailbox(ms.mailbox_id) OR t.assigned_member_id = app_current_member_id();

CREATE OR REPLACE VIEW mcp_mail_rules WITH (security_barrier = true) AS
SELECT r.id AS mail_rule_id, r.mailbox_id, m.name AS mailbox_name, r.name, r.sort_order,
       r.match_field, r.match_kind, r.match_value, r.action, r.action_params, r.stop_after, r.active
FROM mail_rules r JOIN mailboxes m ON m.id = r.mailbox_id
WHERE app_can_see_mailbox(r.mailbox_id);

GRANT SELECT ON mcp_mailboxes, mcp_mail_threads, mcp_mail_messages, mcp_mail_attachments,
    mcp_mail_rules
TO app_records_ro;

COMMIT;
