-- 115: Portal & Forms (docs/build-specs/portal-forms.md). ADDITIVE.
--
-- 1. invitations.share_organization_id — a portal invitation names the company the External
--    person is for; accepting it shares that company with them (record_shares), which is what
--    the views already key an External caller's reach off. NULL for every other invitation.
-- 2. mcp_forms / mcp_form_submissions: columns the screens need, APPENDED as the last columns.
--    WHERE clauses, security barriers and every existing column are unchanged.
-- 3. The Portal application row opens at /forms/ — the insiders' module. /portal is what an
--    External person sees, and no insider "opens" it.
BEGIN;

ALTER TABLE invitations ADD COLUMN IF NOT EXISTS share_organization_id bigint REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS invitations_share_org_idx ON invitations (share_organization_id);

CREATE OR REPLACE VIEW mcp_forms WITH (security_barrier = true) AS
SELECT f.id AS form_id, f.slug, f.name, f.description, f.kind, f.status, f.requires_login,
       f.submit_action, f.department_id, f.pipeline_id, f.ticket_category_id,
       f.assign_member_id, f.success_message, f.submission_count, f.published_at, f.archived_at,
       (SELECT count(*) FROM form_submissions s
         WHERE s.form_id = f.id AND s.status = 'new') AS unprocessed_count,
       f.appointment_type_id, f.notify_member_ids, f.redirect_url, f.spam_protection, f.created_at
FROM forms f
WHERE app_has_module('portal') OR app_is_super_admin() OR app_is_admin_of(f.department_id);

CREATE OR REPLACE VIEW mcp_form_submissions WITH (security_barrier = true) AS
SELECT s.id AS form_submission_id, s.form_id, f.name AS form_name, s.submitted_at, s.data,
       s.status, s.contact_id, s.organization_id, s.ticket_id, s.deal_id, s.appointment_id,
       s.processed_at, s.processed_by, s.note,
       s.submitted_by
FROM form_submissions s JOIN forms f ON f.id = s.form_id
WHERE app_has_module('portal') OR app_is_super_admin() OR app_is_admin_of(f.department_id)
   OR (f.department_id IS NOT NULL AND f.department_id = ANY (app_my_department_ids()))
   OR f.assign_member_id = app_current_member_id();

UPDATE applications SET url = '/forms/', updated_at = now() WHERE app_key = 'portal' AND url = '/portal/';

COMMIT;
