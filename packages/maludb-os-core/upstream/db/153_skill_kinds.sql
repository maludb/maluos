-- 153: a skill's kind (owner, 2026-09-27): a runbook is a skill with `kind: runbook` in its frontmatter —
-- a more generic skill tied to an application, shipped with it, and given to individual agents from
-- there. MaluDB holds the bundle and its frontmatter, but its list answers no frontmatter, so the
-- kernel keeps the kind by name, written on every ingest and filled in lazily for what was ingested
-- before (skill_kind_of() reads the bundle once and records it).
BEGIN;

CREATE TABLE skill_kinds (
    skill_name text PRIMARY KEY,
    kind text NOT NULL DEFAULT 'skill' CHECK (kind IN ('skill', 'runbook')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE skill_kinds IS 'The kind of a MaluDB skill by name: skill, or runbook (an application''s generic skill). db/153.';
GRANT SELECT, INSERT, UPDATE, DELETE ON skill_kinds TO app_rw;
GRANT SELECT ON skill_kinds TO app_records_ro;
GRANT SELECT ON skill_kinds TO app_runner;

COMMIT;
