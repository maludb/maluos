-- 195: the estate's node samples (MaluOS Phase 14 slice 4b; maluos docs/phase14-watching-agents.md).
--
-- A node's report is kept 24 deep (db/188): enough to say what is wrong now, not how it got there. The watching
-- agents need trends ("the disk fills in nine days"), so the kernel keeps a thinner, longer history: the report's
-- NUMBERS only, one row per node per ten minutes, thirty days. Additive; nothing existing changes.

CREATE TABLE estate_node_samples (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id   bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    ts            timestamptz NOT NULL DEFAULT now(),
    numbers       jsonb NOT NULL
);
CREATE INDEX estate_node_samples_node_idx ON estate_node_samples (location_id, ts DESC);
COMMENT ON TABLE estate_node_samples IS
    'The numbers of a node''s reports over time (db/195): one row per node per ten minutes, kept thirty days by the presence sweep. Flat keys (disk:/ used_pct as "disk./", "pg.connections_pct", "sec.failed_logins"); never text from a log or a query.';

ALTER TABLE estate_node_samples ENABLE ROW LEVEL SECURITY;
CREATE POLICY estate_node_samples_app_rw ON estate_node_samples FOR ALL TO app_rw USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, DELETE ON estate_node_samples TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE estate_node_samples_id_seq TO app_rw;
