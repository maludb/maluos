# Build spec: Projects & tasks slice (phase 3, slice 1)

2026-09-18 · build plan phase 3 · written by the planning-class model

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`, code under
`html/contacts/`, `app/features/contacts/`, `app/views/contacts/`). Read
`docs/build-specs/business-os-slice-template.md` first; this spec names only the substitutions.

Module grant: `projects` · Manifest section: **Projects & tasks**
Schema tables (never modify): `projects`, `project_members`, `milestones`, `tasks`,
`task_dependencies`, `task_checklist_items` — `db/032_projects_tasks.sql`
Read views: `mcp_projects`, `mcp_project_members`, `mcp_milestones`, `mcp_tasks`,
`mcp_task_dependencies`, `mcp_task_checklist_items`, plus the shared `mcp_tags`, `mcp_taggings`,
`mcp_record_comments`, `mcp_team_directory`, `mcp_departments`, `mcp_organizations`, `mcp_deals`.
Questions this slice must answer: **P1–P12** (record: P1–P9; activity: P10–P12), **DB2**, **DB5**.
P13 (AI spend per project) belongs to the prompt ledger and is **not** this slice.

---

## Prerequisite migration — `db/080_project_name_masking.sql` (write and run BEFORE the slice)

`db/065` established the rule: **a record you may see must not name a record you may not.**
The projects views break it in two places. Verified against the installed database on 2026-09-18
with a rolled-back fixture (a project filed to HR, a task on it assigned to Sam Okafor — an
ordinary user with no grants and not in HR):

| View | Column | What the caller got | What they should get |
| --- | --- | --- | --- |
| `mcp_tasks` | `project_name` | `Confidential HR Rebuild` — read off his own task row | NULL — `mcp_projects` returns him no rows |
| `mcp_task_dependencies` | `depends_on_title`, `depends_on_status` | `Secret dependency task` / `todo` | NULL — that task is not in his `mcp_tasks` |
| `mcp_projects` | `organization_name` | `Zenith Holdings`, to a **projects**-grant holder with no **contacts** grant | NULL — `mcp_organizations` returns him nothing |

The third is the cross-module shape www-b4 found the same day in the sales views (`db/077`):
the view checks the row against `app_can_see('projects', …)` and then borrows a label from a
table gated on a **different** module. Passing `organization_id` into `app_can_see()` would not
have saved it — the projects grant says nothing about who may see the company.

`mcp_milestones` is already correct: it joins `mcp_projects`, so it masks by construction.

`db/080` applies the `db/065` pattern:

- `app_can_see_project(bigint) RETURNS boolean`, `STABLE SECURITY DEFINER SET search_path = public`,
  holding the **one** definition of project visibility:
  `app_can_see('projects', p.owner_member_id, p.department_id, 'project', p.id, p.organization_id)
  OR EXISTS (project_members row for app_current_member_id())`. `mcp_projects`' own WHERE is
  rewritten to call it, so the rule exists once rather than three times.
- `mcp_tasks.project_name` → `CASE WHEN app_can_see_project(t.project_id) THEN p.name END`.
- `mcp_projects.organization_name` → shown only when `app_can_see('contacts', o.owner_member_id,
  o.department_id, 'organization', o.id, o.id)` — the **contacts** rule, because that is the rule
  `mcp_organizations` itself applies.
- `mcp_task_dependencies.depends_on_title` / `depends_on_status` → shown only when the
  depended-on task is itself in `mcp_tasks`; the id stays (it opens to a 404 either way), and
  `has_open_dependencies` on `mcp_tasks` is unchanged — *that* a task is blocked is the
  assignee's business, *what* is blocking it is not always.
- `GRANT SELECT` re-issued on every changed view to `app_records_ro, app_rw`.

The screens print an em dash for a masked name and never say "hidden".

**Written, run and verified 2026-09-18** across four seats in one rolled-back transaction: an
assignee with no grants sees his task and no project name; a projects-grant holder sees the
project and no customer name; the same member **with** the contacts grant sees the customer name
of a company `mcp_organizations` returns him (a mask that over-applies is just a different bug);
the super-admin sees all three names. Row counts are identical before and after — only labels
are masked.

---

## What the database already guarantees (do not re-implement in PHP)

- `projects.code` is `NOT NULL UNIQUE`, taken from `next_document_number('project')` (prefix
  `P-`, seeded). A project is not a legal document, so a burned number is acceptable here —
  `db/066`'s gapless rule applies to invoices and credit notes, not to project codes.
- `status` CHECKs: project ∈ planning | active | on_hold | completed | cancelled; task ∈
  todo | in_progress | blocked | done | cancelled; priority ∈ low | normal | high | urgent;
  billing_type ∈ fixed | hourly | non_billable. **Never validate these in PHP by re-listing them
  loosely** — use the constants below, which match the CHECKs exactly.
- `task_dependencies` CHECKs `task_id <> depends_on_task_id` and its PK refuses duplicates.
  Cycles are **not** refused by the database — the slice refuses them (see `task_would_cycle`).
- `project_members` PK refuses a duplicate member; `ON DELETE CASCADE` cleans up.
- `search_tsv` triggers maintain full-text on projects and tasks. Do not write those columns.
- `departments` is four standing departments with the Front Office as the org-chart root
  (`db/074`), parented by trigger. This slice **never writes `departments.parent_id`**.

---

## Gate and visibility — READ THIS BEFORE WRITING AN ENDPOINT

The recurring defect in this codebase (five appearances across Expenses, the ledger, the estate)
is **a screen gated differently from the view behind it**. The rule that has held:
*the screen gate must be no stricter than the view, and anything narrower belongs in the view.*

The installed views admit more people than the module grant does:

- `mcp_projects` admits: the owner · a super-admin · a dept-admin **inside** the project's
  department · a `projects`-grant holder whose departments include the project's (or the project
  has none) · an external with the grant or a share · **and any member of `project_members`,
  grant or no grant.**
- `mcp_tasks` additionally admits **the assignee** and **the creator**, and requires
  `app_is_insider()`.

Therefore:

| Endpoint kind | Gate | Why |
| --- | --- | --- |
| `/projects/` reads (`index.php`, `view.php`, `form.php` in edit mode) | `require_login()` | Matches `mcp_projects` exactly. **Never `require_module('projects')`** — it would refuse a contributor the view admits to their own project. |
| `/tasks/` reads | `require_insider()` | Matches `mcp_tasks` exactly (the view's own `app_is_insider()`). |
| Actions marked `mod:projects` | `require_module('projects')` + `can_see_record('projects', …)` on the target row | Projects carry a department, so `has_module()` (grant **or** business admin) is the right helper here — not `require_module_grant()`, which is for business-wide modules. |
| Actions marked `own, mod:projects` (a comma means **OR**) | `require_task_actor()` | Assignee **or** creator **or** (`has_module('projects')` and the row is visible). |
| `task_create` (`all (own), mod:projects`) | `require_insider()` | Anyone who works here may write down their own work. If `project` is given, the project must be visible or the action is refused **by name**. |
| `project_delete` (`admin`) | `require_admin_for_department($pdo, $project['department_id'])` | Doc vocabulary: `admin` = super-admin, or dept-admin **within their departments**. A project with no department is therefore super-admin only. |
| `task_delete` (`own (creator), admin`) | creator, or `require_admin_for_department()` on the task's department (falling back to the project's) | The manifest's own words. |

A refusal always **names what is in the way** ("This needs the projects module grant, which an
admin can grant in Team & Access") — never a bare "cannot".

**Row rule on writes:** every write endpoint re-reads the target through its view first
(`find_project()` / `find_task()`); a row the view does not return is a 404, not a 403, so a
screen never reveals that a hidden record exists.

**Department stamping (the Expenses lesson — the default lives in the WRITE PATH, not the form):**

- `projects.department_id`: the form pre-selects the creator's primary department; `save.php`
  applies **the same default** when the field is absent (voice, agent, any non-browser caller).
  Blank is legal and means "no department" — visible to every holder of the `projects` grant,
  and the form says exactly that under the field.
- `tasks.department_id`: the project's department when a project is given, else the creator's
  primary department, else NULL. A task with no department is still visible to its assignee and
  creator, so nothing disappears.
- A member may only file into a department they belong to; a super-admin may file anywhere.
  Enforced in the write path, with the message the exemplar uses.

---

## Status vocabulary (locked)

| State | Badge |
| --- | --- |
| project `planning` | `secondary` · `active` `success` · `on_hold` `warning` · `completed` `info` · `cancelled` `dark` |
| task `todo` | `secondary` · `in_progress` `info` · `blocked` `danger` · `done` `success` · `cancelled` `dark` |
| priority `low` | `secondary` · `normal` (no badge) · `high` `warning` · `urgent` `danger` |
| overdue (due_date < today, not done/cancelled) | `danger` text on the date, never a second badge |
| archived project | `secondary` "Archived" badge next to the name |

---

## Screens

| Screen id | Canonical URL | When the user wants… | Params |
| --- | --- | --- | --- |
| `projects-list` | `/projects/` | to browse projects | `status`, `organization`, `department`, `over_budget`, `q`, `page`, `sort` |
| `project-add` | `/projects/new` | to start a project | `name`, `organization`, `deal` |
| `project-view` | `/projects/{id}` | one project: team, tasks, milestones, budget | `tab` |
| `project-edit` | `/projects/{id}/edit` | to edit a project | — |
| `milestone-add` | `/projects/milestones/new` | to add a milestone | `project` |
| `milestone-edit` | `/projects/milestones/{id}/edit` | to edit a milestone | — |
| `tasks-list` | `/tasks/` | to browse tasks | `mine`, `assignee`, `project`, `status`, `overdue`, `blocked`, `agents`, `q`, `page`, `sort` |
| `task-add` | `/tasks/new` | to add a task | `title`, `project`, `assignee`, `due` |
| `task-view` | `/tasks/{id}` | one task with checklist, dependencies and comments | — |
| `task-edit` | `/tasks/{id}/edit` | to edit a task | — |

**Manifest amendment (one, and it is a URL not a decision):** the manifest gives `milestone-add`
as `/projects/{id}/milestones/new`. The canonical-URL rules
(`docs/deploy/apache-canonical-urls.conf`) serve `/{module}/new` only when
`DOCUMENT_ROOT/{module}/form.php` exists, and `{module}` there would contain a record id — no
file can match. The URL becomes **`/projects/milestones/new?project={id}`**, which the existing
rules serve from `html/projects/milestones/form.php` and which matches the sibling
`milestone-edit` URL the manifest already uses. Same precedent as the Applications screens that
moved to query-string URLs. The manifest row is updated in the same commit; nothing else in the
manifest changes.

Never `hx-push-url="true"` — always the canonical URL above.

## `projects-list`

- Columns: **Code** (`code`) · **Project** (`name`, link to `project-view`; archived badge) ·
  **Customer** (`organization_name`, em dash when masked or absent) · **Status** (badge) ·
  **Owner** (`owner_name`, "—") · **Due** (`due_date`, `danger` when overdue and not
  completed/cancelled) · **Progress** (`tasks_done`/`tasks_total` + a `.progress` bar) ·
  **Actions** (Edit).
- Search `q`: `name ILIKE` or `code ILIKE`. Filters: `status` (any of the five, or `open` =
  planning+active+on_hold, the default), `organization`, `department`, `over_budget=1`
  (see below). Archived rows are hidden unless `status=archived`.
- Sort allowlist: `name`, `due_date`, `updated_at`, `code` (default `updated_at DESC`).
  Page size 25, server-rendered pagination. Pattern B; the region `#projects-list-results`
  refreshes on `projectChanged` and `taskChanged` (progress moves when tasks move).
