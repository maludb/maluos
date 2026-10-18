-- 134: the company's own logo (2026-09-22).
--
-- A super-admin uploads the business's logo on Business settings; it is shown where the
-- shipped /assets/images/logo-full.png sits, in the sidebar header of every signed-in screen.
-- The shape of db/090 (agent photos): the bytes live under the storage root, outside the
-- document root, and the row holds the facts about them. Nothing here is served by Apache
-- on its own — /settings/business/logo.php is the only way to the file. Additive.

ALTER TABLE business_settings
    ADD COLUMN IF NOT EXISTS logo_path        text,
    ADD COLUMN IF NOT EXISTS logo_mime        text,
    ADD COLUMN IF NOT EXISTS logo_size_bytes  integer,
    ADD COLUMN IF NOT EXISTS logo_sha256      text,
    ADD COLUMN IF NOT EXISTS logo_updated_at  timestamptz;

COMMENT ON COLUMN business_settings.logo_path IS
    'Relative to the storage root (STORAGE_ROOT, default APP_ROOT/storage): business/logo/<sha256>.<ext>. NULL = the shipped logo.';

ALTER TABLE business_settings
    ADD CONSTRAINT business_settings_logo_whole
    CHECK ((logo_path IS NULL) = (logo_mime IS NULL)
       AND (logo_path IS NULL) = (logo_sha256 IS NULL)
       AND (logo_path IS NULL) = (logo_size_bytes IS NULL)
       AND (logo_path IS NULL) = (logo_updated_at IS NULL));
