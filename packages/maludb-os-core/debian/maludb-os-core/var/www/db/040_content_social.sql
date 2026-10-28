-- 040_content_social.sql
-- Content & social (decided in v1, 2026-09-17). Channels, campaigns, content items with a
-- variant per channel, the calendar (variant scheduled_at), publish results, metrics
-- snapshots, and lead/deal attribution. Publishing is an external send, so agent-authored
-- items go through the approval queue (approval_request_id FK added in 044).
-- Direct publishing through platform APIs is still an open point; the schema supports
-- both manual publish (paste the link) and connector publish.
-- Questions: SM1–SM13, C12.

BEGIN;

CREATE TABLE channels (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform           text NOT NULL CHECK (platform IN ('linkedin', 'facebook', 'instagram', 'x',
                                                         'threads', 'youtube', 'tiktok', 'newsletter',
                                                         'blog', 'other')),
    name               text NOT NULL,
    handle             text,
    publish_mode       text NOT NULL DEFAULT 'manual' CHECK (publish_mode IN ('manual', 'connector')),
    connection_status  text NOT NULL DEFAULT 'not_connected'
                           CHECK (connection_status IN ('not_connected', 'connected', 'expired', 'error')),  -- SM9
    secret_id          bigint REFERENCES tenant_secrets(id) ON DELETE SET NULL,
    connected_at       timestamptz,
    last_checked_at    timestamptz,
    last_error         text,
    department_id      bigint REFERENCES departments(id) ON DELETE SET NULL,
    archived_at        timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, name)
);

CREATE TABLE campaigns (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text NOT NULL,
    goal             text,
    status           text NOT NULL DEFAULT 'planned'
                         CHECK (status IN ('planned', 'active', 'completed', 'cancelled')),
    starts_on        date,
    ends_on          date,
    budget_amount    numeric(14,2) CHECK (budget_amount >= 0),
    currency         char(3),
    owner_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    department_id    bigint REFERENCES departments(id) ON DELETE SET NULL,
    created_by       bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on)
);
CREATE INDEX campaigns_status_idx ON campaigns (status, starts_on);

CREATE TABLE content_items (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title                text NOT NULL,
    brief                text,
    campaign_id          bigint REFERENCES campaigns(id) ON DELETE SET NULL,
    author_member_id     bigint REFERENCES members(id) ON DELETE SET NULL,     -- human or agent (SM3)
    owner_member_id      bigint REFERENCES members(id) ON DELETE SET NULL,
    reviewer_member_id   bigint REFERENCES members(id) ON DELETE SET NULL,     -- SM2
    department_id        bigint REFERENCES departments(id) ON DELETE SET NULL,
    status               text NOT NULL DEFAULT 'idea'
                             CHECK (status IN ('idea', 'draft', 'in_review', 'approved', 'scheduled',
                                               'published', 'failed', 'archived')),
    approval_request_id  bigint,                                                -- FK in 044 (SM3, SM13)
    approved_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    approved_at          timestamptz,
    search_tsv           tsvector,                                              -- SM10
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX content_items_status_idx   ON content_items (status);
CREATE INDEX content_items_campaign_idx ON content_items (campaign_id);
CREATE INDEX content_items_search_idx   ON content_items USING gin (search_tsv);

-- One variant per channel: the caption/body as it goes out there, and its calendar slot.
CREATE TABLE content_variants (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_item_id    bigint NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    channel_id         bigint NOT NULL REFERENCES channels(id) ON DELETE RESTRICT,
    body               text NOT NULL,
    status             text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'scheduled', 'publishing', 'published', 'failed', 'cancelled')),
    scheduled_at       timestamptz,                                              -- SM1, SM7
    published_at       timestamptz,
    published_by       bigint REFERENCES members(id) ON DELETE SET NULL,         -- SM12
    platform_post_id   text,
    published_url      text,
    publish_error      text,                                                     -- SM4
    search_tsv         tsvector,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (content_item_id, channel_id)
);
CREATE INDEX content_variants_calendar_idx ON content_variants (channel_id, scheduled_at)
    WHERE status IN ('scheduled', 'publishing');
