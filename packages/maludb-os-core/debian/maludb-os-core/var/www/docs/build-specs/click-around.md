# Click-around — every name a link, every page a way back

Status: **step 0 BUILT 2026-09-27** (the kit — `web/lib/routes.ts`, `web/lib/here.ts`, `BackLink`, `Who`,
`PageHeader back=`, the `/ai` route — proven on spend-by-agent → agent → run → back → back; R1–R6 in the slice
template). **Step 1 BUILT 2026-09-27** (every link the JSON already allowed, 31 files; the watch page now
names the alert, the set and the agent as three links; the activity trail's route map is `recordHref`; a
filtered trail says whose it is and offers "Show everything"). **Step 2 BUILT 2026-09-27** (every id a presenter
had dropped, added ADDITIVELY — PHP is live before React deploys, so a key is added and never renamed or reshaped,
and every new zod field defaults to null; the "Granted by" raw-id bug fixed; an eval run's page gained its facts
line; a review form gained Cancel and a crumb to its member). **Step 3 BUILT 2026-09-27** (db/151: `mcp_agents.model_id`,
the escalation recipient's name and kind, `mcp_team_directory.department_ids`, the access scope's own target; `mcp_run_verdicts`
already had `member_id` — presenter and query only; `CardSection` takes an `href` so a group heading is a link). **Step 4 BUILT
2026-09-27** (the prompt log takes `acting`, `model`, `provider`, `department`, `application` and `month=YYYY-MM` and names each in
its header with a clear link; a spend row's and a statement line's call count opens those calls; the watch and traces pages have an
agent and an eval-set control, the watch's agent filter reaching schedules too; the approvals pills keep the status; an application
offers its calls. No `config_version` filter: the ledger has no such column). **Step 5 BUILT 2026-09-27** (`afterSave()` in
`routes.ts`: an edit opened from a record's page returns to that page — tab and trail kept — and a create opened from a list lands
on the new record with the list as its back; `useRecordForm(path, back)`; every form page reads `?back=`, every form's Cancel and
`PageHeader back=` honour it, every Edit/New link carries the page; PHP: the department save lands on the department, a review on
the agent's Performance tab, the business settings save keeps `?saved=1` so its banner shows). **Steps 6 and 7 BUILT
2026-09-27** (6: the run page's "what it did" rows and an approval's "About" go through `recordHref` — the activity trail, the
audit subjects, the call page and the escalations had gone through it in steps 1–2; record labels on activity rows stay an
owner's option. 7: every crumb but the last links; the Settings hub lists Business settings, Models, Prompt library, Approval
policies and Navigation; `PageHeader` takes `home=` and the launcher's Home is `/launcher`; the catch-all and `ModuleStub`
keep their single crumb, which is the last). **All seven steps built; the owner owes the web deploy and the five answers.**
Found on the way, not this work's: `/team/<id>` and `/team/departments/<id>` have the stacked-card inner
scroll (`verify.sh` INNER-SCROLL) on the live build too. The owner's words: "when
I'm on the /ai/spend pages and listing spend by agents I should be able to click on an agent name and
go to /agents/ for that agent and have a back button that brings me back to the prior page. This is a
problem in many places throughout the application."

## What the survey found (2026-09-27, all 67 shell screens read)

Three failures, everywhere at once:

1. **Names are text.** A record that has its own page is named on some other page as plain text about
   120 times: the agent on a spend row, the department on an agents card, the manager on a department
   card, the approver on an approval, the actor on an activity row, the policy that caught a request.
   In roughly half of those the id is already in the JSON — the page just never made a link. In the
   other half the presenter whitelisted the name and dropped the id it stood beside.
2. **There is no way back.** The only "up" is the breadcrumb, and 41 of 67 screens have a crumb with
   no link (the "AI Ops" crumb fourteen times — there is no `/ai` page to go to). A crumb that does
   link goes to the bare list: whatever period, filter, tab or page the person left is gone. Nothing
   remembers where the person came from — an agent opened from spend-by-agent goes back to `/agents`.
3. **Forms land in the wrong place.** Saving a department lands on the departments list, not the
   department (`html/team/departments/save.php` pushes `/team/departments`); a review of an agent lands
   on its Job tab, not Performance; Cancel on an edit form goes to the list on departments, locations
   and applications; the review form has no Cancel at all.

And a few things the survey turned up that are bugs, not gaps: the application Access tab's "Granted
by" column prints the raw member id (`app/features/applications/present.php:230`); the activity trail
still links `organization`, `contact` and `deal` to pages the kernel cut removed; the team list links an
agent's name to `/team/<id>` instead of `/agents/<id>`.

## The rules (added to `docs/build-specs/react-slice-template.md` in step 0)

- **R1 — a name is a link.** Wherever a screen shows the name of a record that has a page, it is a
  `Link` to that page. A presenter that emits a name emits the id beside it (and, for a member, the
  kind). New presenters use the `who` shape `{ id, name, kind }` for members; `{ id, name }` for
  everything else. No exceptions for cards, facts, badges, table cells or sentences.
- **R2 — one route map.** `web/lib/routes.ts` is the only place that knows where a kind of record lives:
  `recordHref(kind, id)` (every `entity_type` that `log_activity()` is called with), `memberHref({id,
  kind})` (agent → `/agents/`, otherwise `/team/`). Activity rows, audit subjects, run "what it did"
  rows, approvals' entities and escalations all go through it.
- **R3 — every crumb links except the last.** A crumb's parent is a real page. "AI Ops" gets one
  (`/ai`, see step 0). Where a screen sits under a hub the hub lists it (Settings lists Business, Models,
  Prompts, Approval policies, Navigation).
- **R4 — a detail page knows where it came from.** A link that leaves a list, a table, a card grid or
  another record's page carries `?back=<path+query of the page it left>`. The detail page shows
  "← Back to <label>" in its header, returning to exactly that URL (period, filters, tab and page kept).
  With no `back`, the header shows the parent crumb's target instead, so a shared or bookmarked URL
  still has a way up. `back` chains: an agent page reached from spend, then a run opened from that
  agent, goes back to the agent page *with its own back*, and from there to spend. Only a relative path
  starting with a single `/` is honoured; anything else is ignored.
- **R5 — forms land on the record.** Save lands on the saved record's page (with the tab it belongs
  to); Cancel on an edit goes to the record, on a create to the list; both honour `back`. A record that
  was deleted lands on its list.
