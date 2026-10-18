-- 061_portal_forms.sql
-- The customer portal and the forms that feed it: public forms (contact, intake, request)
-- whose submissions become contacts, tickets or deals, and the portal pages an External
-- member sees when they sign in.
--
-- Portal access itself is the existing External business role plus record_shares (030) --
-- this module adds what the outside world can send IN, and what it is shown.
-- Questions: PF1-PF10. Module grant: 'portal'.

BEGIN;

CREATE TABLE forms (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug                  text NOT NULL UNIQUE,                -- public URL key
    name                  text NOT NULL,
    description           text,
    kind                  text NOT NULL DEFAULT 'contact'
                              CHECK (kind IN ('contact', 'intake', 'request', 'survey',
                                              'booking', 'other')),
    status                text NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'published', 'closed')),
    requires_login        boolean NOT NULL DEFAULT false,      -- portal-only form
    submit_action         text NOT NULL DEFAULT 'none'
                              CHECK (submit_action IN ('none', 'create_contact', 'create_ticket',
                                                       'create_deal', 'create_appointment')),
    department_id         bigint REFERENCES departments(id) ON DELETE SET NULL,
    pipeline_id           bigint REFERENCES pipelines(id) ON DELETE SET NULL,
    ticket_category_id    bigint REFERENCES ticket_categories(id) ON DELETE SET NULL,
    appointment_type_id   bigint REFERENCES appointment_types(id) ON DELETE SET NULL,
    assign_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,   -- human or agent
    notify_member_ids     bigint[] NOT NULL DEFAULT '{}',
    success_message       text,
    redirect_url          text,
    spam_protection       boolean NOT NULL DEFAULT true,
    submission_count      integer NOT NULL DEFAULT 0 CHECK (submission_count >= 0),
    published_at          timestamptz,
    archived_at           timestamptz,
    created_by            bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX forms_status_idx ON forms (status) WHERE archived_at IS NULL;
CREATE INDEX forms_dept_idx   ON forms (department_id);
CREATE INDEX forms_pipeline_idx ON forms (pipeline_id);
CREATE INDEX forms_category_idx ON forms (ticket_category_id);
CREATE INDEX forms_apptype_idx ON forms (appointment_type_id);
CREATE INDEX forms_assign_idx  ON forms (assign_member_id);
CREATE INDEX forms_created_by_idx ON forms (created_by);

CREATE TABLE form_fields (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id       bigint NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    sort_order    integer NOT NULL DEFAULT 0,
    field_key     text NOT NULL,
    label         text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('text', 'textarea', 'email', 'phone', 'number',
                                                'date', 'select', 'multiselect', 'checkbox',
                                                'file', 'hidden')),
    required      boolean NOT NULL DEFAULT false,
    options       jsonb NOT NULL DEFAULT '[]',
    placeholder   text,
    help_text     text,
    maps_to       text,                                        -- 'contact.email', 'ticket.subject'
    validation    text,                                        -- regex or rule name
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (form_id, field_key)
);
CREATE INDEX form_fields_form_idx ON form_fields (form_id, sort_order);

