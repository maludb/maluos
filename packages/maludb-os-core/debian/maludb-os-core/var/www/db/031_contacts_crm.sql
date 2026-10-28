-- 031_contacts_crm.sql
-- Contacts & CRM — the exemplar slice. Organizations, people, pipelines, deals,
-- interactions. Questions: C1–C16, DB4, S7 inputs.
-- source_campaign_id / source_content_item_id FKs are added in 040_content_social.sql.

BEGIN;

-- --------------------------------------------------------------------------
-- Organization — a company we deal with (customer, vendor, lead, partner)
-- --------------------------------------------------------------------------
CREATE TABLE organizations (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 text NOT NULL,
    legal_name           text,
    website              text,
    email                citext,
    phone                text,
    industry             text,
    address              jsonb,                              -- {line1,line2,city,region,postal,country}
    tax_id               text,
    relationship_types   text[] NOT NULL DEFAULT '{}'
                            CHECK (relationship_types <@ ARRAY['customer','vendor','lead','partner']::text[]),
    owner_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    source               text,                               -- 'referral', 'website', 'content', ... (C12)
    source_campaign_id   bigint,                             -- FK in 040
    source_content_item_id bigint,                           -- FK in 040
    payment_terms_days   integer CHECK (payment_terms_days >= 0),  -- null = business default
    currency             char(3),                            -- null = business base currency
    notes                text,
    merged_into_id       bigint REFERENCES organizations(id) ON DELETE SET NULL,   -- C11, C15
    anonymized_at        timestamptz,                        -- right-to-be-forgotten
    archived_at          timestamptz,
    search_tsv           tsvector,
    created_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX organizations_name_trgm      ON organizations USING gin (name gin_trgm_ops);
CREATE INDEX organizations_email_idx      ON organizations (email);
CREATE INDEX organizations_types_idx      ON organizations USING gin (relationship_types);
CREATE INDEX organizations_owner_idx      ON organizations (owner_member_id);
CREATE INDEX organizations_department_idx ON organizations (department_id);
CREATE INDEX organizations_search_idx     ON organizations USING gin (search_tsv);

-- --------------------------------------------------------------------------
-- Contact — a person (may belong to an organization, may have a portal login)
-- --------------------------------------------------------------------------
CREATE TABLE contacts (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      bigint REFERENCES organizations(id) ON DELETE SET NULL,
    first_name           text,
    last_name            text,
    full_name            text NOT NULL,
    email                citext,
    phone                text,
    mobile               text,
    job_title            text,
    is_primary_contact   boolean NOT NULL DEFAULT false,     -- C2
    relationship_types   text[] NOT NULL DEFAULT '{}'
                            CHECK (relationship_types <@ ARRAY['customer','vendor','lead','partner']::text[]),
    owner_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    source               text,
    source_campaign_id   bigint,                             -- FK in 040
    source_content_item_id bigint,                           -- FK in 040
    portal_member_id     bigint UNIQUE REFERENCES members(id) ON DELETE SET NULL,  -- External login (C16)
    address              jsonb,
    notes                text,
    merged_into_id       bigint REFERENCES contacts(id) ON DELETE SET NULL,
    anonymized_at        timestamptz,
    archived_at          timestamptz,
    search_tsv           tsvector,
    created_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX contacts_org_idx         ON contacts (organization_id);
CREATE UNIQUE INDEX contacts_primary_per_org_idx ON contacts (organization_id)
    WHERE is_primary_contact AND archived_at IS NULL AND organization_id IS NOT NULL;
CREATE INDEX contacts_name_trgm       ON contacts USING gin (full_name gin_trgm_ops);
CREATE INDEX contacts_email_idx       ON contacts (email);
CREATE INDEX contacts_phone_idx       ON contacts (phone);
CREATE INDEX contacts_types_idx       ON contacts USING gin (relationship_types);
CREATE INDEX contacts_owner_idx       ON contacts (owner_member_id);
CREATE INDEX contacts_search_idx      ON contacts USING gin (search_tsv);

-- --------------------------------------------------------------------------
-- Pipelines + stages
-- --------------------------------------------------------------------------
CREATE TABLE pipelines (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    is_default   boolean NOT NULL DEFAULT false,
    archived_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX pipelines_one_default_idx ON pipelines ((true)) WHERE is_default;

CREATE TABLE deal_stages (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_id  bigint NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    name         text NOT NULL,
    stage_kind   text NOT NULL DEFAULT 'open' CHECK (stage_kind IN ('open', 'won', 'lost')),
    probability  numeric(5,2) NOT NULL DEFAULT 0 CHECK (probability BETWEEN 0 AND 100),
    sort_order   integer NOT NULL DEFAULT 0,
    archived_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pipeline_id, name)
);

-- --------------------------------------------------------------------------
-- Deal
-- --------------------------------------------------------------------------
CREATE TABLE deals (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title                text NOT NULL,
    organization_id      bigint REFERENCES organizations(id) ON DELETE SET NULL,
    primary_contact_id   bigint REFERENCES contacts(id) ON DELETE SET NULL,
    pipeline_id          bigint NOT NULL REFERENCES pipelines(id) ON DELETE RESTRICT,
    stage_id             bigint NOT NULL REFERENCES deal_stages(id) ON DELETE RESTRICT,
    stage_entered_at     timestamptz NOT NULL DEFAULT now(),   -- C13 fast path; full history in activity
    value                numeric(14,2) NOT NULL DEFAULT 0 CHECK (value >= 0),
    currency             char(3) NOT NULL,
    probability_override numeric(5,2) CHECK (probability_override BETWEEN 0 AND 100),
    expected_close_date  date,
    closed_at            timestamptz,                         -- set on won/lost
    lost_reason          text,
    owner_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    source               text,
    source_campaign_id   bigint,                              -- FK in 040
    source_content_item_id bigint,                            -- FK in 040
    description          text,
    archived_at          timestamptz,
    search_tsv           tsvector,
    created_by           bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX deals_stage_idx      ON deals (pipeline_id, stage_id) WHERE archived_at IS NULL;
CREATE INDEX deals_close_idx      ON deals (expected_close_date) WHERE closed_at IS NULL;
CREATE INDEX deals_org_idx        ON deals (organization_id);
CREATE INDEX deals_owner_idx      ON deals (owner_member_id);
CREATE INDEX deals_department_idx ON deals (department_id);
CREATE INDEX deals_search_idx     ON deals USING gin (search_tsv);

-- --------------------------------------------------------------------------
-- Interaction — a call, email, meeting, message or note (C6, C8, C9)
-- --------------------------------------------------------------------------
CREATE TABLE interactions (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('call', 'email', 'meeting', 'message', 'note')),
    direction         text CHECK (direction IN ('inbound', 'outbound')),
    occurred_at       timestamptz NOT NULL DEFAULT now(),
    organization_id   bigint REFERENCES organizations(id) ON DELETE CASCADE,
    contact_id        bigint REFERENCES contacts(id) ON DELETE CASCADE,
    deal_id           bigint REFERENCES deals(id) ON DELETE SET NULL,
    member_id         bigint REFERENCES members(id) ON DELETE SET NULL,    -- who on our side
    subject           text,
    body              text,
    duration_minutes  integer CHECK (duration_minutes >= 0),
    search_tsv        tsvector,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (organization_id IS NOT NULL OR contact_id IS NOT NULL OR deal_id IS NOT NULL)
);
CREATE INDEX interactions_org_idx     ON interactions (organization_id, occurred_at DESC);
CREATE INDEX interactions_contact_idx ON interactions (contact_id, occurred_at DESC);
CREATE INDEX interactions_deal_idx    ON interactions (deal_id, occurred_at DESC);
CREATE INDEX interactions_search_idx  ON interactions USING gin (search_tsv);

-- --------------------------------------------------------------------------
-- Full-text search maintenance
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION organizations_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.name, '') || ' ' || coalesce(NEW.legal_name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.email::text, '') || ' ' || coalesce(NEW.website, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.notes, '')), 'C');
    RETURN NEW;
