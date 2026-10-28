-- 162: a shared tool may answer about PEOPLE (owner, 2026-09-28: txtSchedules tells HR which time off was taken).
-- application_shares.people marks such a tool (maludb-os.json shares[] "people": true). The kernel lets only a consumer
-- application registered for directory writes — HR, the one application that changes the directory — read it, and
-- only over a connection a super-admin approved. Additive.
-- Run as postgres:  sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/162_person_level_shares.sql
BEGIN;
ALTER TABLE application_shares ADD COLUMN people boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN application_shares.people IS 'The tool answers about members, keyed by the kernel''s member id — only a consumer with directory_writes may read it (db/162).';
DROP VIEW mcp_application_connections;
CREATE VIEW mcp_application_connections WITH (security_barrier = true) AS
 SELECT c.id AS connection_id, c.consumer_id, ca.name AS consumer_name, c.provider_id, pa.name AS provider_name,
        c.tool, s.description AS tool_description, s.scoped, c.why,
        CASE WHEN c.revoked_at IS NOT NULL THEN 'revoked' WHEN c.approved_at IS NOT NULL THEN 'approved' ELSE 'proposed' END AS state,
        c.proposed_at, c.approved_at, c.approved_by, c.revoked_at, COALESCE(s.people, false) AS people
   FROM application_connections c
   JOIN applications ca ON ca.id = c.consumer_id
   JOIN applications pa ON pa.id = c.provider_id
   LEFT JOIN application_shares s ON s.application_id = c.provider_id AND s.tool = c.tool
  WHERE (SELECT app_is_super_admin());
GRANT SELECT ON mcp_application_connections TO app_rw, app_records_ro;
COMMIT;
