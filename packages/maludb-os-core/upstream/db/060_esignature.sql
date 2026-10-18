-- 060_esignature.sql
-- E-signature: send a document (quote, contract, SOW) for signing, track each signer, and
-- file the executed copy back into Documents. A provider adapter as in 038, so DocuSign,
-- Dropbox Sign or the built-in signing page are all just rows.
-- Questions: SG1-SG8. Module grant: 'signatures'.

BEGIN;

CREATE TABLE signature_providers (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL UNIQUE,
    provider      text NOT NULL CHECK (provider IN ('internal', 'docusign', 'dropbox_sign',
                                                    'adobe_sign', 'other')),
    secret_id     bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    webhook_secret_id bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    config        jsonb NOT NULL DEFAULT '{}',
    is_default    boolean NOT NULL DEFAULT false,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX signature_providers_default_idx ON signature_providers ((true))
    WHERE is_default AND status = 'active';
CREATE INDEX signature_providers_secret_idx ON signature_providers (secret_id);
CREATE INDEX signature_providers_wh_idx     ON signature_providers (webhook_secret_id);

CREATE TABLE signature_requests (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id            bigint REFERENCES signature_providers(id) ON DELETE SET NULL,
    document_id            bigint REFERENCES documents(id) ON DELETE SET NULL,     -- what is signed
    entity_type            text,                                                   -- 'quote', 'contract'
    entity_id              bigint,
    organization_id        bigint REFERENCES organizations(id) ON DELETE SET NULL,
    department_id          bigint REFERENCES departments(id) ON DELETE SET NULL,
    subject                text NOT NULL,
    message                text,
    signing_order          text NOT NULL DEFAULT 'parallel'
                               CHECK (signing_order IN ('parallel', 'sequential')),
    status                 text NOT NULL DEFAULT 'draft'
                               CHECK (status IN ('draft', 'sent', 'partially_signed', 'completed',
                                                 'declined', 'voided', 'expired')),
    external_ref           text,
    sent_at                timestamptz,
    completed_at           timestamptz,
    expires_at             timestamptz,
    reminder_days          integer CHECK (reminder_days > 0),
    signed_document_id     bigint REFERENCES documents(id) ON DELETE SET NULL,     -- executed copy
    voided_reason          text,
    owner_member_id        bigint REFERENCES members(id) ON DELETE SET NULL,
    created_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signature_requests_entity_idx ON signature_requests (entity_type, entity_id);
CREATE INDEX signature_requests_status_idx ON signature_requests (status, sent_at DESC);
CREATE INDEX signature_requests_org_idx    ON signature_requests (organization_id);
CREATE INDEX signature_requests_doc_idx    ON signature_requests (document_id);
CREATE INDEX signature_requests_signed_idx ON signature_requests (signed_document_id);
CREATE INDEX signature_requests_owner_idx  ON signature_requests (owner_member_id);
CREATE INDEX signature_requests_provider_idx ON signature_requests (provider_id);
CREATE INDEX signature_requests_dept_idx   ON signature_requests (department_id);
CREATE INDEX signature_requests_created_by_idx ON signature_requests (created_by);

CREATE TABLE signature_signers (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id          bigint NOT NULL REFERENCES signature_requests(id) ON DELETE CASCADE,
    sign_order          integer NOT NULL DEFAULT 1 CHECK (sign_order > 0),
    role                text NOT NULL DEFAULT 'signer'
                            CHECK (role IN ('signer', 'approver', 'cc', 'witness')),
    member_id           bigint REFERENCES members(id) ON DELETE SET NULL,   -- our side
    contact_id          bigint REFERENCES contacts(id) ON DELETE SET NULL,  -- their side
    name                text NOT NULL,
    email               citext NOT NULL,
    status              text NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sent', 'viewed', 'signed',
                                              'declined', 'bounced')),
    sent_at             timestamptz,
    viewed_at           timestamptz,
    signed_at           timestamptz,
    declined_at         timestamptz,
    decline_reason      text,
    ip_address          inet,
    access_token_hash   text,                                  -- internal provider signing link
    access_expires_at   timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signature_signers_request_idx ON signature_signers (request_id, sign_order);
CREATE INDEX signature_signers_contact_idx ON signature_signers (contact_id);
CREATE INDEX signature_signers_member_idx  ON signature_signers (member_id);
CREATE INDEX signature_signers_email_idx   ON signature_signers (email);

-- Append-only audit trail; the legal value of an e-signature is its history.
CREATE TABLE signature_events (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id   bigint NOT NULL REFERENCES signature_requests(id) ON DELETE CASCADE,
    signer_id    bigint REFERENCES signature_signers(id) ON DELETE SET NULL,
    kind         text NOT NULL CHECK (kind IN ('created', 'sent', 'delivered', 'viewed',
                                               'signed', 'declined', 'reminded', 'completed',
                                               'voided', 'expired', 'webhook', 'error')),
    detail       jsonb NOT NULL DEFAULT '{}',
    ip_address   inet,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signature_events_request_idx ON signature_events (request_id, occurred_at);
CREATE INDEX signature_events_signer_idx  ON signature_events (signer_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['signature_providers', 'signature_requests', 'signature_signers',
                             'signature_events'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['signature_providers', 'signature_requests', 'signature_signers'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

CREATE OR REPLACE VIEW mcp_signature_providers WITH (security_barrier = true) AS
SELECT id AS signature_provider_id, name, provider, is_default, status,
       (secret_id IS NOT NULL) AS has_credential
FROM signature_providers
WHERE app_has_module('signatures') OR app_is_super_admin();

CREATE OR REPLACE VIEW mcp_signature_requests WITH (security_barrier = true) AS
SELECT r.id AS signature_request_id, r.provider_id, r.document_id, r.entity_type, r.entity_id,
       r.organization_id, o.name AS organization_name, r.department_id, r.subject,
       r.signing_order, r.status, r.sent_at, r.completed_at, r.expires_at, r.signed_document_id,
       r.voided_reason, r.owner_member_id, r.created_at,
       (SELECT count(*) FROM signature_signers s WHERE s.request_id = r.id) AS signer_count,
       (SELECT count(*) FROM signature_signers s WHERE s.request_id = r.id
         AND s.status = 'signed') AS signed_count
FROM signature_requests r LEFT JOIN organizations o ON o.id = r.organization_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

CREATE OR REPLACE VIEW mcp_signature_signers WITH (security_barrier = true) AS
SELECT s.id AS signature_signer_id, s.request_id, s.sign_order, s.role, s.member_id,
       s.contact_id, s.name, s.email::text, s.status, s.sent_at, s.viewed_at, s.signed_at,
       s.declined_at, s.decline_reason
FROM signature_signers s
JOIN signature_requests r ON r.id = s.request_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

CREATE OR REPLACE VIEW mcp_signature_events WITH (security_barrier = true) AS
SELECT e.id AS signature_event_id, e.request_id, e.signer_id, e.kind, e.detail, e.occurred_at
FROM signature_events e
JOIN signature_requests r ON r.id = e.request_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

GRANT SELECT ON mcp_signature_providers, mcp_signature_requests, mcp_signature_signers,
    mcp_signature_events
TO app_records_ro;

COMMIT;
