-- 080_project_name_masking.sql
-- A record you may see must not name a record you may not — db/065's rule, applied to
-- projects and tasks before the Projects & tasks slice is built on top of them.
--
-- Three leaks, each verified against the installed database with a rolled-back fixture
-- (2026-09-18, while writing docs/build-specs/projects-tasks.md):
--
--   1. mcp_tasks.project_name — a task reached by ONE route (the assignee clause) printed the
--      name of a project mcp_projects refuses that caller entirely. Sam Okafor (ordinary user,
--      no grants, not in HR) read "Confidential HR Rebuild" off his own task row.
--
--   2. mcp_projects.organization_name — the cross-module shape db/077 found in the sales views:
--      the view asks app_can_see('projects', ...) for the ROW, then borrows the customer's name
--      with no check at all. Organizations are gated on the CONTACTS module, so a projects-grant
--      holder with no contacts grant saw "Zenith Holdings" while mcp_organizations returned him
--      nothing. Passing an organization_id into app_can_see() would not have saved it either —
--      the projects grant says nothing about whether the caller may see the company.
--
--   3. mcp_task_dependencies.depends_on_title / depends_on_status — the blocking task's title
--      and state, borrowed straight from the base table, for a task the caller cannot see.
--      THAT a task is blocked stays visible (mcp_tasks.has_open_dependencies is untouched):
--      it is the assignee's business. WHAT is blocking it is not always.
--
-- The rows each view returns are unchanged. Only the borrowed label is masked, and the id
-- stays, because a caller who cannot see the record cannot open it either way; the screens
-- render NULL as an em dash.

BEGIN;

-- One definition of "may this caller see this project", so the rule stops being copied.
-- SECURITY DEFINER for the same reason as the location helpers (db/068): it must answer the
-- same way for app_rw and for the read-only MCP roles, whatever RLS says about the base tables.
CREATE OR REPLACE FUNCTION app_can_see_project(p_project_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM projects p
         WHERE p.id = p_project_id
           AND (app_can_see('projects', p.owner_member_id, p.department_id,
                            'project', p.id, p.organization_id)
                OR EXISTS (SELECT 1 FROM project_members x
                            WHERE x.project_id = p.id
                              AND x.member_id = app_current_member_id())));
$$;

REVOKE ALL ON FUNCTION app_can_see_project(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_can_see_project(bigint) TO app_rw, app_records_ro, app_activity_ro;

-- mcp_projects: same rows as before (its WHERE now calls the helper that holds the rule), with
-- the customer's name shown only to someone the CONTACTS rule admits to that company.
CREATE OR REPLACE VIEW mcp_projects WITH (security_barrier = true) AS
SELECT p.id AS project_id, p.code, p.name, p.description, p.organization_id,
       CASE WHEN app_can_see('contacts', o.owner_member_id, o.department_id,
                             'organization', o.id, o.id)
            THEN o.name END AS organization_name,
       p.deal_id, p.department_id, p.owner_member_id,
       pm.display_name AS owner_name, p.status, p.start_date, p.due_date, p.completed_at,
       p.billing_type, p.budget_hours, p.budget_amount, p.currency,
       CASE WHEN NOT app_is_external() THEN p.hourly_rate END AS hourly_rate,
       (SELECT count(*) FROM tasks t WHERE t.project_id = p.id AND t.status <> 'cancelled') AS tasks_total,
       (SELECT count(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'done') AS tasks_done,
       p.archived_at, p.search_tsv, p.created_at, p.updated_at
FROM projects p
LEFT JOIN organizations o ON o.id = p.organization_id
LEFT JOIN members pm ON pm.id = p.owner_member_id
WHERE app_can_see_project(p.id);

-- mcp_tasks: unchanged rows (the assignee, the creator, project members and app_can_see() all
-- still admit), with the project's name masked to exactly what mcp_projects would return.
CREATE OR REPLACE VIEW mcp_tasks WITH (security_barrier = true) AS
SELECT t.id AS task_id, t.project_id,
       CASE WHEN app_can_see_project(t.project_id) THEN p.name END AS project_name,
       t.milestone_id, t.parent_task_id,
       t.organization_id, t.ticket_id, t.title, t.description, t.task_type,
       t.assignee_member_id, am.display_name AS assignee_name, am.member_kind AS assignee_kind,
       t.department_id, t.status, t.blocked_reason, t.priority, t.start_date, t.due_date,
       t.estimate_hours, t.completed_at,
       EXISTS (SELECT 1 FROM task_dependencies td JOIN tasks dt ON dt.id = td.depends_on_task_id
                WHERE td.task_id = t.id AND dt.status NOT IN ('done', 'cancelled')) AS has_open_dependencies,
       t.search_tsv, t.created_by, t.created_at, t.updated_at
FROM tasks t
LEFT JOIN projects p ON p.id = t.project_id
LEFT JOIN members am ON am.id = t.assignee_member_id
WHERE app_is_insider()
  AND (t.assignee_member_id = app_current_member_id()
       OR t.created_by = app_current_member_id()
       OR app_can_see('projects', p.owner_member_id, COALESCE(t.department_id, p.department_id),
                      'task', t.id, NULL)
       OR EXISTS (SELECT 1 FROM project_members x
                   WHERE x.project_id = t.project_id AND x.member_id = app_current_member_id()));

-- mcp_task_dependencies: the dependency edge stays (the id is not a secret and opens to a 404);
-- the blocking task's title and status appear only when that task is itself visible.
CREATE OR REPLACE VIEW mcp_task_dependencies WITH (security_barrier = true) AS
SELECT td.task_id, td.depends_on_task_id,
       CASE WHEN EXISTS (SELECT 1 FROM mcp_tasks v WHERE v.task_id = td.depends_on_task_id)
            THEN dt.title END AS depends_on_title,
       CASE WHEN EXISTS (SELECT 1 FROM mcp_tasks v WHERE v.task_id = td.depends_on_task_id)
            THEN dt.status END AS depends_on_status
FROM task_dependencies td
JOIN mcp_tasks t ON t.task_id = td.task_id
JOIN tasks dt ON dt.id = td.depends_on_task_id;

GRANT SELECT ON mcp_projects, mcp_tasks, mcp_task_dependencies TO app_records_ro, app_rw;

COMMIT;
