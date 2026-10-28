-- 139: the third kind of application (A7 (f), 2026-09-22).
--
-- application_catalog.kind gains 'ours': an application from us — a separate memory-first
-- application on our stack the installation agent installs beside the kernel (maludb-os.json,
-- registration.md). The catalog row is added by the installation agent or by hand
-- (application_catalog_save) before the application is registered against it. Additive.
-- Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/139_ours_kind.sql

BEGIN;
ALTER TABLE application_catalog DROP CONSTRAINT application_catalog_kind_check;
ALTER TABLE application_catalog ADD CONSTRAINT application_catalog_kind_check CHECK (kind IN ('builtin', 'external', 'ours'));
COMMENT ON COLUMN application_catalog.kind IS 'builtin: the kernel''s own; ours: an application from us, installed beside the kernel at its own name; external: anyone else''s product.';
COMMIT;

-- The runner reads the catalog kind of an endpoint's application (A7 (a)). Applied 2026-09-22.
GRANT SELECT ON application_catalog TO app_runner;

-- application_catalog carries row security with a policy for app_rw only; the runner reads it as app_runner.
CREATE POLICY application_catalog_runner ON application_catalog FOR SELECT TO app_runner USING (true);