END$$;
CREATE TRIGGER organizations_tsv_trg BEFORE INSERT OR UPDATE OF name, legal_name, email, website, notes
    ON organizations FOR EACH ROW EXECUTE FUNCTION organizations_tsv_update();

CREATE OR REPLACE FUNCTION contacts_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.full_name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.email::text, '') || ' ' || coalesce(NEW.phone, '')
                                        || ' ' || coalesce(NEW.mobile, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.job_title, '') || ' ' || coalesce(NEW.notes, '')), 'C');
    RETURN NEW;
END$$;
CREATE TRIGGER contacts_tsv_trg BEFORE INSERT OR UPDATE OF full_name, email, phone, mobile, job_title, notes
    ON contacts FOR EACH ROW EXECUTE FUNCTION contacts_tsv_update();

CREATE OR REPLACE FUNCTION deals_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER deals_tsv_trg BEFORE INSERT OR UPDATE OF title, description
    ON deals FOR EACH ROW EXECUTE FUNCTION deals_tsv_update();

CREATE OR REPLACE FUNCTION interactions_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.body, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER interactions_tsv_trg BEFORE INSERT OR UPDATE OF subject, body
    ON interactions FOR EACH ROW EXECUTE FUNCTION interactions_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX contacts_department_idx ON contacts (department_id);
CREATE INDEX deals_stage_fk_idx ON deals (stage_id);
CREATE INDEX deals_primary_contact_idx ON deals (primary_contact_id);
CREATE INDEX interactions_member_idx ON interactions (member_id, occurred_at DESC);

COMMIT;
