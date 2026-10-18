# Projects — the plan (Phase 0 of the new-app workflow, with the kernel's part)

2026-09-28 · the second application from us beside the kernel (build plan phase 7, **A9**): an Agile
Scrum project-management suite in the manner of Jira and Linear — **backlogs, sprints and a kanban
board** — on the standard Apache/PHP/HTMX stack, in its own repository `/srv/apps/projects`, served as
`projects.<domain>`, signed in by the kernel, usable by OS users and by everyone else the kernel admits,
and **installed by default with the kernel**. Built with `htmx-php-builder` (how it is built) and
fitted to `maludb-os-integration` 0.4.1 (how it fits), exactly as HR was (`/srv/apps/hr/docs/hr-design.md`).

> **Status: approved 2026-09-28 with the owner's six answers (§12).** This document moves to
> `/srv/apps/projects/docs/projects-design.md` as Phase 0; Phase 1 (the whole schema, the MCP tool surface, the
> action manifest and every slice spec) is the checkpoint before any PHP; K1 and K2 come first in the kernel.

## 1. What Projects is, and is not

Projects **owns work**: what is to be done, by whom, in which sprint, in what order, and what state it
is in. A project has a backlog of issues (stories, tasks, bugs, grouped under epics), plans them into
sprints, works them across a board, and reports velocity, burndown and cycle time. It is the Jira or
Linear a small business or an agency would otherwise pay for, with one difference that matters here:
**agents are assignees**. An issue can be given to an agent as readily as to a person, the board shows
the agent's work beside everyone else's, and the agent reads its assignments through the same door
people use (the Projects MCP servers) and moves them through the kernel's Actions MCP.

The kernel **owns the directory** (who exists, their departments, who administers them) and the
**identity** (sign-on at `app.<domain>`; no login form, no password, no account in Projects). Projects
mirrors the directory with the kernel's ids and never changes it. Projects ships its expert and one
proposed agent (a Scrum desk), which the kernel hires and runs; Projects never calls a model.

