-- 114: what the built-in signing page needs to be evidence (docs/build-specs/signatures.md). ADDITIVE.
--
-- db/060 modelled requests, signers and events but not WHAT was signed or HOW: no document hash,
-- no typed name, no consent, no drawn signature, no user agent, and nothing for the executed
-- copy's render. Columns are nullable with no default; the three views get columns APPENDED
-- (security barrier, WHERE clauses and existing columns unchanged). No view ever carries a
-- token, a token hash or an image path.
BEGIN;

ALTER TABLE signature_requests
    ADD COLUMN IF NOT EXISTS document_version_id      bigint REFERENCES document_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS document_sha256          text,
    ADD COLUMN IF NOT EXISTS executed_render_error    text,
    ADD COLUMN IF NOT EXISTS render_token_hash        text,
    ADD COLUMN IF NOT EXISTS render_token_expires_at  timestamptz;
CREATE INDEX IF NOT EXISTS signature_requests_docver_idx ON signature_requests (document_version_id);
CREATE INDEX IF NOT EXISTS signature_requests_render_idx ON signature_requests (render_token_hash) WHERE render_token_hash IS NOT NULL;

ALTER TABLE signature_signers
    ADD COLUMN IF NOT EXISTS signed_name           text,
    ADD COLUMN IF NOT EXISTS consent_at            timestamptz,
    ADD COLUMN IF NOT EXISTS signature_image_path  text,
    ADD COLUMN IF NOT EXISTS user_agent            text;
CREATE INDEX IF NOT EXISTS signature_signers_token_idx ON signature_signers (access_token_hash) WHERE access_token_hash IS NOT NULL;

CREATE OR REPLACE VIEW mcp_signature_requests WITH (security_barrier = true) AS
SELECT r.id AS signature_request_id, r.provider_id, r.document_id, r.entity_type, r.entity_id,
       r.organization_id, o.name AS organization_name, r.department_id, r.subject,
       r.signing_order, r.status, r.sent_at, r.completed_at, r.expires_at, r.signed_document_id,
       r.voided_reason, r.owner_member_id, r.created_at,
       (SELECT count(*) FROM signature_signers s WHERE s.request_id = r.id) AS signer_count,
       (SELECT count(*) FROM signature_signers s WHERE s.request_id = r.id
         AND s.status = 'signed') AS signed_count,
       r.document_version_id, r.document_sha256, r.executed_render_error, r.message, r.reminder_days
FROM signature_requests r LEFT JOIN organizations o ON o.id = r.organization_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

CREATE OR REPLACE VIEW mcp_signature_signers WITH (security_barrier = true) AS
SELECT s.id AS signature_signer_id, s.request_id, s.sign_order, s.role, s.member_id,
       s.contact_id, s.name, s.email::text, s.status, s.sent_at, s.viewed_at, s.signed_at,
       s.declined_at, s.decline_reason,
       s.signed_name, host(s.ip_address) AS ip_address, (s.signature_image_path IS NOT NULL) AS has_drawn_signature
FROM signature_signers s
JOIN signature_requests r ON r.id = s.request_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

CREATE OR REPLACE VIEW mcp_signature_events WITH (security_barrier = true) AS
SELECT e.id AS signature_event_id, e.request_id, e.signer_id, e.kind, e.detail, e.occurred_at,
       host(e.ip_address) AS ip_address
FROM signature_events e
JOIN signature_requests r ON r.id = e.request_id
WHERE app_can_see('signatures', r.owner_member_id, r.department_id, 'signature_request', r.id,
                  r.organization_id);

COMMIT;
