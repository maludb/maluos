-- 179: K36 — the Data Lake application in the catalog (D1/D16 of /srv/apps/datalake/docs/datalake-design.md §12–13, the owner
-- approved 2026-10-10): the business's own data lake with a built-in lakehouse, on open formats and embeddable libraries (DuckLake on
-- a PostgreSQL catalog, Parquet, DuckDB) with no data platform adopted — datasets in four zones written only by the application's
-- writer service, a catalog filled by the machine, contracts and checks with quarantine, incidents and computed certification,
-- grants with masks by classification and row filters, one sandboxed query service as the only door to the data with every read
-- audited, retention and erasure with a proof, a SQL editor, saved and verified queries, metrics and an ask window. Category
-- 'database' is already admitted by both checks (db/172, db/175 and db/178 kept it), so nothing is widened. Seeded so every
-- installation shows it under Technology & Infrastructure ("from us, not installed") and the installer's apply finds its row. On
-- request, not a default. Additive.
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/179_k36_datalake_catalog.sql
BEGIN;

INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category, sort_order)
SELECT 'datalake', 'Data Lake',
       'The business''s own data lake with a built-in lakehouse: spreadsheets people upload, files and outside databases read on a schedule, and extracts of the other applications'' data through the kernel — landed as received, typed and checked against a contract, owned and certified. A catalog to find every dataset with its owner, meaning, freshness, quality and lineage; classifications, masks and row filters to protect it, with every read audited and an erasure that proves itself; a SQL editor, saved and verified queries, metrics and an ask window whose answers show their SQL. The Data Lake Expert answers as the person who asks; the Data Steward drafts descriptions and triages failed checks for people to accept. Optional; installed on request.',
       'feather-database', g.id, 'ours', NULL, 'database', 0
  FROM nav_groups g WHERE g.name = 'Technology & Infrastructure'
ON CONFLICT (catalog_key) DO NOTHING;

COMMIT;
