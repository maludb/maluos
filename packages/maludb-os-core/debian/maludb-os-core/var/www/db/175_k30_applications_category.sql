-- 175 — K30 (2026-10-09): applications.category admits 'inventory' and 'manufacturing'.
-- K27 (db/172) and K29 (db/174) widened application_catalog's category check for the Inventory and ProcessCore catalog
-- rows, but the installer registers the application itself in `applications`, whose own check still listed the original
-- twelve categories: `bin/app_install.php apply /srv/apps/processcore` failed at the register step with
-- applications_category_check (2026-10-09). The two checks now agree. Additive: no row changes.
ALTER TABLE applications DROP CONSTRAINT applications_category_check;
ALTER TABLE applications ADD CONSTRAINT applications_category_check
    CHECK (category IN ('platform', 'accounting', 'crm', 'calendar', 'email', 'documents', 'storage', 'database',
                        'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing', 'other'));