- Empty state, and it must be honest: when the caller holds no `projects` grant and is on no
  project, "You are not on any projects yet. Tasks assigned to you are under My tasks." —
  not "No projects".
- **`over_budget` and money:** hours and expenses belong to modules that are not built yet
  (Time & work log, and Expenses' project link). The filter is offered **only** to a caller
  holding both the `time` and `expenses` grants; for anyone else the control is absent and the
  parameter is refused by name. See "Budget" below — this slice never prints a 0 that reads as
  a fact.

## `project-view`

Header: code · name · status badge · customer link · owner · department · dates · tags.
Tabs (`tab`, the card-header tab pattern): **Overview** (default) · **Tasks** · **Team** ·
**Milestones**.

- **Overview** — description, dates, billing type, budget card, comments
  (`mcp_record_comments`), and the "what is blocking this" list: tasks with
  `status = 'blocked'` (showing `blocked_reason`) and tasks with `has_open_dependencies` (P5).
- **Tasks** — the project's tasks from `mcp_tasks`, grouped by milestone then `sort_order`,
  each row offering status change, assign and complete inline (Pattern C on the row). "Add task"
  links to `/tasks/new?project={id}`.
- **Team** — `mcp_project_members`: display name, **kind badge** (Person / Agent — P7 is
  answered on this screen, not only through MCP), role, added. Add member (a member from the
  team directory + optional role) and Remove, both `mod:projects`.
- **Milestones** — `mcp_milestones` by `sort_order`: name, due date, done state, complete
  toggle, edit, delete.

**Budget card (the honest-degradation rule, copied from Agent HR):** it prints `budget_hours`,
`budget_amount`, `currency`, `billing_type`, `hourly_rate` (masked for externals by the view)
and the task progress it can compute. Where hours and spend would go, it says
*"Hours logged and spend arrive with the Time & work log slice (phase 3) and the project link on
Expenses."* It does **not** render 0.00 of 40.00 hours, because a zero there reads as a fact and
this module cannot yet know it.

`data-screen="project-view"`, `data-entity="project"`, `data-record-id="{id}"` on `#page-content`.

## `tasks-list`

- Columns: **Task** (`title`, link) · **Project** (`project_name`, em dash when masked) ·
  **Assignee** (`assignee_name` + Agent badge when `assignee_kind = 'agent'`) · **Status**
  (badge; blocked shows a `danger` badge and the reason as its `title`) · **Priority** ·
  **Due** (`danger` when overdue) · **Actions** (Complete / Edit).
- Filters: `mine=1` (assignee = me), `assignee` (member id), `project`, `status`,
  `overdue=1` (`due_date < current_date AND status NOT IN ('done','cancelled')`),
  `blocked=1` (`status='blocked' OR has_open_dependencies`), `agents=1`
  (`assignee_kind='agent'` — P7). `q` matches `title ILIKE`.
- Default view: everything the view returns, newest-updated first, with a **My tasks** chip
  that sets `mine=1`. Sort allowlist: `due_date`, `priority`, `updated_at`, `title`
  (default `due_date ASC NULLS LAST`). Page size 25.
- Region `#tasks-list-results` refreshes on `taskChanged`.
- Empty state: "Nothing on your plate." / "No tasks match those filters."

## `task-view`

Header: title · status badge · priority · project link · assignee · due date · department ·
tags. Panels: **Checklist** (`mcp_task_checklist_items`, add + toggle, a done count) ·
**Depends on** (`mcp_task_dependencies`, add + remove; a masked dependency shows
"A task you cannot see" and no link) · **Blocked** (reason, when blocked) ·
**Comments** (`mcp_record_comments`).

## Forms

**Project form** (`project-add` / `project-edit`), ids `project-form-field-{name}`:

| Field | Input | Required | Validation |
| --- | --- | --- | --- |
| name | text | ✔ | 1–200 |
| description | textarea | — | ≤ 10000 |
| organization_id | select (customers from `mcp_organizations`) | — | a visible organization |
| deal_id | select (open deals of that organization) | — | a visible deal; Pattern A fragment reloads it when the organization changes |
| department_id | select (my departments; super-admin: all) | — | one of them, or blank (note printed) |
| owner_member_id | select (team directory) | — | default self |
| status | select | ✔ | the five; default `planning` |
| start_date / due_date | date ×2 | — | `due_date >= start_date` when both are given |
| billing_type | select | ✔ | fixed / hourly / non_billable; default `hourly` |
| hourly_rate | number | — | ≥ 0, 2dp; blank allowed (the Time slice decides the fallback) |
| budget_hours | number | — | ≥ 0, 2dp |
| budget_amount | number | — | ≥ 0, 2dp |
| currency | select (ISO codes in use + base) | ✔ | 3 letters; default the business base currency |

`code` is never on the form — the write path takes it from `next_document_number('project')`.

**Task form** (`task-add` / `task-edit`), ids `task-form-field-{name}`:
`title` (✔ 1–200), `description` (≤ 10000), `project_id` (select of visible projects),
`milestone_id` (select — Pattern A fragment reloaded from the chosen project),
`assignee_member_id` (team directory, humans **and** agents, kind shown in the option label),
`department_id`, `status` (✔ default `todo`), `blocked_reason` (required 1–500 **only** when
status is `blocked`; cleared when status leaves `blocked`), `priority` (✔ default `normal`),
`start_date`, `due_date` (`due_date >= start_date`), `estimate_hours` (≥ 0),
`task_type` (text ≤ 60), `organization_id` (customer work with no project).
`parent_task_id` and `ticket_id` are **not** on the form (see Out of scope).

**Milestone form** (`milestone-add` / `milestone-edit`), ids `milestone-form-field-{name}`:
`project` (hidden on add, from the param), `name` (✔ 1–200), `due_date`, `sort_order` (integer,
default `max+10` within the project).

No modals. Forms are full pages in `#page-content`; save/cancel in the page header.

## Files (exactly these — no additions)

```
html/projects/index.php · form.php · view.php · save.php · status.php · archive.php · delete.php
html/projects/member-add.php · member-remove.php
html/projects/milestone-save.php · milestone-complete.php · milestone-delete.php
html/projects/deals-fragment.php                      (Pattern A: deals of the chosen customer)
html/projects/milestones/form.php                     (milestone-add / milestone-edit)
html/tasks/index.php · form.php · view.php · save.php · assign.php · status.php
html/tasks/complete.php · reopen.php · reschedule.php · delete.php
html/tasks/dependency-add.php · dependency-remove.php
html/tasks/checklist-add.php · checklist-toggle.php
html/tasks/milestones-fragment.php                    (Pattern A: milestones of the chosen project)

app/features/projects/queries.php · render.php
app/features/tasks/queries.php · render.php

app/views/projects/page.php
app/views/projects/partials/table.php · row.php · form.php · project.php
app/views/projects/partials/tab-overview.php · tab-tasks.php · tab-team.php · tab-milestones.php
app/views/projects/partials/task-row.php · member-row.php · milestone-row.php · form-milestone.php
app/views/tasks/page.php
app/views/tasks/partials/table.php · row.php · form.php · task.php
app/views/tasks/partials/checklist.php · checklist-item.php · dependencies.php

mcp/business_projects.py            (registered by records_server.py with exactly two appended lines)
```

Per the exemplar's two structural additions: `render.php` per feature holds the success-branch
re-render (`render_projects_list()`, `render_project_page()`, `render_tasks_list()`,
`render_task_page()`), and every self-refreshing region has its own `*-row`/list partial so the
first paint and the Pattern A/C re-render emit identical markup.

## Query functions (signatures fixed; PDO first, no request/response awareness)

```php
// app/features/projects/queries.php
const PROJECTS_PAGE_SIZE = 25;
const PROJECTS_SORT_ALLOWED = ['name', 'due_date', 'updated_at', 'code'];
const PROJECT_STATUSES = ['planning', 'active', 'on_hold', 'completed', 'cancelled'];
const PROJECT_BILLING_TYPES = ['fixed', 'hourly', 'non_billable'];

find_projects(PDO, string $q, string $status, ?int $organizationId, ?int $departmentId,
              string $sort, int $page): array        // + total_count window
find_project(PDO, int $id): ?array                   // mcp_projects
find_project_options(PDO): array                     // id + code + name, for selects
insert_project(PDO, array $f): array                 // takes next_document_number('project')
update_project(PDO, int $id, array $f): array
set_project_status(PDO, int $id, string $status): array   // completed → completed_at = now(), else NULL
archive_project(PDO, int $id, bool $archived): array
delete_project(PDO, int $id): bool                   // 23503 → "it has time or invoices" message
find_project_members(PDO, int $projectId): array     // mcp_project_members
add_project_member(PDO, int $projectId, int $memberId, ?string $role): array
remove_project_member(PDO, int $projectId, int $memberId): bool
find_milestones(PDO, int $projectId): array          // mcp_milestones
find_milestone(PDO, int $id): ?array
upsert_milestone(PDO, ?int $id, int $projectId, array $f): array
complete_milestone(PDO, int $id, bool $done): array
delete_milestone(PDO, int $id): bool
project_blockers(PDO, int $projectId): array         // blocked tasks + tasks with open dependencies (P5)

// app/features/tasks/queries.php
const TASKS_PAGE_SIZE = 25;
const TASKS_SORT_ALLOWED = ['due_date', 'priority', 'updated_at', 'title'];
const TASK_STATUSES = ['todo', 'in_progress', 'blocked', 'done', 'cancelled'];
const TASK_PRIORITIES = ['low', 'normal', 'high', 'urgent'];

find_tasks(PDO, array $filters, string $sort, int $page): array   // filters: q, mine, assignee,
                                                                  // project, status, overdue,
                                                                  // blocked, agents, milestone
find_task(PDO, int $id): ?array
find_tasks_for_project(PDO, int $projectId): array   // grouped by milestone, then sort_order
insert_task(PDO, array $f): array
update_task(PDO, int $id, array $f): array
assign_task(PDO, int $id, ?int $memberId): array
set_task_status(PDO, int $id, string $status, ?string $blockedReason): array
complete_task(PDO, int $id): array                   // status done + completed_at
reopen_task(PDO, int $id): array                     // status todo + completed_at NULL
reschedule_task(PDO, int $id, ?string $dueDate): array
delete_task(PDO, int $id): bool
find_task_dependencies(PDO, int $taskId): array      // mcp_task_dependencies
add_task_dependency(PDO, int $taskId, int $dependsOnId): array
remove_task_dependency(PDO, int $taskId, int $dependsOnId): bool
task_would_cycle(PDO, int $taskId, int $dependsOnId): bool   // recursive CTE over task_dependencies
find_checklist_items(PDO, int $taskId): array
add_checklist_item(PDO, int $taskId, string $body): array
toggle_checklist_item(PDO, int $id, bool $done): array
find_checklist_item(PDO, int $id): ?array
```

Every `find_*` reads an `mcp_*` view. Every mutation writes a base table and returns
`RETURNING *`. Multi-statement mutations (`insert_task` with a milestone default,
`upsert_milestone` with `sort_order = max+10`) use an explicit transaction.

## Action-manifest entries (copied from the manifest — do not invent)

`project_create`, `project_update` (`save.php`) · `project_set_status` (`status.php`) ·
`project_add_member` (`member-add.php`) · `project_remove_member` (`member-remove.php`) ·
`project_archive` (`archive.php`) · `project_delete` (`delete.php`, ✔ confirm, admin, agent
approval `delete`) · `milestone_save` (`milestone-save.php`) · `milestone_complete`
(`milestone-complete.php`) · `milestone_delete` (`milestone-delete.php`, ✔, `delete`) ·
`task_create`, `task_update` (`/tasks/save.php`) · `task_assign` (`/tasks/assign.php`) ·
`task_set_status` (`/tasks/status.php`) · `task_complete` (`/tasks/complete.php`) ·
`task_reopen` (`/tasks/reopen.php`) · `task_reschedule` (`/tasks/reschedule.php`) ·
`task_add_dependency` / `task_remove_dependency` · `checklist_item_add` /
`checklist_item_toggle` · `task_delete` (`/tasks/delete.php`, ✔, `delete`).

Every state-changing endpoint, in this order:
`require_post()` → `verify_csrf()` → gate → row re-read through the view → validation →
`check_approval()` → write → `log_activity()` → `emit_action_status(true, …)` →
`hx_trigger('{entity}Changed')` → whole refreshed screen.
Triggers: `projectChanged`, `taskChanged`, `milestoneChanged`, `projectMemberChanged`,
`dependencyChanged`, `checklistChanged`, plus the shared `taggingChanged` / `commentChanged`.

**A validation failure answers `emit_action_status(false, ['errors' => …])` and re-renders the
form** — never a bare 200 with a form in it, which every non-browser caller reads as success.

## Approval awareness

`project_delete`, `milestone_delete` and `task_delete` carry the `delete` category, so each calls
`check_approval($pdo, $action, $logEvent, $summary, $payload, $entityType, $entityId)` **before
touching a row**. A match writes an `approval_requests` row, emits `pending_approval`, and
executes nothing. Humans are not paused by the default policies; agents are. No money threshold
applies in this slice — nothing here carries an amount.

## Activity log events

`project.create/update/set_status/archive/delete` · `project_member.create/remove` ·
`milestone.save/complete/delete` · `task.create/update/assign/set_status/complete/reopen/
reschedule/delete` · `task_dependency.create/remove` · `task_checklist_item.create/toggle` ·
`screen.view` on every GET screen with the screen id above.

`before`/`after` carry the changed fields. `task.assign` puts the **old and new assignee ids** in
`before`/`after` and `task.reschedule` the old and new dates — P10 ("who reassigned or rescheduled
this, and how many times") is answered by `action_counts` reading exactly those rows, and P11
(`cycle_times` from `task.create` to `task.complete`, grouped by `task_type`) needs `task_type`
in `after` on **`task.create`**. Get those three payloads right or two activity questions die.

## MCP tools this slice must leave working (`mcp/business_projects.py`)

| Tool | Questions | Reads |
| --- | --- | --- |
| `find_projects` | P1, P8 | `mcp_projects` (+ `mcp_time_entries`, `mcp_expenses` only for `over_budget`) |
| `get_project` | P4, P5, P6, P9 | `mcp_projects`, `mcp_project_members`, `mcp_tasks`, `mcp_task_dependencies`, `mcp_milestones` |
| `find_tasks` | P2, P3, P5, P7 | `mcp_tasks`, `mcp_task_dependencies` |
| `upcoming_milestones` | P9 | `mcp_milestones` |

- `my_work` (P2, DB2) and `team_workload` (DB5, K1) span modules that do not exist yet
  (appointments, tickets, duties). **Not built here.** They are named in the slice's Out of scope
  with the slice that owns them, and `find_tasks(assignee_member_id=me)` answers P2 today.
- **`over_budget` refuses rather than under-reports.** Hours and project expenses live behind the
  `time` and `expenses` grants; a caller without both gets an error naming the missing grant, not
  a smaller number. This is the accountant-export fix applied before the defect happens.
- Tools take the caller's own visibility from the views — no tool re-implements a WHERE.

## Acceptance (the demo this slice owes, over real HTTP, from four seats)

1. **Super-admin:** create a project for an existing customer, add two team members (one of them
   the agent `Ledger Bot`), add two milestones, add five tasks across them, set one `blocked`
   with a reason, make one depend on another, complete a milestone.
2. **A `projects`-grant holder in the project's department:** sees it, edits it, reassigns a task;
   `task.assign` shows old and new assignee in the activity trail.
3. **An ordinary user with no grants who is a project member:** reaches `/projects/` and the
   project (the contributor case the gate exists for), and **cannot** delete it.
4. **An ordinary user with no grants who is only an assignee:** sees the task at `/tasks/`,
   sees **no** project name on it (db/080), completes it, and gets a 404 on `/projects/{id}`.
5. **An agent** attempting `task_delete` is paused as an approval request and nothing is removed.
6. Each of the four MCP tools answers against the data the screens created — `get_project`
   returns the blockers, `find_tasks(agents=true)` returns the agent's task, `upcoming_milestones`
   returns the milestone due inside 14 days, `find_projects(over_budget=true)` refuses the caller
   without the `time` grant by name.
7. 375px: no horizontal scroll on either list, the project tabs wrap, the header actions collapse.

## Out of scope for this slice

- **Hours, utilization and spend** on a project (Time & work log, phase 3; Expenses' project
  link). The budget card says so rather than printing zeros.
- **AI spend per project (P13)** — the prompt ledger, phase 5.
- `my_work` and `team_workload` tools, and the `/my-work` screen — they need appointments,
  tickets and duties; whichever slice lands last owns them.
- **Sub-tasks** (`tasks.parent_task_id`) and **ticket origin** (`tasks.ticket_id`): the columns
  exist, the slice neither edits nor invents UI for them. Tickets owns the second.
- Gantt charts, drag-and-drop ordering, recurring tasks, task templates, bulk edit, project
  templates, cloning, task watchers/notifications.
- Any change to the cert-study `study_plans` / `plan_items` tables or screens: the conversion is
  a **new** module beside them, exactly as the build plan says.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none — the two things that would have been questions are answered above: the gate follows the
  view, and the milestone-add URL is amended in the manifest.)