- **R6 — an aggregate row opens its detail.** A row that sums calls, spend or runs by something
  (spend by agent, a statement line, an eval set's runs) links to the list of the things it sums,
  filtered to it — which means the target list accepts that filter as a query parameter.

## How it is built

**`web/lib/routes.ts`** — `recordHref`, `memberHref`, and `withBack(href, here)` which appends
`back=<here>` (URL-encoded; `here` is the request's own path and query, which the middleware already
stamps as `x-pathname`, `web/middleware.ts:69`). A server page reads `here` once:
`const here = (await headers()).get("x-pathname")`. `Link` itself stays as it is.

**`components/kit/BackLink.tsx`** (client) — reads `useSearchParams().get("back")`, validates it (R4),
and renders `<i class="feather-arrow-left"> Back to <label>`. The label comes from a small table of the
app's list pages in `routes.ts` (`/ai/spend` → "AI spend", `/agents` → "Agents", `/approvals` →
"Approvals", …) keyed on the path without its query, falling back to "Back". `PageHeader` gains a
`back?: { href, label }` prop (the fallback, R4) and renders `BackLink` above the title in
`.page-header-left`; on a phone that line is what the person sees first. The design system's page
header markup is kept; the line is an addition inside it.

**`components/kit/Who.tsx`** — `<Who who={…} />` renders a member's name as the right link
(`memberHref`) or, when the id is null, as text. Every "for {acting.name}", "approver {name}",
"manager {name}" becomes one.

**`RecordCard`** — `href` already accepts any string, so `withBack` is applied by the caller; `facts`
already take React nodes, so a fact becomes a `Link` with no kit change.

**Tabs** — the agent page's tabs and the application page's tabs are already URL-addressed (`?tab=`); a
`back` on a tabbed page is the tab URL, so returning lands on the tab. Tab links keep `back` (the
agent page's tab `Link`s at `agents/[id]/page.tsx:113` rebuild the query with both).

**Forms** — `useRecordForm` follows PHP's `HX-Push-Url`. Where a handler pushes the wrong place (the
department save; the review save without `?tab=performance`) the PHP handler changes. `back` on a form
page is passed to Cancel and, after save, appended to PHP's location by `submitToPlatform` when the
form page carried one (`web/lib/actions.ts:53`, a two-line change) — so edit → save returns to the
record *with* the trail intact.

