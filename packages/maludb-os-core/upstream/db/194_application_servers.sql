-- 194: application servers (MaluOS Phase 14 slice 3; maluos docs/phase14-application-servers.md).
--
-- An application may run on a MaluOS server of its own, apart from the kernel. That server is an estate node
-- (kind server) that joined with a code its operator minted FOR NAMED APPLICATIONS: the code carries the
-- catalog keys, the node keeps them, and the node may register only those through /api/v1/estate/apps/*.
-- A node whose code named none installs nothing. Additive; nothing existing changes.

ALTER TABLE desk_enrollment_codes ADD COLUMN apps text[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN desk_enrollment_codes.apps IS
    'Node codes only: the catalog keys the joining server may install as an application server (db/194). Empty: none.';

ALTER TABLE locations ADD COLUMN node_apps text[] NOT NULL DEFAULT '{}';
ALTER TABLE locations ADD COLUMN node_role text;
ALTER TABLE locations ADD COLUMN node_address text;
COMMENT ON COLUMN locations.node_apps IS
    'A node''s allowance: the catalog keys it may register as an application server, from its join code (db/194).';
COMMENT ON COLUMN locations.node_role IS
    'What the node says it is in its report: kernel, application-server, database-server (a label; the kind stays server) (db/194).';
COMMENT ON COLUMN locations.node_address IS
    'The node''s address on the business''s network as it gave it at registration: where the kernel posts an application''s actions and what the proxy uses as the upstream (db/194).';
ALTER TABLE locations ADD CONSTRAINT locations_node_role_check
    CHECK (node_role IS NULL OR node_role IN ('kernel', 'application-server', 'database-server'));

-- Where an application runs when it is not beside the kernel: the address the Actions MCP posts to. NULL: loopback.
ALTER TABLE applications ADD COLUMN internal_base_url text;
COMMENT ON COLUMN applications.internal_base_url IS
    'A remote application''s internal base URL as the kernel reaches it (http://<application server>:<port>); NULL for one beside the kernel (db/194).';