Out of scope, by the owner's standing decisions and by this plan: money (no billing rates, budgets in
currency, invoicing — the accounting application's, if any; hours and points are Projects' units);
time tracking as a product (a worklog line on an issue is in; timesheets, approvals of hours and pay
are not); documents and wikis (an issue's description and attachments are in; a page tree is not);
customer portals (see §3: an external who works here is a kernel member); CRM links (the kernel has no
CRM — a project may name a customer as text); releases/versions and roadmaps (a later slice, if asked).

## 2. Who uses it (the actors)

- **A member of the business** (any human the kernel admits to Projects): reads projects they may see,
  works their issues, comments, moves cards on the board.
- **A product owner** of a project: owns the backlog, ranks it, writes and accepts stories, plans sprints.
- **A scrum master** of a project: opens and closes sprints, keeps the board's rules (columns, WIP),
  reads the reports.
- **A project admin** (usually the department's admin or a super-admin): creates projects, sets
  workflow, board and labels, names the project's team and roles.
- **An external collaborator** (a client, a contractor): a kernel member flagged `is_external`, admitted
  to Projects by a grant, seeing only the projects they are a member of (§3).
- **An agent** (the project's expert, the Scrum desk, any agent given issues): reads through the two MCP
  servers under a run token, acts through the kernel's Actions MCP, pauses for approval where an action
  says so.
- **The kernel** (the platform): signs people in, delivers the directory, runs the agents, asks
  Projects for a person's open work (a future My Work aggregation) and for its roles.

## 3. Who sees what — the rules, in one place

- **Access to Projects** is a kernel grant (`application_access`): nobody by default; a super-admin
  grants a member, a department or a site's residents, with a set of roles (kernel C5). On a default
  install (§10) every standing department is granted the **Member** role, so every insider can launch.
- **Roles** (published by `app_roles`, `os.app-roles/1`; exactly one `is_admin`):

  | Role | Capability | Rights |
  |---|---|---|
  | Viewer | read | `project.read` |
  | Member | write | + `issue.write`, `comment.write`, `board.move`, `worklog.write` |
  | Product Owner | write | + `backlog.rank`, `sprint.plan`, `issue.accept`, `epic.write` |
  | Scrum Master | write | + `sprint.run` (open, close, carry over), `board.configure` |
  | Projects Admin | admin | every right, + `project.admin` (create, archive, workflow, team, labels) |

  A role is held business-wide from the grant; **inside a project, the project's team list narrows it**:
  a project is *open* (every holder of the role sees it) or *private* (its team only). A private
  project is how an external collaborator sees one project and nothing else. `app_has_right(right,
  project_id)` is the one gate, in SQL for the views, in PHP for the handlers and the menu.
- **Scope**: **unscoped** (`scope_kind: none`). The contract's own example of a department-scoped
  "project tool" is considered and not taken: a project's team crosses departments (a designer, an
  engineer, an agent from IT), and a department-scoped installation would cut it in two. The department
  is a *property* of a project (who owns it, whose admin administers it), not a wall. Should a business
  want walls (an agency with client teams that must never see each other), private projects give them
  per project; a scoped mode is a later decision, not a rewrite (`scope_id` on `projects` is reserved
  NULL from day one).
- **Externals**: today a member flagged external sees an empty launcher (`app_is_insider()` gates
  `mcp_my_applications`, recorded open in `docs/build-specs/kernel-sign-on.md`). **Kernel prerequisite
  K2 (§10) opens the launcher to an external with a live grant.** Until then, externals cannot reach
  Projects, and this plan does not work around it inside the application.
- **Agents** see what the run facts vouch for (the run-facts gate, as HR): the tools the kernel names on
  their grants, and rows the same views admit for the agent's member id. An agent's page in the kernel
  already shows its runs; its issues are Projects' to show.

## 4. Memory model — what Projects remembers

Named in domain language; the schema is a Phase 1 translation.

| Entity | What it is | Key facts |
|---|---|---|
| **Project** | A body of work with a team and a key | key (`PROJ`, unique, used in issue keys), name, description, department (owner), lead (a member), visibility open/private, status active/archived, issue counter, workflow, board, created/archived |
| **Team membership** | Who works on a project, in what project role | project, member (human or agent), role (lead/PO/SM/member/viewer), since |
| **Issue** | The unit of work: a story, a task, a bug, or a subtask | key `PROJ-123`, project, type, summary, description (markdown), status (of the project's workflow), resolution, priority, story points, estimate (hours, optional), assignee (human or agent, or none), reporter, parent (for subtasks), epic, sprint (or backlog), **rank** (backlog order), labels, components, due date, created/updated/resolved |
| **Epic** | A large body of work that issues roll up to | project, key, name, summary, colour, status, target date |
| **Sprint** | A time-box the team commits issues to | project, name, goal, start, end, state future/active/closed, committed points at start, completed points at close, carried over |
| **Workflow** | The statuses a project's issues move through and the allowed moves | statuses (name, category to-do/in-progress/done, order), transitions (from, to); the default: To do → In progress → In review → Done |
| **Board** | How the active sprint (or the whole backlog, for kanban) is shown | columns (name, mapped statuses, WIP limit), swimlane by assignee/epic/none, kanban or scrum mode |
| **Comment** | What someone said on an issue | issue, author, body, when, edited |
| **Attachment** | A file on an issue | issue, name, size, mime, stored path, by, when |
| **Issue link** | A typed relation between issues | from, to, kind blocks/is-blocked-by/relates/duplicates (blocks is a dependency; cycles refused) |
| **Label**, **Component** | Free tags, and a project's named parts with an optional default assignee | project-scoped names |
| **Watcher** | A member who wants the issue's changes | issue, member |
| **Worklog** | Hours someone logged on an issue | issue, member, hours, date, note |
| **Checklist item** | A line inside an issue that is done or not | issue, text, done, order |
| **Saved filter** | A named query a person keeps | owner, name, filter, shared or private |
| **Issue history** | Every change to an issue's fields | from `activity_log` — not a second table |

The **mirror**: `members` (id, name, kind human/agent, status, roles, is_external), `departments`,
`department_members` — the kernel's ids, from the claims and the change feed, never edited here.

**Activity memory** (`activity_log`, one `log_activity()` funnel, `entity.verb`, shipped to the tenant's
MaluDB tagged `application: projects`): every screen view, every action, with the payloads the
questions need — `issue.transition` carries from/to status and the sprint; `issue.assign` old/new
assignee; `issue.estimate` old/new points; `issue.rank` old/new rank; `sprint.start` the committed issue
keys and points, `sprint.close` completed/carried; `board.move` the column and who dragged.

## 5. The question inventory — what Projects exists to answer

Record questions (answered by screens and by the records MCP server):

1. What projects exist, which are mine, and what state is each in? (projects list)
2. What is on my plate, across projects, and what is due or overdue? (my work; `my_work` tool)
3. What is in this project's backlog, in rank order, and what is unestimated? (backlog)
4. What is in the active sprint, by status and by assignee, and what is blocked? (board)
5. What is this issue — its story, comments, subtasks, links, attachments, history? (issue view)
6. Who is working on what, and who has nothing? (board by assignee, `workload`)
7. How is the sprint going — points done vs committed, day by day? (burndown)
8. What did we finish in the last sprints, and what can we commit to next? (velocity)
9. How long does an issue take from start to done, by type? (cycle time)
10. What was added to or removed from the sprint after it started? (scope change)
11. How far along is each epic? (epic progress)
12. Which issues are blocked, and by what? Which block the most? (blocked, links)
13. Which issues have an agent as assignee, and how are they doing? (agents' work)
14. What is unassigned, stale (no change in N days), or without a sprint for too long? (hygiene)
15. What is in review waiting on me? (reviewer's queue: assigned or watching, status In review)
16. What did the team log in hours this sprint, per issue? (worklogs)
17. Find the issue I half-remember. (search: key, text, label, assignee)

Activity questions (answered from MaluDB through the activity MCP server; nothing is built for them
but the log):

18. When did PROJ-123 move to In progress, and who moved it?
19. Who changed the estimate on this story, and from what?
20. When was this issue pulled into the sprint, and by whom?
21. What did Becky (an agent) do on the project last week?
22. Who reassigned this from Jack to Sasha, and why (the note)?
23. What happened in this project yesterday?
24. When did we last close a sprint with everything done?

Run the loop: every entity in §4 answers a question above; every question maps to a screen or a tool
in §6–§7. (Releases, roadmaps and timesheets answer questions nobody in §2 asks yet — cut.)

## 6. Screens (the frequent questions), in Jira's and Linear's layout, the nxl look

Every screen: the design system's rules — no modals, full-page create/edit, Save/Cancel in the header,
375 px with 44 px targets, lists of named things as cards, ledgers as tables, explicit `hx-push-url`,
kebab ids, and the kernel's click-around rules (every name a link, every page a way back).

| Screen | What it answers | Notes |
|---|---|---|
| `/` dashboard | 1, 2, 4 | my open issues, my projects, the active sprints' burndown sparkline |
| `/projects` | 1 | cards by department; open/private badge; New |
| `/projects/{key}` | 1, 11 | overview: lead, team, active sprint, epics with progress, recent activity |
| `/projects/{key}/backlog` | 3, 10 | **the backlog**: ranked list, inline estimate, the *next sprint* box above it; move up/down and "move to sprint N" as actions (drag-and-drop is an enhancement over them, §12) |
| `/projects/{key}/board` | 4, 6, 12 | **the board**: columns from the board config, cards (key, summary, assignee avatar, points, labels, blocked mark), swimlanes, WIP counts; a card's status change is a POST (`issue_transition`) — dragging is the enhancement; the panel scrolls horizontally with a visible scrollbar |
| `/projects/{key}/sprints` | 7, 8, 10 | sprints list; a sprint's page: goal, burndown, scope changes, close with carry-over |
| `/projects/{key}/epics` | 11 | epics as cards with progress bars; an epic's page lists its issues |
| `/projects/{key}/issues` | 17, 14, 15 | the issue table with filters (type, status, assignee, sprint, label, epic, text), saved filters |
| `/issues/{KEY-n}` | 5, 12, 16 | the issue: fields column, description, subtasks, links, attachments, checklist, worklogs, comments, history (from activity), watch |
| `/issues/new`, `/issues/{KEY-n}/edit` | — | full-page forms (type decides the fields) |
| `/projects/{key}/reports` | 7, 8, 9 | velocity (last 6 sprints), burndown (active sprint), cycle time by type, cumulative flow |
| `/projects/{key}/settings` | — | workflow (statuses, transitions), board (columns, WIP, swimlane), labels, components, team and roles, visibility, archive |
| `/my-work` | 2, 15 | assigned to me, watching, in review for me — across projects; the same shape the kernel's future My Work asks for |
| `/activity` | 23 | the application's trail, filtered by project |

The command bar on every screen posts to the kernel's chat endpoint for the expert (18–24 in words).

## 7. The agents' door

**Records MCP** (`/mcp/records`, FastMCP, read-only, run-facts gate): `find_projects`, `get_project`,
`find_issues` (every filter of the issues screen), `get_issue`, `backlog`, `board` (the active sprint by
column), `sprint_status`, `burndown`, `velocity`, `cycle_time`, `sprint_scope_changes`, `epic_progress`,
`blocked_issues`, `workload`, `my_work` (member → the shape the kernel's aggregator wants: kind, id,
title, detail, due_at, state blocked|overdue|due today|due, href, urgency), `hygiene` (unassigned,
stale, unestimated), `worklogs`, `records_search` (guarded), `app_roles` (the kernel's token only).

**Activity MCP** (`/mcp/activity`): `issue_history`, `who_did` (member, since), `project_activity`,
`sprint_events`, `activity_search`.

**Actions** (the manifest → `mcp/action_registry.json` → the kernel's `mcp/registries/projects.json`,
JSON-mode handlers on the loopback vhost; an agent's call pauses on the kernel's hook where an action
carries a category): `project_create`, `project_update`, `project_archive` (deletion), `team_add`,
`team_remove`, `issue_create`, `issue_update`, `issue_assign`, `issue_transition`, `issue_estimate`,
`issue_rank`, `issue_move_to_sprint`, `issue_link`, `issue_unlink`, `issue_delete` (deletion),
`comment_add`, `comment_delete` (deletion), `checklist_add`, `checklist_toggle`, `worklog_add`,
`attachment_add` (through the screen only; agents cannot), `watch`, `unwatch`, `epic_create`,
`epic_update`, `sprint_create`, `sprint_start` (other: the commitment is a team's), `sprint_close`
(other), `sprint_update`, `label_save`, `component_save`, `workflow_save` (other), `board_save` (other),
`filter_save`. Every create answers a `location` ending in the id.

**Agents shipped** (`maludb-os.json` `agents[]`, proposed on install, hired by a person in one click):
- **expert** (`os/expert.md`) — answers questions about the work through the tools; never moves an issue
  unasked.
- **scrum_master** (`os/scrum_master.md`; hired on install, §12) — a daily duty: flags stale, unassigned and unestimated issues,
  drafts the sprint report at close, nudges blocked issues' owners; acts only through registered
  actions, which pause where they must.

**Skills shipped**: `projects-basics` (skill: the vocabulary and the tools), `sprint-planning`
(runbook), `sprint-close` (runbook), `backlog-triage` (runbook) — runbooks per db/153, given to
agents from the application's page.

## 8. The kernel's part (owed to this application)

| # | Kernel item | Why |
|---|---|---|
| K1 | **Catalog entry `projects` (kind `ours`) seeded by a migration** (db/158, built 2026-09-28), business area *Work* (a `nav_groups` row if none fits) | so every installation knows the application exists before it is installed; HR's row was added by hand |
| K2 | **Externals can launch**: `app_can_launch()` + `mcp_launcher_applications` (db/159, built 2026-09-28) | §3; was open in `kernel-sign-on.md` |
| K3 | **`bin/app_install.php plan|apply <repo>`** (build plan C4, not built) — the deterministic installer the `os-install` skill drives: database, `.env`, ports, vhost, services, registration calls, token, registry, skills, proposed agents | Projects is installed by it, not by hand as HR was |
| K4 | **Default applications on install**: the tenant provisioning script (build plan phase 4, not built) gains a step *install the default applications* — `hr` and `projects` — from their repositories, then grants every standing department the Member role in Projects and proposes the agents | "a default part of the deploy" |
| K5 | **My Work aggregation** (later): a kernel screen that asks every `ours` application with a `my_work` tool for a person's open work | Projects' `my_work` is designed to that shape now |

K3 and K4 are the same work Reservations and ZozoCal need; Projects is the application that makes them
worth building now. K1 and K2 are small and come first.

## 9. Decisions taken in this plan (the owner may overturn any)

1. **Scrum vocabulary, Linear's calm.** Issues, epics, sprints, points; a board per project; no
   multi-project boards, no custom fields, no per-issue-type workflows in the first version.
2. **One workflow per project**, editable in settings, seeded with To do / In progress / In review /
   Done; categories drive the board and the reports, so a renamed status still burns down.
3. **Points, not hours, for planning**; hours only as worklogs. Velocity and burndown are in points.
4. **Agents are first-class assignees.** An issue given to an agent is shown as such; the Scrum desk
   works only through registered actions.
5. **Unscoped**, with open/private projects (§3). `scope_id` reserved.
6. **Drag-and-drop is an enhancement, never the only way.** Every board and backlog move is a POST
   with a button; one small vanilla drag library (SortableJS, ~45 KB, no build step) is the one upgrade
   the board earns from the stack's baseline, posting the same actions; keyboard users get the buttons.
7. **Live boards by polling**, not sockets: the board and the active sprint re-read every 30 s
   (`hx-trigger="every 30s"`) and on the actions' triggers; SSE is the upgrade if a team feels the lag.
8. **Attachments on disk** under `storage/attachments/<project>/<issue>/`, size-capped, served through
   a PHP handler that checks the gate — never a public path.
9. **Issue keys are permanent**; moving an issue between projects gives it a new key and keeps the old
   as an alias (`issue_aliases`) so links and memory stay true.
10. **History is the activity log**, presented on the issue; no second history table.

## 10. Build order, gates and size

Mirrors HR. Each phase is a checkpoint the owner approves; commit after every step; nothing is pushed.

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | this document, moved into the repository as `docs/projects-design.md` | owner's go |
| 1 | the whole schema (`db/001`–`0NN`: identity + activity + settings from HR's 001–004 verbatim, then projects, issues, sprints, boards, links, comments, attachments, worklogs, filters, `mcp_*` views, roles/rights `app_has_right`), `docs/projects-mcp-tool-surface.md`, `docs/projects-action-manifest.md`, one slice spec per slice below with **Projects & issues** as the exemplar | **approved together, before any PHP** |
| 2 | `/sso`, `/sso/logout`, the mirror and its timer, the ingest bridge, the nxl shell with the command bar, `/api/v1/health`, the vhost (`projects.<domain>` + loopback), the dashboard | proven at 375 and 1280, hand-off token replay refused |
| 3 | slices in order: **(1) projects and issues** (exemplar: list, project page, issue view/create/edit, comments, checklist, watch, search) → **(2) backlog and sprints** (rank, estimate, create/start/close sprint, carry-over, burndown data) → **(3) the board** (columns, WIP, swimlanes, transition, polling; then drag-and-drop) → **(4) epics, links, subtasks, labels, components, attachments, worklogs** → **(5) reports** (velocity, burndown, cycle time, cumulative flow, scope change) → **(6) settings** (workflow, board, team and roles, visibility, archive) → **(7) my work, saved filters, activity** | each slice: screens + handlers + logging + manifest entries + tools, at 375 and 1280 |
| 4 | the two MCP servers with the run-facts gate; `app_roles`; the registry on the kernel; skills and runbooks imported; the expert and the Scrum desk proposed; `maludb-os.json`; `deploy/` | the command bar answers a real question through the kernel; an agent moves an issue through the Actions MCP and a deletion pauses |
| K | K1, K2 first; K3 and K4 alongside phase 4 so Projects is the first application installed by the script and the first shipped by default | a fresh installation gets HR and Projects without a hand touching a file |

Size, by HR's measure (HR: nine migrations, six slices, 35 actions, 26 tools, built in three days with
a planning-class model on the exemplar and workers on the rest): Projects is larger — about twelve
migrations, seven slices, ~40 actions, ~25 tools — call it **five to six days** of the same working, plus
two for K3–K4.

## 11. Ports, names and files

- Repository `/srv/apps/projects`; database `<tenant>_projects` (`subello_projects` here); roles
  `projects_rw`, `projects_records_ro`, `projects_activity_ro`; MaluDB: the tenant's one memory, episodes
  tagged `projects`.
- Vhost `projects.<domain>` (`/etc/hosts` here until DNS), loopback `127.0.0.1:8181`; MCP records
  `:8823`, activity `:8824` (the next free block after HR; confirmed against `ss -ltn` at install).
- `maludb-os.json`: `catalog_key projects`, `business_area "Work"`, `category other`, `icon
  feather-trello`, `criticality medium`, `sso {/sso, /sso/logout}`, `directory {reads: true, writes:
  false}`, `assistant {command_bar: true, agent: expert}`, `agents [expert, scrum_master]`, `skills`
  (four), `endpoints` (records, activity, web, health), `actions`, `approvals` (deletions → `deletion`;
  sprint start/close, workflow and board changes → `other`), `services` (records-mcp, activity-mcp,
  activity-ingest + timer, directory-sync + timer). No `scopes` block.
- Kernel files: `mcp/registries/projects.json`, the db/154 catalog seed, the installer.

## 12. The owner's answers (2026-09-28) — decisions, not questions

1. **Externals: yes, open the launcher.** K2 is built first, before Phase 2, so a client can sit on a private
   project from the first sprint.
2. **JavaScript and packages are fine for Projects.** SortableJS for the board and the backlog, and any other
   vendored package the board or the reports earn (a chart library for burndown and velocity), with the buttons
   underneath for keyboard users. The baseline stays HTMX; this is the earned upgrade, not a framework.
3. **Worklogs: yes.** A line on an issue where someone logs hours; no timesheets, no approvals of hours.
4. **Issue types: fixed** — story, task, bug, subtask.
5. **Default application: each person's or their admin's choice.** Projects is not forced on anyone's landing.
6. **A Scrum Master agent is hired on install**, not merely proposed — as the Installer is (`bin/hire_scrum_master.php`
   on the kernel, run by the installer step K4): the daily duty of §7, on the Claude harness, in the department that
   owns the installation's first project (the Front Office until one exists), with the expert proposed beside it.
   Its name in `maludb-os.json` `agents[]` is `scrum_master`; the plan's "Scrum desk" is that agent.

**The plan is approved (2026-09-28).** Next: K1 and K2 in the kernel, then the repository with this document as
`docs/projects-design.md` and Phase 1 as the checkpoint.