**Presenters** — an id is a whitelist addition in `present.php` plus the zod field; a view or query
change is listed separately below because it is a migration or a query edit, not a whitelist.

## The steps

Each step is one commit in the repo's style; each ships whole (web + presenter + schema) for the
screens it names. Order is by value to the owner, then by cost.

### Step 0 — the kit, proven on the owner's example
`routes.ts` (`recordHref` with every entity kind from the table under step 6, `memberHref`, `withBack`,
the list-label table), `BackLink`, `Who`, `PageHeader.back`, the `/ai` route
(`web/app/(app)/(shell)/ai/page.tsx` → a redirect to `/ai/spend`; a real AI Ops index page is the
owner's call, see open questions), R1–R6 written into the slice template. Then the example end to end:
`/ai/spend?group_by=agent` — each row links to the agent (or the person: `find_ai_spend()` adds the
key's member kind, `present_ai_spend_row` passes `kind`; the model grouping links to
`/settings/models/<key>/edit`, the department grouping to `/team/departments/<key>`; provider and day
have no page) — the agent page shows "Back to AI spend" and returns to the same period and grouping.
*Proof:* the click path in the browser at 375px and desktop; a run page opened from that agent's
Performance tab goes back to the agent, then to spend.

### Step 1 — links the JSON already allows (web only)
The id is in the schema today; the page renders text. One commit, every screen:
- **AI Ops:** statement lines (model, department, agent, application); evals list (agent, department);
  eval set page (department; a case's "from real work" badge → the call or run); alert page (eval set);
  watch (the alert's set and agent); audit (alert cards → the alert; `ledger` subjects → the call);
  prompt log and call page (acting person; request id → the log filtered to it); run page → "all calls
  of this run" (`/ai/prompt-log?run=`); versions (system prompt).
- **Agents/team/estate:** agent page (manager, eval-runs' set name, "for {acting}"); departments list
  and page (manager, reports-to, works-at); location page (owner, office manager, residents, departments,
  applications); member edit (department names); skills (department reach; a proposal's run); approvals
  page ("Behind this request: run #N"; approver); team list (an agent's name → `/agents/`).
- **Applications/settings:** application page (owner department, accountable person, the Overview tab's
  location, department scopes, endpoint names, expertise skills → `/skills`); approval-policies list
  (the policy name → its edit page; applies-to; approver); Agent View department chips.
- **Dashboard:** the agent and team cards are one stretched link each; inner links (department, model,
  last run) need `position: relative; z-index: 1` over the stretched link — done here for the ids
  already present, the rest in step 2.

### Step 2 — ids the presenters dropped (whitelist + schema)
The row already carries the column; the presenter left it out. Per presenter, with the target link
(step 1 confirmed each of these is missing from the zod schema; it also found `present_nav_item` lacks
`application_id` and the approvals `who` on the agent page's Performance list lacks the approver's id):
- `present_ledger_call` (aiops): `model_id`, `application_id`.
- `present_ops_run` (aiops): `model_id`, `requested_by` (+ kind), `acting_member_id`, `application_id`;
  the children rows in `html/ai/runs/view.php` get `agent_member_id`.
- `present_eval_run`: `agent_member_id`, `config_version_id`, `model_id`, `baseline_run_id` ("regressed"
  links to the baseline), `started_by`.
- `present_eval_schedule`: `agent_member_id`, `last_eval_run_id`. `present_eval_alert`: `schedule_id`,
  `acknowledged_by`. `present_ai_period_month`: `closed_by`.
- Inline presenters: `html/ai/traces.php` (`agent_member_id`, set name), `html/ai/audit/index.php`
  (alerts: `eval_set_id`, `agent_member_id`; grades: `agent_member_id`; decisions: `agent_run_id`),
  `html/ai/system/index.php` (decisions: `subject_kind`, `subject_id`).
- `present_agent_row`: `manager_member_id`; `present_agent`: departments as `{id,name}` (via
  `member_departments()`), manager kind; `present_agent_version`: `model_id`, `gating_eval_run_id`;
  `present_agent_tool_grant`: `application_id`; `present_agent_approval_request`: `approver_member_id`.
- `present_approval_request`: `policy_id` (→ the policy's edit page). `present_escalation`:
  `approval_request_id`, `entity_type`/`entity_id`.
- `present_location_row`: `parent_location_id`, `owner_member_id`. `present_pending_invitation` (+ the
  query selects `invited_by`). `present_skill_assignment` / `present_skill_proposal`: `assigned_by`,
  `decided_by`. `present_memory_result`: the department id parsed from `dept:<id>`.
- `present_application_card`: `sme_agent_member_id`, `owner_department_id`.
  `present_application_access`: `member_id`, `member_kind`, `department_id`, `resident_location_id`, and a
  **`granted_by` name** (join `members`) — fixes the raw-id bug at line 230. The withdrawn-holdings
  banner in `html/applications/view.php` gets the grantee id.
- `present_activity_row`: `actor_member_id` (already selected by `find_activity()`).
- `present_home_agent` / `home_agents()`: `department_id` (the lateral already reads
  `mcp_department_members`), `agent_run_id` for the "last run" line; the inline team presenter in
  `html/index.php`: department ids. `present_system_prompt_version`: `created_by`.
  `present_nav_item`: `application_id`. `reviewFormData`: the member's `kind`.
- `RunVerdict`: `member_id` (needs `mcp_run_verdicts` to expose it — that one is step 3).

### Step 3 — what needs a view or a query (one additive migration — landed as db/151, since db/150 was taken)
Step 2 confirmed these still need the view: the dashboard team cards' and the team list's department ids
(`mcp_team_directory` names only), the agents list's department section id (`find_agents()` lateral),
`RunVerdict`'s member id (`mcp_run_verdicts`), the Access tab's scope target (`mcp_application_access.scope_id`
is the `application_scopes` row, not the location or department), and the audit page's `eval_schedule` /
`eval_result` subjects (no parent id recorded). Already done in step 2 by a query join, so NOT needed here:
the agent's manager kind and home location name, the approver's kind, a run's requester kind, an eval run's
names, a version's model name, the grantor's name.
- `mcp_agents`: add `model_id` and the manager's `member_kind` (agents list, agent page, dashboard
  card, Agent View model link).
- `mcp_agent_escalations`: join the recipient — `to_member_name`, `to_member_kind` (today the screen
  prints "member #N").
- `mcp_team_directory`: a `department_ids` array beside `departments` (team list, dashboard team card).
- `mcp_run_verdicts`: `member_id`. `mcp_agents`: `home_location_name` (the agent page says "View
  location" with no name).
- Query only, no view: `approvals/queries.php` selects the approver's `member_kind` (three places);
  `find_agents()` selects `dm.department_id`; `find_ai_spend()` the key's kind (step 0);
  `skills/queries.php` the two member ids; the team page's inline applications presenter emits
  `department_id` / `resident_location_id` for "Through".
Views keep `WITH (security_barrier = true)`, new columns appended last, grants checked after.

### Step 4 — targets that need a filter (R6)
- `/ai/prompt-log` (`find_ledger_calls`): `acting` (a person's own calls), `model`, `provider`,
  `department`, `application`, `month=YYYY-MM` (a statement line's month) and `config_version`. The
  page shows the active filter in its title with a "clear" link, as it does for `run` today. Then: spend
  rows (every grouping but day → its filtered log; day → `from`/`to` if the owner wants it), statement
  lines, a version's "its calls", the run page's "all calls", an application page's calls.
- `/ai/evals/watch` and `/ai/evals/traces`: an agent select (both already accept `?agent=`, neither
  shows a control), an `eval_set` filter; the watch agent filter applied to schedules too.
- `/approvals`: the role pills keep `status`.
- `/activity`: a visible "about this record" chip when `entity_type`/`entity_id` filter it, with a link
  back to the record (`recordHref`) — the application page's "history" link relies on this.

### Step 5 — forms land right (R5)
- `html/team/departments/save.php` pushes `/team/departments/<id>`; `DepartmentForm` Cancel → the
  department on edit. `LocationForm`, `ApplicationForm` Cancel → the record on edit.
- `html/team/reviews/save.php` pushes `/agents/<id>?tab=performance` for an agent; `ReviewForm` gets a
  Cancel and a crumb to the member (needs `kind`, step 2).
- Model save and policy save may keep landing on their lists (they are short lists; the owner decides).
- `back` through forms: `submitToPlatform` appends the form page's `back` to PHP's location;
  `AgentForm`, `DepartmentForm`, `LocationForm`, `ApplicationForm`, `EndpointForm`, `EvalSetForm`,
  `EvalCaseForm`, `ModelForm`, `PromptForm`, `PolicyForm`, `NavItemForm` pass it to Cancel.
- `BusinessForm`: confirm whether the "Saved" banner ever shows (the save redirect drops `?saved=1`);
  fix if not.

### Step 6 — the activity trail, and every "kind #id"
`recordUrl()` in `activity/page.tsx` becomes `recordHref` from `routes.ts`, with the dead CRM kinds
removed and these added: `application`, `application_endpoint`, `location`, `approval_request`,
`approval_policy`, `model`, `system_prompt`, `eval_set`, `eval_run`, `eval_alert`, `eval_case`,
`agent_run`, `prompt_ledger`, `agent`, `member`, `department`, `nav_item`, `skill_proposal`, `skill`,
`skill_assignment`, `business_settings`, `business_hours`. The same map drives the run page's "what it
did" rows, the call page's activity rows, the audit page's decision subjects (`eval_schedule` → its
set, `eval_result` → its run need the parent id in the inline presenter), the approval page's entity
and the escalations' entity. The actor becomes a `Who`. A record *label* on activity rows (the name,
not "application #39") needs a join per kind and is left as an owner's option.

### Step 7 — crumbs and hubs (R3), the sweep
Every plain crumb gets its href: "AI Ops" → `/ai`, "HR" → `/agents`, "Work Locations" → `/locations`,
"Departments" under People, "Settings" on Business/Models/Prompts/Navigation, the set's crumb on the
eval-set edit form, the record's crumb on every edit form, the `[...slug]` catch-all and `ModuleStub`.
The Settings hub lists the five settings screens. The Agent View's launcher header stops pointing
"Home" at the OS dashboard for a person on the app face (it points at `/launcher`).

## Proof

- Step 0 in the browser (both widths) on the owner's path; every later step with a per-screen click
  through of what it changed, and `npm run build` clean.
- A grep gate for R1, run before each commit: no `{x.name}` / `_name}` rendered in a shell page where the
  same row has an `id` field and `routes.ts` knows the kind. Written as `web/scripts/check-links.mjs`
  once, kept as a pre-commit habit like the smokes.
- A grep gate for R3: no `{ label: "…" }` crumb without `href` except the last of each list.
- No PHP write path changes except the two save handlers in step 5, so no new smoke; the handlers'
  existing smokes (`mcp/smoke/…departments…`, reviews) still pass.

## The owner's five answers (2026-09-27) — all BUILT the same day

1. **`/ai` is a real index page**: `html/ai/index.php` + `web/app/(app)/(shell)/ai/page.tsx` — one card a section (Spend this
   month with its providers, calls today, the month's statement, evals with the last run, open alerts, graded traces, Audit and
   System for admins, models) each linking in; "Overview" is the first tab of `AiOpsNav`.
2. **The logo stays on the Agent View** (`/`). No change.
3. **Activity rows show the record's name**: `app_record_label(kind, id)` (db/152) names a kernel record by kind — members,
   departments, locations, applications, endpoints, approval requests and policies, models, prompts, eval sets and cases, nav
   items, tokens, skill proposals; a kind with no table keeps "kind #id". `find_activity()` selects it, the row shows the name with
   the kind muted beside it.
4. **Model and policy saves land on the record** (`html/settings/models/save.php`, `html/settings/approval-policies/save.php`
   push the edit page); a status change still returns to the list.
5. **Spend by day links to the day's calls**: the prompt log takes `day=YYYY-MM-DD` (one UTC day, as the spend page counts it)
   and names it in its header; the day row's call count opens it.

## Size

Step 0 one session; steps 1–2 one session together (many files, each a line or two); step 3 half a
session including the migration; steps 4–7 one session together. About four commits, no new tables.