CREATE INDEX content_variants_published_idx ON content_variants (published_at) WHERE status = 'published';
CREATE INDEX content_variants_search_idx ON content_variants USING gin (search_tsv);

-- Media attached to a variant come from Documents.
CREATE TABLE content_variant_media (
    content_variant_id  bigint NOT NULL REFERENCES content_variants(id) ON DELETE CASCADE,
    document_id         bigint NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    sort_order          integer NOT NULL DEFAULT 0,
    PRIMARY KEY (content_variant_id, document_id)
);

-- Performance snapshots pulled from the platform (or entered by hand) — SM5, SM6.
CREATE TABLE content_metrics (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_variant_id  bigint NOT NULL REFERENCES content_variants(id) ON DELETE CASCADE,
    captured_at         timestamptz NOT NULL DEFAULT now(),
    source              text NOT NULL DEFAULT 'connector' CHECK (source IN ('connector', 'manual')),
    impressions         bigint CHECK (impressions >= 0),
    reach               bigint CHECK (reach >= 0),
    engagements         bigint CHECK (engagements >= 0),
    clicks              bigint CHECK (clicks >= 0),
    likes               bigint CHECK (likes >= 0),
    comments            bigint CHECK (comments >= 0),
    shares              bigint CHECK (shares >= 0),
    video_views         bigint CHECK (video_views >= 0),
    raw                 jsonb
);
CREATE INDEX content_metrics_variant_idx ON content_metrics (content_variant_id, captured_at DESC);

-- --------------------------------------------------------------------------
-- Attribution + cost links from earlier modules (SM8, SM11, C12)
-- --------------------------------------------------------------------------
ALTER TABLE organizations
    ADD CONSTRAINT organizations_source_campaign_fk
        FOREIGN KEY (source_campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
    ADD CONSTRAINT organizations_source_content_fk
        FOREIGN KEY (source_content_item_id) REFERENCES content_items(id) ON DELETE SET NULL;
ALTER TABLE contacts
    ADD CONSTRAINT contacts_source_campaign_fk
        FOREIGN KEY (source_campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
    ADD CONSTRAINT contacts_source_content_fk
        FOREIGN KEY (source_content_item_id) REFERENCES content_items(id) ON DELETE SET NULL;
ALTER TABLE deals
    ADD CONSTRAINT deals_source_campaign_fk
        FOREIGN KEY (source_campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
    ADD CONSTRAINT deals_source_content_fk
        FOREIGN KEY (source_content_item_id) REFERENCES content_items(id) ON DELETE SET NULL;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_campaign_fk
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL;
ALTER TABLE time_entries
    ADD CONSTRAINT time_entries_campaign_fk
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL;

CREATE INDEX organizations_source_campaign_idx ON organizations (source_campaign_id);
CREATE INDEX contacts_source_campaign_idx      ON contacts (source_campaign_id);
CREATE INDEX deals_source_campaign_idx         ON deals (source_campaign_id);
CREATE INDEX deals_source_content_idx          ON deals (source_content_item_id);
CREATE INDEX expenses_campaign_idx             ON expenses (campaign_id);
CREATE INDEX time_entries_campaign_idx         ON time_entries (campaign_id);

CREATE OR REPLACE FUNCTION content_items_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.brief, '')), 'B');
    RETURN NEW;
END$$;
CREATE TRIGGER content_items_tsv_trg BEFORE INSERT OR UPDATE OF title, brief
    ON content_items FOR EACH ROW EXECUTE FUNCTION content_items_tsv_update();

CREATE OR REPLACE FUNCTION content_variants_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv := to_tsvector('english', coalesce(NEW.body, ''));
    RETURN NEW;
END$$;
CREATE TRIGGER content_variants_tsv_trg BEFORE INSERT OR UPDATE OF body
    ON content_variants FOR EACH ROW EXECUTE FUNCTION content_variants_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX content_items_author_idx ON content_items (author_member_id);
CREATE INDEX content_items_reviewer_idx ON content_items (reviewer_member_id);
CREATE INDEX content_variant_media_document_idx ON content_variant_media (document_id);

COMMIT;
