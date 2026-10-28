-- 098_agent_skills.sql
-- Stage H5 (docs/build-specs/agent-skills.md). Schema approved by the owner at the H1 checkpoint
-- (2026-09-19). Numbered 098 because it was drafted then; the stub-modules build numbers its
-- migrations from 105, so the two runs never collide.
--
-- Skills live in MaluDB: immutable, hash-identified SKILL.md bundles with lineage. MaluDB stores
-- and versions them; the platform decides WHO GETS WHICH. Two tables:
--
--   skill_assignments — a MaluDB skill is assigned to the whole organisation, a department, a
--     functional role (agent_profiles.role_key) or one agent; optionally pinned to one bundle
--     hash. Before every run the runner materialises the agent's assigned skills, read-only.
--   skill_proposals   — a skill an agent wrote (or changed) during a run. It is ingested into
--     MaluDB disabled, scanned, and waits for the agent's manager. A skill can carry
--     instructions every other agent will follow, so nothing an agent writes reaches another
--     agent without a person reading the diff. v1 refuses agent-authored bundles with scripts.

BEGIN;

CREATE TABLE skill_assignments (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    skill_name         text NOT NULL,                       -- MaluDB skill name (stable across versions)
    pinned_bundle_hash text,                                -- null = newest enabled version
    scope_kind         text NOT NULL CHECK (scope_kind IN ('org', 'department', 'role', 'agent')),
    department_id      bigint REFERENCES departments(id) ON DELETE CASCADE,
    role_key           text,
    agent_member_id    bigint REFERENCES agent_profiles(member_id) ON DELETE CASCADE,
    note               text,
    assigned_by        bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    created_at         timestamptz NOT NULL DEFAULT now(),
    revoked_at         timestamptz,
    revoked_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    CHECK (scope_kind <> 'department' OR (department_id IS NOT NULL AND role_key IS NULL AND agent_member_id IS NULL)),
    CHECK (scope_kind <> 'role'       OR (role_key IS NOT NULL AND department_id IS NULL AND agent_member_id IS NULL)),
    CHECK (scope_kind <> 'agent'      OR (agent_member_id IS NOT NULL AND department_id IS NULL AND role_key IS NULL)),
    CHECK (scope_kind <> 'org'        OR (department_id IS NULL AND role_key IS NULL AND agent_member_id IS NULL))
);
CREATE UNIQUE INDEX skill_assignments_live_idx
    ON skill_assignments (skill_name, scope_kind, COALESCE(department_id, 0), COALESCE(role_key, ''),
                          COALESCE(agent_member_id, 0))
    WHERE revoked_at IS NULL;
CREATE INDEX skill_assignments_agent_idx ON skill_assignments (agent_member_id) WHERE revoked_at IS NULL;
CREATE INDEX skill_assignments_dept_idx  ON skill_assignments (department_id)  WHERE revoked_at IS NULL;

CREATE TABLE skill_proposals (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_member_id     bigint NOT NULL REFERENCES agent_profiles(member_id) ON DELETE RESTRICT,
    agent_run_id        bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    skill_name          text NOT NULL,
    bundle_hash         text NOT NULL,
    parent_bundle_hash  text,                                -- null = a new skill; set = a change to one
    maludb_skill_id     bigint,                              -- the disabled row ingested into MaluDB
    file_count          integer NOT NULL DEFAULT 1,
    has_scripts         boolean NOT NULL DEFAULT false,
    scan_findings       jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(scan_findings) = 'array'),
    skill_markdown      text,                                -- the proposed SKILL.md, kept for the reviewer's diff
    parent_markdown     text,                                -- the SKILL.md it changes (null = a new skill)
    status              text NOT NULL DEFAULT 'proposed'
                            CHECK (status IN ('proposed', 'approved', 'rejected', 'withdrawn')),
    approval_request_id bigint REFERENCES approval_requests(id) ON DELETE SET NULL,
    decided_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    decided_at          timestamptz,
    decision_note       text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (skill_name, bundle_hash)
);
CREATE INDEX skill_proposals_open_idx  ON skill_proposals (created_at) WHERE status = 'proposed';
CREATE INDEX skill_proposals_agent_idx ON skill_proposals (agent_member_id, created_at DESC);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['skill_assignments', 'skill_proposals'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)', t || '_rw', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_runner USING (true) WITH CHECK (true)', t || '_runner', t);
    END LOOP;
END $$;

-- Read surface for the MCP servers (tool skill_catalog). Skills are not secret inside the business:
-- which skills exist and who has them is visible to every insider, like the tool-grant view. A
-- PROPOSAL is its author's work under review: the agent itself, whoever may see that agent, and HR.
CREATE VIEW mcp_skill_assignments WITH (security_barrier = true) AS
SELECT a.id AS skill_assignment_id, a.skill_name, a.pinned_bundle_hash, a.scope_kind, a.department_id,
       d.name AS department_name, a.role_key, a.agent_member_id, m.display_name AS agent_name,
       a.note, a.assigned_by, a.created_at
  FROM skill_assignments a
  LEFT JOIN departments d ON d.id = a.department_id
  LEFT JOIN members m     ON m.id = a.agent_member_id
 WHERE a.revoked_at IS NULL AND app_is_insider();

CREATE VIEW mcp_skill_proposals WITH (security_barrier = true) AS
SELECT p.id AS skill_proposal_id, p.agent_member_id, m.display_name AS agent_name, p.agent_run_id,
       p.skill_name, p.bundle_hash, p.parent_bundle_hash, p.file_count, p.has_scripts, p.scan_findings,
       p.status, p.decided_by, p.decided_at, p.decision_note, p.created_at
  FROM skill_proposals p
  JOIN members m ON m.id = p.agent_member_id
 WHERE app_is_insider()
   AND (p.agent_member_id = app_current_member_id() OR app_has_module('hr') OR app_can_see_agent(p.agent_member_id));

GRANT SELECT ON mcp_skill_assignments, mcp_skill_proposals TO app_rw, app_records_ro;

GRANT SELECT, INSERT, UPDATE ON skill_assignments, skill_proposals TO app_rw;
GRANT SELECT ON skill_assignments TO app_runner;   -- the runner syncs; it proposes through a PHP handler

COMMIT;