CREATE TABLE form_submissions (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id           bigint NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    submitted_at      timestamptz NOT NULL DEFAULT now(),
    submitted_by      bigint REFERENCES members(id) ON DELETE SET NULL,   -- portal login, if any
    data              jsonb NOT NULL DEFAULT '{}',
    source_ip         inet,
    user_agent        text,
    status            text NOT NULL DEFAULT 'new'
                          CHECK (status IN ('new', 'processed', 'spam', 'rejected')),
    contact_id        bigint REFERENCES contacts(id) ON DELETE SET NULL,
    organization_id   bigint REFERENCES organizations(id) ON DELETE SET NULL,
    ticket_id         bigint REFERENCES tickets(id) ON DELETE SET NULL,
    deal_id           bigint REFERENCES deals(id) ON DELETE SET NULL,
    appointment_id    bigint REFERENCES appointments(id) ON DELETE SET NULL,
    document_ids      bigint[] NOT NULL DEFAULT '{}',          -- uploaded files, filed to Documents
    processed_at      timestamptz,
    processed_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    note              text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX form_submissions_form_idx   ON form_submissions (form_id, submitted_at DESC);
CREATE INDEX form_submissions_new_idx    ON form_submissions (status, submitted_at DESC)
    WHERE status = 'new';
CREATE INDEX form_submissions_contact_idx ON form_submissions (contact_id);
CREATE INDEX form_submissions_org_idx    ON form_submissions (organization_id);
CREATE INDEX form_submissions_ticket_idx ON form_submissions (ticket_id);
CREATE INDEX form_submissions_deal_idx   ON form_submissions (deal_id);
CREATE INDEX form_submissions_appt_idx   ON form_submissions (appointment_id);
CREATE INDEX form_submissions_by_idx     ON form_submissions (submitted_by);
CREATE INDEX form_submissions_processed_by_idx ON form_submissions (processed_by);

-- What a signed-in External member sees in the portal, per section. Sharing individual
-- records still works through record_shares; this decides which sections exist at all.
CREATE TABLE portal_settings (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    is_enabled            boolean NOT NULL DEFAULT false,
    welcome_message       text,
    show_invoices         boolean NOT NULL DEFAULT true,
    show_quotes           boolean NOT NULL DEFAULT true,
    show_tickets          boolean NOT NULL DEFAULT true,
    show_projects         boolean NOT NULL DEFAULT false,
    show_documents        boolean NOT NULL DEFAULT true,
    show_appointments     boolean NOT NULL DEFAULT false,
    allow_ticket_create   boolean NOT NULL DEFAULT true,
    allow_online_payment  boolean NOT NULL DEFAULT true,
    support_form_id       bigint REFERENCES forms(id) ON DELETE SET NULL,
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX portal_settings_singleton_idx ON portal_settings ((true));
CREATE INDEX portal_settings_form_idx ON portal_settings (support_form_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['forms', 'form_fields', 'form_submissions', 'portal_settings'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

CREATE OR REPLACE VIEW mcp_forms WITH (security_barrier = true) AS
SELECT f.id AS form_id, f.slug, f.name, f.description, f.kind, f.status, f.requires_login,
       f.submit_action, f.department_id, f.pipeline_id, f.ticket_category_id,
       f.assign_member_id, f.success_message, f.submission_count, f.published_at, f.archived_at,
       (SELECT count(*) FROM form_submissions s
         WHERE s.form_id = f.id AND s.status = 'new') AS unprocessed_count
FROM forms f
WHERE app_has_module('portal') OR app_is_super_admin() OR app_is_admin_of(f.department_id);

CREATE OR REPLACE VIEW mcp_form_fields WITH (security_barrier = true) AS
SELECT ff.id AS form_field_id, ff.form_id, ff.sort_order, ff.field_key, ff.label, ff.kind,
       ff.required, ff.options, ff.placeholder, ff.help_text, ff.maps_to
FROM form_fields ff JOIN forms f ON f.id = ff.form_id
WHERE app_has_module('portal') OR app_is_super_admin() OR app_is_admin_of(f.department_id);

CREATE OR REPLACE VIEW mcp_form_submissions WITH (security_barrier = true) AS
SELECT s.id AS form_submission_id, s.form_id, f.name AS form_name, s.submitted_at, s.data,
       s.status, s.contact_id, s.organization_id, s.ticket_id, s.deal_id, s.appointment_id,
       s.processed_at, s.processed_by, s.note
FROM form_submissions s JOIN forms f ON f.id = s.form_id
WHERE app_has_module('portal') OR app_is_super_admin() OR app_is_admin_of(f.department_id)
   OR (f.department_id IS NOT NULL AND f.department_id = ANY (app_my_department_ids()))
   OR f.assign_member_id = app_current_member_id();

CREATE OR REPLACE VIEW mcp_portal_settings WITH (security_barrier = true) AS
SELECT id AS portal_settings_id, is_enabled, welcome_message, show_invoices, show_quotes,
       show_tickets, show_projects, show_documents, show_appointments, allow_ticket_create,
       allow_online_payment, support_form_id
FROM portal_settings WHERE app_is_insider();

GRANT SELECT ON mcp_forms, mcp_form_fields, mcp_form_submissions, mcp_portal_settings
TO app_records_ro;

INSERT INTO portal_settings (is_enabled) SELECT false
WHERE NOT EXISTS (SELECT 1 FROM portal_settings);

COMMIT;
