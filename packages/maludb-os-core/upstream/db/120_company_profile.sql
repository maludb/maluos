-- 120_company_profile.sql
-- Company Profile (docs/build-specs/company-profile.md, approved 2026-09-20): who the business is,
-- what it sells, and the source a display website is built from.
--
-- Identity is NOT copied: business name, legal name, address, email, phone and website stay in
-- business_settings (one source of truth); the profile adds the story, the facts, the pictures
-- and a curated list of what the business offers. Additive only.
--
--   company_profile         singleton: tagline, about, mission, facts, social links, logo/hero,
--                           and whether the website feed is published
--   company_profile_media   the uploaded images (bytes on disk under the storage root)
--   company_profile_items   the "products": a catalog item, an inventory product, or a free-form
--                           showcase entry, each with its own blurb, picture and order
--   mcp_company_profile, mcp_company_profile_items   what insiders (and their tools) read
--
-- tax_id is deliberately nowhere in this file.

BEGIN;

CREATE TABLE company_profile_media (
    id            bigserial PRIMARY KEY,
    slot          text NOT NULL CHECK (slot IN ('logo', 'hero', 'item')),
    storage_path  text NOT NULL,
    original_name text,
    mime          text NOT NULL CHECK (mime IN ('image/png', 'image/jpeg', 'image/webp')),
    size_bytes    integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
    sha256        text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    width         integer NOT NULL CHECK (width > 0),
    height        integer NOT NULL CHECK (height > 0),
    uploaded_by   bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE company_profile (
    id             smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tagline        text CHECK (tagline IS NULL OR char_length(tagline) <= 160),
    about          text CHECK (about IS NULL OR char_length(about) <= 8000),
    mission        text CHECK (mission IS NULL OR char_length(mission) <= 2000),
    founded_year   integer CHECK (founded_year IS NULL OR founded_year BETWEEN 1800 AND 2100),
    industry       text CHECK (industry IS NULL OR char_length(industry) <= 120),
    headquarters   text CHECK (headquarters IS NULL OR char_length(headquarters) <= 160),
    team_size      text CHECK (team_size IS NULL OR char_length(team_size) <= 60),
    social_links   jsonb NOT NULL DEFAULT '[]'::jsonb
                   CHECK (jsonb_typeof(social_links) = 'array' AND jsonb_array_length(social_links) <= 12),
    logo_media_id  bigint REFERENCES company_profile_media(id) ON DELETE SET NULL,
    hero_media_id  bigint REFERENCES company_profile_media(id) ON DELETE SET NULL,
    is_published   boolean NOT NULL DEFAULT false,
    published_at   timestamptz,
    published_by   bigint REFERENCES members(id) ON DELETE SET NULL,
    updated_by     bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
INSERT INTO company_profile (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE company_profile_items (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('catalog_item', 'product', 'custom')),
    catalog_item_id bigint REFERENCES catalog_items(id) ON DELETE CASCADE,
    product_id      bigint REFERENCES products(id) ON DELETE CASCADE,
    title           text CHECK (title IS NULL OR char_length(title) <= 160),
    blurb           text CHECK (blurb IS NULL OR char_length(blurb) <= 200),
    description     text CHECK (description IS NULL OR char_length(description) <= 4000),
    image_media_id  bigint REFERENCES company_profile_media(id) ON DELETE SET NULL,
    show_price      boolean NOT NULL DEFAULT false,
    price_text      text CHECK (price_text IS NULL OR char_length(price_text) <= 80),
    link_url        text CHECK (link_url IS NULL OR (char_length(link_url) <= 500 AND link_url ~* '^https://')),
    display_order   integer NOT NULL DEFAULT 0,
    is_visible      boolean NOT NULL DEFAULT true,
    created_by      bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    -- exactly the source its kind names; a showcase entry names none and needs its own title
    CONSTRAINT company_profile_items_source CHECK (
        (kind = 'catalog_item' AND catalog_item_id IS NOT NULL AND product_id IS NULL)
     OR (kind = 'product'      AND product_id IS NOT NULL      AND catalog_item_id IS NULL)
     OR (kind = 'custom'       AND catalog_item_id IS NULL     AND product_id IS NULL
                               AND title IS NOT NULL AND btrim(title) <> '')),
    -- a record's own price is the only price it shows; free text is for showcase entries
    CONSTRAINT company_profile_items_price_text CHECK (price_text IS NULL OR kind = 'custom')
);
CREATE UNIQUE INDEX company_profile_items_catalog_uq ON company_profile_items(catalog_item_id) WHERE catalog_item_id IS NOT NULL;
CREATE UNIQUE INDEX company_profile_items_product_uq ON company_profile_items(product_id) WHERE product_id IS NOT NULL;
CREATE INDEX company_profile_items_order_idx ON company_profile_items(display_order, id);
CREATE INDEX company_profile_items_image_idx ON company_profile_items(image_media_id) WHERE image_media_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON company_profile_media, company_profile_items TO app_rw;
GRANT SELECT, UPDATE ON company_profile TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE company_profile_media_id_seq, company_profile_items_id_seq TO app_rw;

-- What an insider reads. The storage path of a picture is no client's business and is not here;
-- neither is tax_id. An External (a portal customer) reads nothing.
CREATE VIEW mcp_company_profile WITH (security_barrier = true) AS
SELECT b.business_name, b.legal_name, b.address, b.email::text AS email, b.phone, b.website,
       p.tagline, p.about, p.mission, p.founded_year, p.industry, p.headquarters, p.team_size,
       p.social_links,
       p.logo_media_id, lm.mime AS logo_mime, lm.width AS logo_width, lm.height AS logo_height, lm.sha256 AS logo_sha256,
       p.hero_media_id, hm.mime AS hero_mime, hm.width AS hero_width, hm.height AS hero_height, hm.sha256 AS hero_sha256,
       p.is_published, p.published_at, p.updated_at
FROM company_profile p
CROSS JOIN business_settings b
LEFT JOIN company_profile_media lm ON lm.id = p.logo_media_id
LEFT JOIN company_profile_media hm ON hm.id = p.hero_media_id
WHERE app_is_insider();

-- Each offering with its source resolved. The price is the record's own, and only when the item
-- says to show it -- so the profile never tells someone without the sales or inventory module a
-- price the super-admin did not choose to show. An archived source takes its card with it.
CREATE VIEW mcp_company_profile_items WITH (security_barrier = true) AS
SELECT i.id AS item_id, i.kind, i.catalog_item_id, i.product_id,
       COALESCE(NULLIF(btrim(i.title), ''), ci.name, pr.name) AS name,
       i.title AS title_override,
       COALESCE(ci.name, pr.name) AS source_name,
       i.blurb,
       COALESCE(NULLIF(btrim(i.description), ''), ci.description, pr.description) AS description,
       i.description AS description_override,
       pr.sku,
       COALESCE(ci.unit, pr.unit) AS unit,
       i.show_price,
       CASE WHEN i.show_price THEN COALESCE(ci.unit_price, pr.unit_price) END AS unit_price,
       CASE WHEN i.show_price THEN COALESCE(ci.currency, pr.currency)::text END AS currency,
       i.price_text, i.link_url, i.display_order, i.is_visible,
       i.image_media_id, im.mime AS image_mime, im.width AS image_width, im.height AS image_height, im.sha256 AS image_sha256,
       i.created_at, i.updated_at
FROM company_profile_items i
LEFT JOIN catalog_items ci ON ci.id = i.catalog_item_id
LEFT JOIN products pr ON pr.id = i.product_id
LEFT JOIN company_profile_media im ON im.id = i.image_media_id
WHERE app_is_insider()
  AND (i.kind = 'custom'
       OR (i.kind = 'catalog_item' AND ci.archived_at IS NULL)
       OR (i.kind = 'product' AND pr.archived_at IS NULL));

GRANT SELECT ON mcp_company_profile, mcp_company_profile_items TO app_rw, app_records_ro;

-- Publishing puts the profile where a website can read it: outward-facing, so an agent pauses
-- for a person (same shape as db/053 and db/105; editable in Settings -> Approval policies).
INSERT INTO approval_policies (name, category, action_pattern, applies_to)
SELECT 'Agents: publishing the company profile', 'external_send', 'company_profile.publish', 'agents'
WHERE NOT EXISTS (SELECT 1 FROM approval_policies p WHERE p.name = 'Agents: publishing the company profile');

COMMIT;
