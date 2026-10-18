> **2026-09-22:** the kernel cut (`db/133`, build plan phase 7 A1) removed every business module this plan converted. What stays in React is the kernel: home, estate, departments, the directory, Agent HR, applications, approvals, AI Ops, skills, memory, settings. The rest of this document is the record of what was built and how. Design: `docs/business-os-integration.md`.

# Business OS — React migration plan

2026-09-18 · status: **approved by the owner 2026-09-18** · supersedes the "Apache/PHP/Bootstrap/HTMX"
front-end statement in the requirements and build plan once approved

## Why

The AI Agent View (`agentview/`, Next.js 15 + React 19 + three.js) cannot be built in HTMX, and
running two unrelated front-end stacks side by side is not an architecture. The front end moves to
**one Next.js application**; the Agent View becomes part of it.

## Decisions taken (owner, 2026-09-18)

| Decision | Chosen |
| --- | --- |
| Backend | **PHP stays, as a JSON API.** Auth, CSRF, authorization, approvals, `log_activity()`, mail and the query functions are kept. Only the HTML templates and HTMX responses are replaced |
| Cut-over | **Freeze and convert everything**, then switch in one release. No mixed-UI period. Feature work on build-plan phases 3–6 pauses until the switch |
| Look and feel | **Traditional — keep the Bootstrap 5.3 nxl admin look** for day-to-day work. The Agent View aesthetic is for visualisation and demos only |
| Agent View | **It is the home screen**, and an **Agent View button** on selected screens opens a contextual visualisation of what that screen is about |

## What does not change

PostgreSQL schema and migrations · RLS, `app_can_see()` and the `mcp_*` views (visibility stays in
SQL, so no rule is re-implemented) · the three roles · the three MCP servers, the assistant
service and the activity-ingest timer · the action manifest's meaning · MaluDB · `log_activity()`
on every state change · the PHP handlers as the **single write path for people and agents alike**
(the actions MCP server POSTs to them today and keeps doing so).

## Target architecture

```
browser ──► Apache :443 ──► Next.js (maludb-os-web, :3000)      every screen, the Agent View
                 │                 │  server components + server actions
                 │                 ▼
                 │          PHP on 127.0.0.1:8080 (internal vhost) ──► PostgreSQL
                 │                 ▲
                 │          actions MCP server (unchanged write path)
                 └──► still public on Apache: /mcp/* proxies, /api/v1/* (bearer tokens only),
                      /voice/* webhooks, /assets/*, OIDC callback
```

1. **One Next.js app at `web/`** — `git mv agentview web`, keeping its history and its working
   server-side API client (`lib/org-graph.ts`). Two route groups with separate root layouts so
   the styles can never leak into each other:
   - `(app)` — Bootstrap nxl shell: sidebar from the module catalog, header, notifications,
     command bar. Every day-to-day screen lives here.
   - `(agentview)` — the dark full-screen visualisation: `/` (home) and `/view/...`.
2. **The browser never talks to PHP.** This is already agentview's rule and it becomes the
   platform's: server components read, **server actions** write, both through one client
   (`web/lib/api.ts`) that forwards the `CSTSID` cookie to PHP on localhost. No CORS, no token in
   JavaScript, and the session API path stays safe because it is server-to-server.
3. **PHP becomes internal.** At cut-over the PHP vhost binds to `127.0.0.1:8080`; Apache's public
   vhost proxies everything to Next.js except the short public list above. Handlers keep their
   file paths, so `mcp/actions_server.py` changes one constant (`APP_BASE`).
4. **URLs keep their shape, minus `.php` and query-string ids:**
   `/contacts/organizations/view.php?organization=5` → `/contacts/organizations/5`. The action
   registry's `navigate` targets are regenerated from the manifest; every old URL that can sit in
   an email or a bookmark (`reset.php`, invitation links, `login.php`) gets a permanent redirect.

## The PHP side: handlers become dual-mode, then JSON-only

The controllers are already clean — gate → query → `view()` — so the conversion is mechanical and
is done **once in `app/http.php`**, not 365 times:

- `wants_json()` — true for `Accept: application/json`. While the freeze lasts, every endpoint
  answers **both**: HTML for the existing UI (which stays live and usable until the switch), JSON
  for React. After cut-over the HTML branch, `app/views/`, `render_screen()` and htmx are deleted.
- Response helpers replace the five HTMX patterns: `respond_screen($payload)`,
  `respond_saved(['id' => …, 'location' => …])`, `respond_invalid($errors)` (422, field-keyed),
  and JSON forms of `deny()` (403), not-found (404), sign-in-required (401) and
  approval-paused (202 + the approval request). Error shape is the existing `api_error()` one.
- **Write handlers need no edit at all (found 2026-09-18).** 154 of the 210 POST handlers —
  every business write — already report their outcome through `emit_action_status()`, because
  the actions MCP server needed it. JSON mode buffers the handler's output and
  `json_mode_finish()` answers from what it *reported*: success → `{ok, did, location}` (location
  read from the `HX-Push-Url`/`HX-Location` the handler set — so a create returns the new
  record's URL), failure → 422 with the handler's error list, a 4xx `exit('plain words')` → that
  status with those words, an approval pause → 202 `pending_approval`, a 5xx → generic words,
  and HTML with a 200 → 501 `not_converted`. **A JSON caller can never receive HTML.** Only
  *reads* need a branch (`respond_screen()`), because only reads have data to whitelist. The ~56
  handlers that do not report (auth, settings/2FA, tokens, notifications, receipts, bank import)
  are converted by hand.
- **Presenters, never raw rows.** Each feature gets `app/features/<f>/present.php` with explicit
  whitelist functions (`present_organization($row)`). Templates chose what to show; JSON must too.
  Dumping `view()` data would over-disclose (member rows, masked project names from `db/080`).
  This is the migration's main security rule.
- CSRF: `verify_csrf()` additionally accepts the session token in an `X-CSRF-Token` header. The
  Next server gets it from `GET /api/v1/session`, which also carries the shell payload (member,
  role flags, nav modules, business name, unread count).
- Auth endpoints (password, TOTP, lockout, Google OIDC, register/invite, forgot/reset) get JSON
  mode. The one delicate piece: the login server action must **relay PHP's `Set-Cookie`**
  (including the regenerated session id) to the browser. Built and tested first.
- `log_screen_view()` fires only when the request carries `X-Screen-View: 1`, which the Next
  client sends on a real render and never on a prefetch — activity memory cannot be un-polluted.

## The React side: a kit, so screens are assembly

- **Theme:** the same `bootstrap.min.css`, `theme.min.css`, `app-overrides.css`, served from
  `/assets`. The theme's jQuery scripts (`vendors.min.js`, `common-init`, DataTables, select2) are
  **not** carried over; `react-bootstrap` supplies dropdown/collapse/offcanvas/toast behaviour on
  the same CSS. Design-system rules carry over verbatim: **no modals, full-page create/edit,
  works at 375px.**
- **Kit** (`web/components/kit/`): `PageHeader`, `DataTable` (URL-driven search, filters, sort,
  pagination via `searchParams` — replaces `hx-get` + `hx-push-url`), `Form` + fields with
  server-action submission and field-keyed errors (`useActionState`), `ConfirmInline` (replaces
  `hx-confirm`, no modal), `Tabs` as routes, `EmptyState`, `Money`, `Timestamp` (mirrors
  `money()` / `format_ts()`), `Link` wrapper with `prefetch={false}`, `AgentViewButton`.
- **Contract:** each endpoint's payload has a zod schema in `web/lib/schemas/<feature>.ts`,
  parsed at the boundary in dev and test, so PHP/TypeScript drift fails loudly instead of
  rendering `undefined`.
- **Command bar:** rebuilt as a client component in the shell; same assistant endpoint, and
  navigation results become `router.push()` + `router.refresh()`.
- **Files:** uploads and downloads stream through Next route handlers to PHP.

## Agent View integration

- `/` is the Agent View: the organisation from where the signed-in person sits (today's
  `org-graph`). A plain **Dashboard** link is always one click away at `/dashboard`.
- `GET /api/v1/graph?focus=<kind>:<id>` generalises `org-graph` to the same node/edge shape for
  other subjects, read from `mcp_*` views only. `AgentViewButton` on a screen opens
  `/view/<kind>/<id>` as a full page (not a modal). First set: department, agent (orchestrator
  roster, applications, tools), project (members, tasks, agents), location/estate, organization
  (people, deals). Every node's profile panel links back to its traditional screen.
- Going live (nodes pulsing on real agent runs via SSE from the prompt ledger) is **out of scope
  for the migration** and returns as a build-plan item in phase 5.

## Order of work

| Step | What | Gate |
| --- | --- | --- |
| **R0 Baseline** | Commit the in-flight projects/tasks slice; tag `pre-react`; record these decisions in CLAUDE.md, the build plan (2 copies) and the requirements (3 copies); freeze: no new PHP screens | — |
| **R1 API foundation** | `wants_json()`, response helpers, presenter convention, header CSRF, `/api/v1/session`, JSON auth endpoints with cookie relay, internal vhost on :8080 (alongside the public one for now) | login → session → logout proven from a Next server action |
| **R2 Web foundation** | `agentview` → `web`; route groups; Bootstrap shell; `lib/api.ts`; the kit; auth screens; command bar; Playwright smoke + 375px harness; `maludb-os-web` unit | shell demo on the staging host name |
| **R3 Exemplar** | **Contacts/CRM end to end in React + JSON**, parity-checked against the PHP screens; then `docs/build-specs/react-slice-template.md` and the conversion recipe are written from it | **Owner approves the exemplar — nothing fans out before this** (same discipline as M1) |
| **R4 Fan-out** | Worker-model conversions from per-module specs, one lane (git worktree) per module, review gate per wave. **A — shell-adjacent:** settings, team & access, members, notifications, activity, feed, my-work, tags/comments, approvals. **B — work & sales:** deals, sales/quotes/invoices/payments, projects, tasks. **C — money:** books, expenses. **D — agents & estate:** agent HR (the largest), applications, locations, org chart, dashboard, AI ops. The 11 one-file module stubs become one placeholder route | per wave: parity checklist, every manifest action still succeeds through the actions MCP, activity rows identical in kind |
| **R5 Agent View** | Home route, `/api/v1/graph`, `AgentViewButton`, profile-panel deep links. Independent lane — runs in parallel with R4 | demo |
| **R6 Cut-over** | Apache flip (PHP internal-only), legacy-URL redirects, action registry regenerated, full manifest smoke through the assistant, then delete `app/views/`, HTML branches, htmx and the jQuery vendor bundle; tenant provisioning script gains Node + the web unit; docs synced; htmx-php-builder skill references in CLAUDE.md replaced | owner sign-off, tag `react-cutover` |
| **R7 Resume** | Build-plan phases 3–6 continue on the new slice template (spec → PHP JSON handlers + presenters + zod schema + React screens + manifest + MCP tools) | — |

Rough weight, from the code as it stands (49k lines of PHP: 19k templates to rewrite, 14.5k of
controllers to make dual-mode, 14k of queries untouched): R1+R2 are the careful part, R3 sets the
pattern, R4 is ~85% of the volume and is mechanical by design.

## Risks and how each is held

| Risk | Held by |
| --- | --- |
| JSON over-discloses what templates hid | Presenters only; review gate checks every payload against its zod schema; `mcp_*` views remain the only read source for API-native endpoints |
| A handler loses its gate, CSRF or logging in conversion | Handlers are edited, not rewritten — gate/CSRF/`log_activity()` lines are untouched; per-wave diff review confirms it |
| Prefetch or double render inflates activity memory | `X-Screen-View` header + `prefetch={false}` |
| Agents' write path breaks | Handler paths unchanged; manifest smoke per wave, not just at the end |
| Worker-model drift across ~130 screens | Exemplar + slice template + kit; ambiguity stops the slice and escalates (existing rule) |
| Session cookie relay / OIDC redirect subtleties | Built first in R1 with its own test, before any screen exists |
| Long freeze with nothing shipping | R5 runs in parallel; the old UI stays fully usable until R6 |

## Questions settled 2026-09-18 (the owner confirmed all three defaults)

1. **Cert-study legacy screens** (`study`, `exams`, `attempts`, `study-log`, `organizer`, and the
   unconverted `plans`/`events`/`issues`/`resources`): **not ported.** They retire at
   cut-over; their tables stay. Phase 3 already replaces them with projects, tasks and time.
   This removes roughly 60 endpoints from R4.
2. **Staging host name** for the new app during the freeze: keep using
   `agentview.subello.com`, renamed at cut-over.
3. **Which screens get the Agent View button first:** the five listed above.

## Decided during the migration

- **`tax_id` was erased on every company edit — fixed 2026-09-19, owner chose option B.**
  `mcp_organizations` does not expose `tax_id` (the `mcp_*` views are what agents read, and tax
  ids stay away from them), so the edit form showed it blank and `update_organization()` wrote
  the blank back. Now the edit form — and only the form — reads that one column from the base
  table through `find_organization_tax_id()`, which joins the view so it can return a value only
  for a company the member may already see. **This is the one sanctioned base-table read in the
  Contacts feature**; the view, the detail screen, the list and every MCP tool are unchanged.
  The fix is in PHP, so the legacy form is fixed too; the React form has its Tax id field back.
  No data had been lost (no company had a tax id yet).

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — editing a deal clears its probability override** (found 2026-09-19, same class as
  `tax_id`). `mcp_deals` exposes the *effective* `probability`, not `probability_override`, so
  the edit form shows the field blank and `update_deal()` writes the blank back: any edit resets
  a hand-set probability to the stage's default. In the HTMX UI today; the React form keeps
  parity. Not a disclosure question this time — the fix is either to add `probability_override`
  to the view (a migration) or to read it for the form as `tax_id` is read. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — saving a form clears a link its editor cannot see** (found 2026-09-19 converting
  Projects & Tasks; same class as `tax_id`, but the hidden thing is a *related record*, not a
  column). Three instances, all in the HTMX UI today, all kept at parity in React:
  1. **Task → project.** `mcp_tasks` admits a task's assignee or creator who cannot open its
     project (db/080 masks the name). The task form's Project select holds only projects the
     editor can open, so it reads "No project", and `tasks/save.php` writes `project_id = NULL`
     (and `milestone_id = NULL`): **an assignee who fixes a typo in their own task detaches it
     from its project.** Reproducible as Sam Okafor on task 10 — not exercised, a save is a real
     activity row.
  2. **Task → customer** and 3. **Project → customer / deal**: the same, for an editor whose
     contacts visibility does not reach the company or deal (a projects-grant holder with no
     contacts grant).
  The fix is a write-path decision — e.g. "a link the editor cannot see is left as it was unless
  they pick a visible replacement" in `save.php`, which the migration rules forbid touching —
  so it is not made here. The presenters deliberately do **not** send the hidden id to make the
  form round-trip it: that would put a masked project's id in the browser. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — a file cannot reach PHP from a React form** (found 2026-09-19 converting Agent HR).
  `web/lib/api.ts` `apiPost()` forwards a form as `application/x-www-form-urlencoded` and keeps
  only string values, so a `File` in the `FormData` is dropped without a word. The agent hire /
  edit form uploads `profile_photo` (multipart, ≤ 2 MB, `agent_photo_from_request()`). The slice
  template puts `api.ts` and `actions.ts` out of a slice's reach, and carrying a file is more
  than one line: `apiPost()` must switch to multipart when a `File` is present, and Next.js caps
  a server action's body at 1 MB by default (`serverActions.bodySizeLimit` in `next.config`),
  below the 2 MB PHP accepts. **Until decided, the React form shows the Picture field disabled
  with a line saying so** — never a silent drop; "Remove this picture" works (it is a string),
  an existing picture is kept by `config-save.php` when no file arrives, and the HTMX form still
  uploads. Expenses (receipts) and Documents will need the same path. **Owner's call:** extend
  `api.ts` + raise the body limit to a named size, or give uploads their own route handler.
  **The same question in the other direction (found converting Expenses):** the accountant
  export is a file PHP streams (`expenses/exports/download.php` — it also stamps
  `last_downloaded_at` and writes an `accountant_export.download` activity row). The browser
  never talks to PHP, so it needs a relay like `/api/avatar`; but that relay forwards only the
  cookie, and a download is *logged* — without `X-Web-Key` + `X-Forwarded-For` the activity row
  would carry 127.0.0.1 instead of the visitor's address, and the helper that builds those
  headers (`baseHeaders()`) is private to `api.ts`. Until decided, **Download is shown disabled**
  on the React exports screen (creating an export works); the HTMX screen still downloads.

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — editing a draft quote or invoice clears its project link** (found 2026-09-19
  converting Sales; the `tax_id` class, inverted: the view shows the column, the *form* does not
  carry it). `document_fields_from_request()` reads `project_id` from the request and
  `update_invoice()` / `update_quote()` write it, but `sales/document-form.php` has no project
  field — so any edit of a draft writes `project_id = NULL`, and the `/invoices/new?project=N`
  prefill that `invoices/form.php` computes never reaches `save.php` either. In the HTMX UI
  today; React keeps parity (a hidden `project_id` input would be a silent fix). The fix is a
  Project select on the form, or a hidden input carrying the current value. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — saving a posting rule clears its note** (found 2026-09-19 converting Books; the same
  class again). `posting-rules/save.php` reads `note` from the request and
  `upsert_posting_rule()` writes it, but the rules table has no note input — and shows no note —
  so saving any row writes `note = NULL`. `mcp_gl_posting_rules` exposes the column. In the HTMX
  UI today; React keeps parity and the presenter does not send the note. **Owner's call:** a
  Note column on the row, or stop writing it from this screen.

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — what a posting run skipped, and why, does not reach React** (found converting
  Books). `post-documents.php` re-renders the Books home with every skipped document and its
  reason ("a silent skip is how an invoice goes missing from the books"), but reports only
  counts through `emit_action_status()` (`did: "Posted 3 document(s), skipped 1"`), and
  `ActionState` carries only that sentence. The React home shows the sentence — not nothing —
  but not the reasons. Carrying them needs `skipped` added to the handler's
  `emit_action_status()` call (a write-handler edit) and a data field on `ActionState`
  (`web/lib/actions.ts`) — both outside a slice's reach. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — editing a model clears its endpoint URL** (found 2026-09-19 converting Settings; the
  `tax_id` case exactly: a form edits a column its read view hides). `mcp_model_registry` does
  not expose `endpoint_url`, so the model form shows it blank on every edit, and
  `upsert_model()` writes the blank back — a local / OpenAI-compatible model loses its endpoint
  the first time anyone changes its price. In the HTMX UI today; React keeps parity and the
  presenter does not send the column. The fix is the view (a migration) or a one-column read
  for the form, as `find_organization_tax_id()` does. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — the personal Settings screen (`/settings`) cannot move yet** (found converting
  Settings; this is the slice template's "a handler that does not report — stop and record it").
  Eight of its nine write handlers never call `emit_action_status()`, so in JSON mode they
  answer **501**: `settings/notifications.php`, `settings/2fa/enroll.php`, `2fa/enable.php`,
  `2fa/disable.php`, `settings/tokens/create.php`, `tokens/revoke.php`,
  `settings/calendar-feed/create.php`, `calendar-feed/revoke.php` (only `profile.php` reports).
  And four of them hand back a **one-time secret that exists only in the HTML they echo** — a
  new API token's raw value, the TOTP secret and its QR image, the recovery codes, the calendar
  feed URL. Making them report is a write-handler edit; *how a one-time secret reaches React*
  (it must not pass through `did`, which is logged and shown as a toast-like sentence) is a
  design decision. Until then `/settings` shows the "has not moved yet" card and the HTMX
  screen stays the way in. **Owner's call.**

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — register / forgot / reset cannot move without editing three auth handlers**
  (2026-09-19; the run that converted the six modules stopped here, as instructed). Each is ONE
  file holding both the form (GET) and the write (POST), and none has a JSON path: every
  outcome re-renders HTML with a 200, which the adapter answers as **501 `not_converted`**.
  Verified with requests that write nothing — `GET /register.php`, `POST /forgot.php` for an
  address that cannot exist (no member → no token, no mail, no activity row), `POST /reset.php`
  with a token that cannot exist: 501 each. `login.php` and `login/2fa.php` moved in R1 because
  they were **edited** to answer `json_error()` / `respond_saved()` explicitly; these three
  need the same treatment, and they are the most security-sensitive handlers in the app —
  forgot's single generic sentence is its enumeration defence and must survive as the ONE JSON
  answer for both outcomes; register resolves an invitation token, establishes a session, and
  its "already registered" message is itself an enumeration surface; Google sign-in is an OAuth
  redirect through the PHP host. The run's rule was "PHP: reads only — do not edit write
  handlers", so nothing was built: a React form over a 501 is a dead form.
  **Owner's call:** authorise the edit of `register.php`, `forgot.php`, `reset.php` (and say
  whether Google sign-in is offered from React), and the three screens follow `login`'s pattern.

- **DECIDED 2026-09-19 (see "Owner's decisions" below; not yet built) — the command bar cannot move without editing `assistant/message.php`** (2026-09-19,
  same run, same rule). The bar has one endpoint and it is a write handler: POST + CSRF, logs
  `assistant.message`, mints an action token, calls the assistant service. It never calls
  `emit_action_status()`; its reply is an HTML bubble, and navigation / refresh travel as
  `HX-Location` / `HX-Trigger` headers — so in JSON mode the adapter answers 501 (a body plus a
  location is neither of its success shapes), and the answer text exists nowhere but the HTML.
  The React bar needs `{answer, navigate, triggers}` as JSON from that handler, and a carrier
  for it on the web side: `ActionState` holds one sentence, and `submitToPlatform` either
  follows a location or stays — it cannot show an answer AND navigate (`web/lib/actions.ts` is
  out of a slice's reach too). Not exercised even once: a message is a real model call, a
  ledger row and an activity row. The pieces the bar will reuse are already in every converted
  screen — `data-screen` / `data-entity` / `data-record-id` on `.main-content`, and
  `router.refresh()` is what every `HX-Trigger` refresh becomes. **Owner's call:** authorise
  the JSON answer in `assistant/message.php` and a small dedicated server action for the bar.

### Owner's decisions, 2026-09-19 (all ten open items — asked one at a time, answered by the owner)

Each of these **authorises the named edit and nothing wider**: gates, `verify_csrf()` and
`log_activity()` lines stay untouched, handler file paths do not move, and every other write
handler keeps the "needs no edit" rule. None is built yet.

1. **Auth screens — edit the three handlers, no Google yet.** `register.php`, `forgot.php` and
   `reset.php` get explicit JSON answers on `login.php`'s pattern. `forgot` keeps ONE generic
   sentence for both outcomes (its enumeration defence). Google sign-in stays on the PHP pages
   until cut-over.
2. **Command bar — JSON answer + its own action.** `assistant/message.php` answers
   `{answer, navigate, triggers}` in JSON mode; the bar gets one small dedicated server action
   in `web/`; `web/lib/actions.ts` stays as it is. `navigate` → a router push, each trigger →
   `router.refresh()`.
3. **Personal Settings — the secret travels in the JSON body, once.** The eight handlers report
   status; the four secret-bearing ones return the secret in a dedicated field (never in `did`,
   which is logged), `Cache-Control: no-store`. A dedicated server action hands it to the page,
   which shows it once and keeps it only in component state — never a URL, cookie or storage.
4. **Files — extend `api.ts` both ways.** `apiPost()` goes multipart when the `FormData` holds a
   `File`; `serverActions.bodySizeLimit` is raised to a named size (proposed 5 MB);
   `baseHeaders()` is exported so ONE allow-listed `/api/download` route streams logged files
   with the visitor's real address. This unblocks the agent photo, the accountant export, and
   `books/banks/import` (whose read and write share a file, so it gets a JSON path too).
5. **Deal probability override — a form-only read, like `tax_id`.** A
   `find_deal_probability_override()` that joins `mcp_deals` feeds the edit form and nothing
   else. No migration; the view and the MCP tools are unchanged.
6. **Hidden links — keep a hidden link unless it is replaced.** In `tasks/save.php` and
   `projects/save.php`: when the record's current project / customer / deal is one the editor
   cannot see and the form sends blank, the existing value is kept; a visible replacement still
   works. The masked id never reaches the browser. Accepted cost: only someone who can see the
   link can clear it.
7. **Draft documents — add a Project select** to the quote / invoice form (visible projects only,
   "No project" allowed), prefilled from `?project=` and from the saved value; rule 6 applies to
   a project the editor cannot see.
8. **Posting rules — add a Note column to the row.** No write-path change; the handler already
   accepts it.
9. **Posting run — add `skipped` to the handler's report.** `post-documents.php` adds the
   skipped list (source, id, reason) to its `emit_action_status()` data, and the Books home gets
   a small dedicated server action that returns it, so the page shows PHP's own result panel.
   The actions MCP and the assistant gain the reasons too.
10. **Model endpoint URL — a form-only read, like `tax_id`.** A `find_model_endpoint_url()` that
    joins `mcp_model_registry` feeds the super-admin model form and nothing else. No migration;
    agents never read internal endpoint addresses.

## State (done-notes, newest last)

- [x] **R0 baseline — decisions recorded 2026-09-18.** CLAUDE.md, the build plan (2 copies) and the
  requirements (3 copies) carry the stack change and the freeze. The in-flight HTMX work
  (projects & tasks, the dashboard reshape) was committed as it stood and tagged `pre-react`.
- [x] **R1 API foundation — PHP side done 2026-09-18.** `app/http.php`: `wants_json()`,
  `json_response()`/`json_error()`, `respond_screen|saved|invalid|not_found()`, and JSON forms of
  `require_post()` (405), `verify_csrf()` (403 `csrf_failed`), `require_login()` (401), `deny()`
  (403), `redirect()` (`{ok, location}`) and uncaught exceptions (500, no text). An endpoint with
  no JSON branch yet answers **501 `not_converted`** from `render_screen()` instead of HTML with a
  200 — so R4's remaining work is countable. `GET /api/v1/session` (session-only, no CORS, not
  activity-logged) carries the CSRF token and the shell payload from a whitelist. Login and 2FA
  answer JSON. `log_screen_view()` honours `X-Screen-View` in JSON mode.
  **Found on the way:** with Next.js calling from localhost every visitor's `REMOTE_ADDR` is
  `127.0.0.1`, which would pool the per-IP login lockout and blank the activity log's ip.
  `client_ip()` believes `X-Forwarded-For` only from loopback **and** only with the shared
  `WEB_INTERNAL_KEY` (`config/.env` + `web/.env.local`); verified that a forged header without
  the key is ignored. Port 3000 must stay reachable only through the fronting proxy, since Next
  passes on the `X-Forwarded-For` it is given.
- [x] **R2 started 2026-09-18.** `agentview/` → `web/` (history kept), unit renamed
  `maludb-os-web`. Route groups: `(agentview)` keeps the dark root layout; `(app)` is the
  Bootstrap nxl root layout with `html/assets` served at `/assets` (symlink in `web/public`).
  `web/lib/api.ts` is the platform client: cookie forwarding, CSRF pre-fetch, `ApiError`, and
  **session-cookie relay**. `/login` and `/login/2fa` are live with server actions. Verified
  through the Next server: refused login renders PHP's message, the pre-login `CSTSID` is relayed
  to the browser, the visitor's address reaches `login_attempts`. **A successful sign-in was
  confirmed by the owner in the browser (2026-09-18)**; logout waits for the shell's button.
- [x] **R2 shell — 2026-09-18.** `components/shell/Shell.tsx` is `app/views/layout.php` in React:
  same nxl markup and ids, sidebar from `session.nav`, active item by longest path match, user
  menu with Settings and **Logout** (a server action → `POST /logout.php`). The theme's jQuery is
  not loaded; its three behaviours are reimplemented on the same classes and the same
  localStorage keys, so a preference set in the legacy UI carries over — mini sidebar
  (`minimenu`), mobile drawer (`mob-navigation-active` + overlay), dark mode (`app-skin-dark`).
  `middleware.ts` sends a cookie-less visitor to `/login?next=…`; the shell layout does the same
  for a cookie PHP rejects. The header carries an **Agent View** button (home). A catch-all
  route answers every unconverted path with "has not moved to the new front end yet" inside the
  shell — never a 404 for a module that exists; converted routes take precedence and the
  catch-all is deleted at cut-over. Kit so far: `Link` (prefetch off), `PageHeader` (mobile
  action toggles included). `react-bootstrap` added for dropdown/offcanvas/toast behaviour.
  Verified by request: no cookie → 307 to login with `next`; rejected cookie → same; signed in
  (seed dept-admin, throwaway fixture) → shell, 27 nav items, Contacts active, zero `hx-`
  attributes. How it looks and behaves (desktop and phone width, the three toggles, the
  user menu, logout) was checked by the owner in the browser the same day: all good.
  *Next in R2:* the rest of the kit (`DataTable`, `Form` + fields, `ConfirmInline`, `Tabs`,
  `EmptyState`, `Money`, `Timestamp`), the command bar, register/forgot/reset, Playwright + 375px
  harness. Then R3, the Contacts/CRM exemplar.
- [x] **R3 Contacts/CRM exemplar — built, and APPROVED BY THE OWNER 2026-09-19** (the gate on worker-model fan-out is open; see the last note in this section for what that leaves).
  - [x] *List (2026-09-18).* `app/features/contacts/present.php` starts the presenter
    convention; `html/contacts/index.php` gained a `wants_json()` branch and nothing else.
    `web/lib/screen.tsx` `renderScreen(path, schema, render)` is the one place a page's failure
    modes live (401 → login with `next`, 404, 403 shown with PHP's own message, 501 "not
    converted", schema mismatch throws); `web/lib/schemas/contacts.ts` is the zod contract.
    List state is the URL (`?q=&kind=&type=&owner=&tag=&page=`) via `useQueryState`; kit gained
    `SearchInput` (400 ms, as HTMX had it), `FilterSelect`, `Pagination`, `Refused`. Same ids as
    the PHP screen. Verified: JSON as super-admin (3 records), rendered page as the seed
    dept-admin with filters applied.
  - [x] *The JSON-mode adapter (2026-09-18)* — see "Write handlers need no edit at all" above.
    Verified with requests refused before anything is written (0 activity rows): 501 for an
    unconverted screen, 400s and a 404 carrying the handler's own words, a 422 with both
    validation messages from `organizations/save.php`; HTMX mode still re-renders the form.
  - [x] *Company view, form, and every company write (2026-09-18).* PHP: `respond_screen()`
    branches in `organizations/view.php` and `form.php`; presenters for the company, its people,
    deal summaries (`deals/present.php` — `money()` stays the one formatter, its display string
    travels with the amount), interactions, tags and notes (`records/present.php`). **No write
    handler was touched** — save, archive, merge, delete, tag add/remove and note add/delete all
    answer through the adapter. Web: `lib/actions.ts` `submitToPlatform` is the ONE server action
    behind every form (path allow-listed to PHP handlers, 422 → field errors, 202 → the approval
    notice, `follow` → PHP's `location`); kit gained `ActionForm` (the `hx-post` counterpart, with
    the browser confirm that `hx-confirm` was), `useRecordForm` (submits by hand so a refused
    form keeps what was typed — React resets a form after its action), `FormFields`
    (`FieldRow`, `IconInput`, `OwnerSelect`, `DepartmentSelect`), `SubmitButton`, `Nl2br`; shared
    record components `Tags`, `Conversations`, `Notes` for every later slice. The refresh after an
    in-place write is marked quiet for 3 s so it is not logged as a screen view (HTMX logged
    nothing there either). Verified with 0 activity rows written: detail (people, deals with
    `48,000.00 USD`, primary badge, tag, conversation time in the viewer's zone, admin actions),
    edit (values, checked types), new (command-bar prefills), a missing id → 404, and a refused
    in-place write through the server action returning PHP's own words.
    **Not yet exercised: a write that succeeds** — left for the owner's browser, since every
    successful write is a real activity row under a real name.
  - [x] *Fixed 2026-09-19 — the page could not reach its own bottom (owner's report: "no
    scrollbars, could not post a note").* Four stacked cards in one column each carried the
    theme's `stretch stretch-full` ("be as tall as the whole row"), so each was row-height and
    the excess scrolled **inside** `.main-content` (which the theme makes a scroll container via
    `overflow-x:hidden`) instead of growing the page. **Rule for every slice: `stretch
    stretch-full` only on a column's ONLY card; stacked cards are plain `.card`.** The legacy
    PHP partials carry the same classes. Also: the sidebar list could not scroll without the
    theme's jQuery scrollbar plugin — `app-overrides.css` now gives `.navbar-content`
    `overflow-y:auto`. Found by reproducing in a real browser: **Playwright + headless Chromium
    are installed** (`web/scripts/probe-scroll.mjs`, `probe-wheel.mjs`, `probe-heights.mjs`,
    `shot.mjs` — all take a session id and send the quiet cookie so a probe is never logged as
    a screen view). Verified at 1280 and 375: the wheel scrolls the document, the note field is
    reachable, screenshots read correctly.
  - Known issue: with JavaScript **disabled**, posting an `ActionForm` hangs (Next.js forwards a
    shared server action between its own workers and never answers). The JS path — what every
    browser does — answers in 0.2 s. The HTMX UI needed JavaScript too, so this is no
    regression, but it should be retested after the next Next.js upgrade.
  - [x] *Person view, form and writes (2026-09-19).* Same pattern, no write handler touched
    (save, archive, merge, delete, make-primary). What the company and person screens share was
    extracted for later slices: `records/DealsCard`, `contacts/Relationship` (badges + checkbox
    row), `kit/FormFields.AddressFields`. Checked in headless Chromium at 1280 and 375 —
    detail, new-with-prefills (`?organization=&name=`), edit scrolls to its end — 0 activity rows.
  - [x] *Interactions, hygiene, and the slice template (2026-09-19).* The conversation form
    (`/interactions/new`, `/interactions/{id}/edit`, prefilled from `?organization=&contact=&deal=`)
    and the hygiene screen (merge straight from the duplicates table). `web/scripts/deploy.sh`
    and `web/scripts/verify.sh` make "done" mechanical: every route, 1280 and 375, in a real
    browser — status, title, not refused, not the placeholder, no horizontal scroll, no inner
    scroll (the stacked-card defect), no `hx-`, no console errors. All 8 Contacts routes pass.
    **`docs/build-specs/react-slice-template.md`** is written from the exemplar.
    **The Contacts/CRM exemplar is complete and awaits the owner's approval** before anything
    fans out to worker models. On the owner's instruction (2026-09-19: "do as many of the HTMX
    refactors as possible while I'm gone") the planning-class session continues through the
    remaining modules itself, in plan order.
- [x] **R4 · Deals (2026-09-19).** The pipeline board (`/deals`, filters in the URL, a card moves
  by changing its stage select — `AutoSubmitSelect` in an `ActionForm`, as the HTMX card did),
  the deal detail (move, won, lost-with-reason, delete, tags, conversations, notes) and the
  add/edit form. The form's two dependent selects (main contact by company, stage by pipeline)
  no longer round-trip: the payload carries every option and the form filters — recorded in the
  slice template. Stage totals per currency are summed in the presenter, where `money()` lives.
  Kit: `AutoSubmitSelect`, `FilterCheckbox`; `formatDate()`. No write handler touched. All 6
  routes pass `verify.sh` at 1280 and 375. `/settings/pipelines` is linked and not yet converted.
- [x] **R4 · Overview group (2026-09-19): dashboard, activity, and the 14 module stubs.**
  `/dashboard` is PHP's `/` (here `/` is the Agent View): count tiles and one card per agent.
  The "what is this agent doing" decision moved from the template into
  `home_agent_activity()` in `home/present.php`, times formatted in the viewer's zone there, so
  both front ends read identically. The grid re-reads once a minute (`AutoRefresh`, which marks
  itself quiet first — a poll is not a screen view, and HTMX's fragment poll logged nothing).
  Agent photos are PHP-served behind the session, so they come through `/api/avatar`; **that
  relay accepted any platform path and now accepts only `/agents/photo.php?agent=N` and image
  files under `/assets/`** — it would otherwise hand the browser any PHP page. `/activity`: the
  trail with its five filters in the URL and the pager capped at 20 as before; before/after
  payloads are deliberately not presented. **Module stubs**: `render_module_stub()` answers JSON
  once, and the catch-all renders all 14 designed-but-unbuilt modules from it (`STUB_PATHS`) —
  distinct from the migration's own "not converted yet" card. All routes pass `verify.sh`.
- [x] **R4 · Team & Access (2026-09-19).** People list (search + three filters in the URL), a
  member's identity / departments / module access, the **access editor** (role, per-department
  admin flag, add/remove department, read/write/revoke per module — every control its own
  `ActionForm`, no Save, "Done" leaves), departments list, a department with its members, and the
  department form. The defaults `department-form.php` worked out inline (reports to the Front
  Office; a new department starts at an onsite office — db/074) are computed in the JSON branch
  and arrive as `selected_parent_id` / `selected_location_id`. Presenters read only the
  `mcp_team_directory` family — never `members`. `lib/nav.ts` gained `NAV_OWNER`, the React form
  of PHP's `activeNav`: People & access lights up HR, conversations light up Contacts. 8 routes
  pass `verify.sh`; a plain user gets PHP's own refusal ("This needs an administrator.").
  *Not converted:* `team/reviews/form.php` (agent reviews — goes with Agent HR).
- [x] **R4 · Work Locations (2026-09-19).** The list (kind / online / show-retired filters; Add
  and Edit only with the `locations` grant, so nobody is walked into a refusal by a button), a
  location's page (move to a building, retire, delete, office manager, residents, departments
  that call it home, applications that run there, its history link into `/activity`), and the
  form. Kind decides Siting / parent / Owner as one block, by the schema's rules; the HTMX form
  re-fetched that block from `parent-options-fragment.php`, here Kind is state and both parent
  lists arrive with the page. The specs panel is built in the presenter as label/value rows so
  "Not recorded" (NULL) can never read as "No" in one front end and not the other. What the
  template asked inline — `is_super_admin()`, "is this the desk's owner" — travels as
  `can.retire` / `can.delete`; delete blockers are named on the disabled button. The PHP
  location page stretches every stacked card (the company-page defect); here they are plain
  `.card`. `PageHeader` gained `icon`; `FilterCheckbox` gained `valueOn`. 7 routes pass
  `verify.sh` across a building, an office and a desk. *Noticed, left as is:* the "Office" kind
  badge uses `bg-soft-brand text-brand`, which the theme does not define, so it is near-invisible
  in both front ends.
- [x] **R4 · Applications (2026-09-19).** The registry list (category / department / location /
  health / gaps-only in the URL; monthly cost from the linked recurring expense), an application
  with its four tabs — **tabs are the card header and each tab is a URL (`?tab=`)**, as in PHP;
  all four tabs' data travels in one payload — Overview (health, "Check now"), Endpoints (add /
  edit / remove; a credential is only ever `has_credential`), Access (grant to a member or a
  department, revoke; the scope note when the viewer sees only their own grants) and Cost
  (Expenses holds the cost, this only reads it), plus the application form and the endpoint form.
  Member and department options for granting are sent only to someone who may manage access.
  10 routes pass `verify.sh`. *Not converted:* the standalone `applications/access.php` screen —
  the Access tab is the same table; if the manifest navigates to it, it becomes a redirect to
  `?tab=access` at cut-over.
- [x] **R4 · Projects & Tasks (2026-09-19).** Projects: the list (search, status / customer /
  department in the URL; "any status" is `?status=any` here because PHP's blank status cannot
  live in a URL the filter kit cleans), a project with its four tabs — Overview (facts, budget,
  "What is in the way"), Tasks grouped by milestone with Complete in the row, Team (add /
  remove), Milestones (done / reopen / edit / delete) — all four in one payload, each tab a URL
  as in Applications; the project form and the milestone form. Tasks: the list (four chips, three
  selects, search), a task (status / assign / reschedule, checklist, dependencies, tags, notes)
  and the task form. Both forms' dependent selects (deal by customer, milestone by project)
  filter a payload that carries every option; `find_deal_options()` and `find_milestones()` are
  per-parent and `queries.php` is frozen, so the JSON branch runs **one query per visible
  customer / project** — fine at this size, worth an `…_all()` query when queries thaw.
  **Masking (db/080):** `present_task_project()` is the one place a task's project is presented —
  a masked project leaves as `{id: null, name: null}` (no name, **no id**, and the milestone id
  is dropped with it); a hidden customer's id is dropped the same way on projects and tasks; a
  blocker's or dependency's masked title stays NULL, and a blocker's blocking-task id is never
  sent. Read as Sam Okafor (assignee of task 10 on "HR Handbook Rewrite", which he cannot open):
  every JSON payload and every rendered page including the serialized props — the project's
  name, code and `/projects/7` appear nowhere; `/projects/7` is a 404 and its edit a refusal.
  Overdue is decided in PHP (`overdue`), status vocabularies live in
  `components/{projects,tasks}/Badges.tsx`. Rate and budget now read through `money()`
  ("45,000.00 USD" where the template printed "45000.00 USD") — slice-template rule 3. `/tasks`
  lights up My work (`NAV_OWNER`). The stacked cards on both detail pages are plain `.card`
  (the PHP templates stretch them). No write handler touched — all 20 already report through
  `emit_action_status()`. 16 routes pass `verify.sh` as the super-admin and 8 as Sam, 1280 and
  375, 0 activity rows. *Not converted:* `deals-fragment.php`, `milestones-fragment.php` (die
  with HTMX). See the new OPEN item above: saving a task can detach it from a hidden project.
- [x] **R4 · Agent HR, with reviews (2026-09-19).** The agents list (status / department in the
  URL, avatars through `/api/avatar`), an agent with its six tabs in one payload — Job (current
  version, activation and its eval-gate sentence), Tools (grant / revoke), Duties (Run now),
  Roster or Orchestrators (none for a voice agent, db/091), Performance (the phase-5 carve-out
  stated, not zeros — since 2026-09-27 the agent's calls, spend, runs and evals from the AI Ops
  views, on the page itself), Trail — plus Identity, Manager and the Danger zone; the hire / edit form;
  escalations (agent + open-only filters, resolve in the row); config history; and
  `team/reviews/new`, which Team & Access had left for this slice. Presenters pass on what
  `mcp_agents` / `mcp_agent_config_versions` return, so a plain insider's payload simply has
  less (read as Sam Okafor: no email, no version, no grants, empty pickers, `can.edit` false;
  the hire form is PHP's refusal). Deliberately never presented: an endpoint's url, photo
  hash / mime / size, a version's `tool_grants` / `schedule` snapshots, review metrics, who
  created or activated what; the config history gets versions **without** their prompt text,
  and the full parameter map goes to the mod:hr form only — every other screen gets the
  one-line summary the template printed. Labels PHP owned (kind, HR event, escalation reason)
  travel as `*_label`; timestamps the templates printed raw now read in the viewer's zone.
  **The template nested the change-kind form inside the agent form**, which HTML forbids (and
  React reports): here that form is an empty sibling and its select and button point at it with
  `form=`, so they sit where they sat and post on their own. No hidden-column edit found: every
  field the form edits is in the view it reads. **Picture upload is disabled on the React
  form** — see the OPEN item above. No write handler touched (all 16 report through
  `emit_action_status()`). 14 routes pass `verify.sh` as the super-admin, 4 as Sam, 1280 and
  375, 0 activity rows. *Noticed, left as is:* "Write a review" is offered to everyone and
  refuses most (parity); escalations print "member #N" for the recipient (parity).
- [x] **R4 · Sales: quotes, invoices, payments (2026-09-19).** Fourteen screens. Quotes and
  invoices: list (the invoice list keeps its per-currency footer), the document page — lines,
  totals, and for an invoice its payments, credit notes, tags and history — and the one shared
  form (`DocumentForm`, as PHP shares `document-form.php`); the credit-note form; payments list,
  a payment with apply / unapply, and Record a payment; receivables aging (`FilterDate` joins the
  kit), the revenue report, a customer statement with Send, and unbilled work. **Lines are
  edited in place on a draft**: HTMX posted a row with `hx-include="closest tr"` because a form
  cannot live in a `<tr>`; here each row's save and remove forms are empty siblings after the
  table and the row's controls point at them with `form=` — the pattern Agent HR's change-kind
  form introduced, now used twice. Every amount travels as `money()`'s string; the statement's
  running balance and the report's per-currency totals, which the templates computed inline,
  moved into the presenter so both front ends print the same figures. A document that is no
  longer a draft answers `{locked: "<PHP's sentence>"}` from its form endpoint (that path never
  logged a screen view, and still does not). Pickers for the line editor are sent only while
  the document is a draft. "Their contact" and "Apply to" filter a payload that carries every
  option; open invoices are one query per visible customer (`find_open_invoices_for()` is
  per-customer, `queries.php` frozen). `/quotes`, `/payments`, `/sales` light up Invoices.
  **Found:** the legacy invoice's **Credit button is a dead link** — no rewrite serves
  `/invoices/{id}/credit`; PHP answers at `/invoices/credit?id=`. The React route lives at the
  address the button always meant and reads the one that answers. And the OPEN item above: a
  draft edit clears the project link. No write handler touched (all 24 report through
  `emit_action_status()`). 20 routes pass `verify.sh` at 1280 and 375; a member without the
  sales grant gets PHP's refusal; 0 activity rows. *Not converted:* `contacts-fragment.php` ×2,
  `invoices-fragment.php` (die with HTMX); `invoices/add-unbilled.php` has no button on any
  screen (an action-manifest endpoint) and needs nothing.
- [x] **R4 · Expenses (2026-09-19).** Nine screens: the list (a member without the grant sees
  their own expenses only — PHP forces `mine`, and the status / category / vendor filters and
  their option lists are not sent), an expense (submit, resubmit, approve, reject-with-reason,
  mark paid, mark reimbursed, edit, delete, the phase-4 receipt stub, tags, notes, history), the
  expense form, bills due, the spend report, accountant exports, recurring costs and their form.
  Every rule `expense.php` worked out inline (own / admin / approver-of-this-department / status)
  now travels as seven booleans under `can`. The form's two Pattern A fragments became data:
  Vendor contact filters every visible contact by the chosen vendor, and each category carries
  its `billable_default`; its two inline `onchange` handlers became state (a due date moves
  Payment status to unpaid; Billable shows "Rebill to"). **Two submit buttons, one form**:
  `useRecordForm` reads the form without its submitter, so "Save as draft" / "Save" write a
  hidden `intent` input on click, before the submit event. The recurring table's Active / Paused
  toggle was an `hx-vals` button; it is a one-button form. A non-editable expense answers
  `{locked}` like a sent invoice. No hidden-column edit: `update_expense()` leaves project /
  task / campaign alone. **Download is disabled** — see the OPEN item on files. *Noticed, left
  as is:* the legacy exports table prints "0: 0" under Rows — it casts the `row_counts` JSON
  *string* to an array; the presenter decodes it, so React shows "expenses: 10". The vendor
  contact's label pointed at an id that did not exist (`…vendor_contact_id` vs
  `…vendor-contact`); the select keeps its id and the label now finds it. No write handler
  touched (all 12 report through `emit_action_status()`, `receipt.php` via
  `render_expense_page()`). 13 routes pass `verify.sh` at 1280 and 375; a member without the
  grant gets their own list, the form, and PHP's refusal on bills; 0 activity rows.
  *Not converted:* `category-defaults-fragment.php`, `vendor-contacts-fragment.php`.
- [x] **R4 · Books (2026-09-19).** Fourteen screens: the home (posted-through, waiting to post,
  periods, banks, Post documents), the chart of accounts with archive / restore, an account's
  activity, the account form; the journal, a journal entry with **lines edited in place on a
  draft** (the `form=` row pattern, third use) and its balance strip, post / void / reverse, the
  header form; bank accounts, a bank account with its transactions (to expense, ignore, unmatch)
  and reconciliations, the bank form, reconcile (start / complete); fiscal periods (close,
  reopen-with-reason, add); posting rules (a row is a form); and the three financial statements.
  **Every sum and every "does it balance" test `statement-table.php` did inline moved into the
  presenter with the template's own arithmetic and 0.005 tolerance** — trial-balance totals, net
  profit, the balance-sheet equation — so two front ends cannot disagree about whether the books
  balance; the entry's balance strip and a reconciliation's difference travel as `balanced`.
  Post and Complete are disabled by that flag, as in PHP. Two fragments became data: the journal
  form's "falls in {period}" badge is decided from the fiscal periods the payload carries
  (`period_for_date()`'s rule), and **"Find match" is a URL** (`?match={transaction}`) — HTMX
  fetched candidates from the GET half of `match.php`, a write handler's file, so the bank
  page's own read branch computes them for that one transaction (only if it is this account's
  and still unmatched). Account pickers are sent only while an entry is a draft. Several Books
  controllers log the screen view *before* assembling data; the branch sits after the data and
  before `render_screen()`. No write handler touched (all 21 report through
  `emit_action_status()`). 24 routes pass `verify.sh` at 1280 and 375; a member without the
  books grant gets PHP's refusal; 0 activity rows. **Not converted: `banks/import`** — the
  screen is a CSV upload (the OPEN item on files) and its read and write share one file
  (`import.php`), which the rules put out of reach; the bank page's Import button leads to the
  "not moved yet" card. Two more OPEN items above: posting-rule notes, and skip reasons.
- [x] **R4 · Settings, with pipelines (2026-09-19) — the admin screens; personal Settings is
  blocked.** Ten screens: business settings, pipelines & stages (linked from the Deals board
  since the Deals slice), catalog, tax rates, expense categories, the model registry and its
  form, the prompt library, a prompt with its immutable versions and "New version", and the
  new-prompt form. Five of them are inline-row tables that posted a row with
  `hx-include="closest tr"`; the `form=` pattern now has a small shared piece,
  `components/settings/RowForms.tsx` (the empty save / archive forms a table's rows point at) —
  its fourth to eighth use. `business_settings()` and the two `*_admin` catalog queries read
  base tables with `SELECT *`, so the presenter's whitelist is the only thing between those
  rows and the browser: the business's tax id, address, email, phone and website are not on the
  screen and are not sent. The prompt page's New-version prefill is sent only to someone with
  mod:hr. Business settings keeps its `hx-confirm` as a confirm before `useRecordForm` submits,
  and its "Saved." banner rides on `?saved=1` as in PHP. No write handler touched (the 14 used
  here all report through `emit_action_status()`). 12 routes pass `verify.sh` at 1280 and 375; a
  plain insider reads a prompt and is refused business settings in PHP's words; 0 activity
  rows. **Not converted: `/settings` itself** (profile, notifications, security, tokens,
  calendar) — see the OPEN item above; and one more OPEN item: a model's endpoint URL.
- [x] **R2 leftovers — auth screens and the command bar: were BLOCKED, awaiting the owner
  (2026-09-19); since unblocked by the owner's ten decisions and built — see the notes below.** Both need a write handler edited, which the converting run was told not to do;
  see the two OPEN items above. **Where R4 stands after that run:** converted — Contacts/CRM,
  Deals, Overview + stubs, Team & Access, Work Locations, Applications, Projects & Tasks, Agent
  HR (+ reviews), Sales, Expenses, Books, Settings (admin). Not converted, each with its reason
  recorded: `/settings` personal (handlers do not report; one-time secrets), `books/banks/import`
  and the agent photo (file upload), the accountant export download (file out, logged),
  `applications/access.php` (same table as the Access tab), the Pattern A fragments (die with
  HTMX), register / forgot / reset, the command bar. **The ten decisions were all taken on 2026-09-19** ("Owner's decisions", above) and none is built yet. They were, in
  "Decided during the migration": deal probability override; a save clearing a link its editor
  cannot see (tasks, projects); files in and out of PHP; a draft document's project link; a
  posting rule's note; a posting run's skip reasons; a model's endpoint URL; personal Settings;
  the auth screens; the command bar.
- [x] **Decision 4 built — files cross in both directions (2026-09-19).** `apiPost()` sends
  multipart when the `FormData` holds a non-empty `File` and stays urlencoded otherwise (an empty
  file input arrives as a nameless zero-byte `File`; that is "no file chosen" and PHP sees no
  upload). `next.config.mjs` raises `serverActions.bodySizeLimit` to **5 MB**; PHP's own
  `upload_max_filesize` (2 M) still applies after it. Instead of exporting `baseHeaders()`,
  `api.ts` gained a narrower `apiDownload(path)` — the headers that prove who is asking stay
  private to the one client — used by ONE route, `/api/download`, whose allow-list holds exactly
  `/expenses/exports/download.php?export=N`. Now live: the **agent photo** field, the
  **accountant export** Download link, and **`books/banks/import`** (its GET got a JSON branch;
  `import-preview.php`, a read-only POST, answers the first five rows as JSON; the React form
  previews through its own small action because nothing should re-read after a preview).
  **Proved without writing anything:** `web/scripts/probe-upload.mjs` uploads a CSV through the
  real browser → server action → `api.ts` → `import-preview.php` and gets the parsed rows back
  (and PHP's "Choose a CSV file first." with no file); the download route answers 400 for a
  path outside its list and 404 for an export that does not exist; 0 activity rows. **Not
  exercised:** a real import, a real photo save, a real download (each is a logged write).
- [x] **Decision 1 built — register / forgot / reset in React (2026-09-19). R2's auth screens
  are done.** The three handlers gained explicit JSON answers and nothing else: **40 lines
  added, none removed or changed** — `require_post()`, `verify_csrf()`, the invitation rule,
  `establish_session()`, `log_activity()` and every HTML path are as they were. `forgot.php`
  answers `{ok, notice}` with the SAME sentence whether or not the account exists (the action
  never branches on it). `reset.php`'s GET says only `{valid}`; a dead link keeps the form but
  empties the token, as the template did; POST answers 410 / 422 / `{ok, location}`.
  `register.php`'s GET prefills the invited address only for the holder of a live invitation
  token; POST answers 422 with PHP's error list, 409 for an address already registered, and on
  success the new session's cookie is relayed by `apiPost()` as login's is. Both token pages are
  `force-dynamic` with `referrer: no-referrer`. Google sign-up is not offered from React
  (the decision). **Proved with requests that write nothing** (`web/scripts/probe-auth.mjs`,
  real browser, signed out, 1280 and 375): forgot for an address that cannot exist → the
  sentence; register with no invitation → PHP's three errors, and the form keeps what was
  typed; reset and register with a dead token → PHP's words; a POST without CSRF → 403. Auth
  and invite activity rows before and after: 64 / 64; no reset token created. **Not
  exercised:** a real registration, a real reset mail, a real password change.
- [x] **Decision 2 built — the command bar is in the React shell (2026-09-19). R2 is complete.**
  `assistant/message.php` gained a JSON answer and nothing else (**14 lines added, none changed**):
  `{answer, navigate, triggers}` — only `navigate.path` travels, since `target` is an HTMX swap
  selector. `components/shell/AssistantBar.tsx` is `shared/assistant-bar.php` with the same ids
  (`assistant-bar`, `assistant-reply`, `assistant-form`, `assistant-input`, `assistant-send-btn`),
  Ctrl/⌘+K and "/" focus, and the reply bubble; it is mounted once in `Shell.tsx`, whose `<main>`
  gains `app-has-assistant-bar`. Its own server action (`shell/assistantAction.ts`) —
  `lib/actions.ts` untouched — maps PHP's canonical path (`/` → `/dashboard`, no trailing slash),
  pushes it, and turns any `triggers` into one quiet `router.refresh()`. Screen context is read
  at submit time from the page's `data-screen` / `data-entity` / `data-record-id`.
  **Gap, recorded:** PHP stamped a screen id on every screen through `render_screen()`; only 13
  of the ~105 React pages carry `data-screen` (those whose template had it on `.main-content`).
  The rest send their **path** as the screen, so the assistant still knows where the person is,
  but "this" / "that" resolve to a record only on the stamped pages. Stamping every page is a
  mechanical pass (each page's doc comment already names its screen id) — not done here.
  **Proved with the one path that writes nothing and calls no model:** an empty message, which
  PHP answers with its hint before it logs — real browser, 1280 and 375, Ctrl+K focuses, the
  bubble shows, no horizontal scroll, no console errors; `assistant.message` rows before / after:
  0 / 0. 11 routes re-verified with the bar mounted. **Not exercised:** a real message (a model
  call, a ledger row, an activity row) — navigation and refresh are yours to try in the browser.
- [x] **Decision 3 built — personal Settings is in React (2026-09-19).** `/settings` with its five
  sections (profile, notifications, security, AI access tokens, calendar feed); a section is a
  URL (`?section=`), as it was. **The eight handlers now report** through `emit_action_status()`
  — `did` is a sentence and never a secret — so the six non-secret writes (profile,
  notifications, 2FA disable, token revoke, feed revoke, and a refused 2FA code) work through
  the ordinary `ActionForm`. The revokes say what happened ("That token was not active —
  nothing changed") instead of claiming a revoke that matched nothing. **The four one-time
  secrets** — a new API token, the TOTP QR + key, the recovery codes, the feed URL — travel in
  their OWN field of the JSON answer (`token`, `qr_data_uri` / `manual_key`, `recovery_codes`,
  `feed_url`), `Cache-Control: no-store`, only when the caller asked for JSON; they are never in
  `did` and never in the `X-Action-Data` header action callers receive. On the web side
  `components/settings/secretActions.ts` (its own action, a closed list of four paths;
  `lib/actions.ts` untouched) hands the secret to the component that asked, which holds it in
  component state only. The read (`present_my_settings()`) names nine fields of the widest row
  in the database and never carries a token value. **Proved with the one secret path that
  writes nothing durable** (`web/scripts/probe-settings.mjs`): starting a 2FA enrollment keeps
  its pending secret in the PHP session only — no row, no activity — and the probe's session is
  thrown away. The QR and key arrive; the key is in no URL, cookie or storage; a wrong code is
  refused with PHP's words and the QR stays; leaving the page and returning shows no QR.
  2FA / token activity rows before and after: 27 / 27; member 1's 2FA still off. JSON answers
  also checked for a revoke that matches nothing, a disable when already off, and an enable
  with no enrollment (410). All five sections pass `verify.sh`. **Not exercised:** creating a
  token, rotating the feed URL, completing an enrollment, saving profile or preferences.
- [x] **Decisions 5 and 10 built — two form-only reads, on the `tax_id` precedent (2026-09-19).**
  `find_deal_probability_override()` (deals/queries.php) and `find_model_endpoint_url()`
  (agents/models.php) each read ONE column from the base table, joined to the `mcp_*` view so
  they answer only for a row the member may already see; their doc comments forbid more columns
  and any use outside the form. The form controllers add the value to the row, so **the legacy
  PHP forms are fixed too**, and to the FORM payload only — `present_deal()` and
  `present_model()`, which the board, the detail screen and the registry list share, do not
  carry it; neither view changed, no migration. Round-tripped inside a transaction that was
  **rolled back**: an override of 35 and an endpoint URL came back through the functions
  (`'35.00'`, the URL), a missing id gave NULL, and after the rollback both columns were NULL
  again. 6 routes pass `verify.sh`. There are now three sanctioned base-table reads in the app.
- [x] **Decisions 6, 7, 8 and 9 built — the four write-path and form fixes (2026-09-19).**
  **6 · hidden links.** One rule, `keep_hidden_link()` (records/queries.php): a blank keeps a
  link the editor cannot see, clears one they can (that is them choosing "none"), and any value
  they picked replaces it. Applied in `tasks/save.php` (project — the milestone stays with a
  kept project — and customer) and `projects/save.php` (customer, deal), after the existing
  "not one you can see" checks. The hidden id is read from the row the handler already loaded
  and never reaches the browser; the React task form says "This task belongs to a project you
  cannot open. It stays there unless you pick another project." Checked read-only as Sam:
  blank + hidden project 7 → kept; blank + visible project 6 → cleared; picks 6 → replaced;
  hidden customer → kept. His task-10 form still carries no trace of the project.
  **7 · draft documents.** The quote / invoice form has a **Project** select (visible projects;
  an archived one the draft already points at is still offered). `invoices/save.php` and
  `quotes/save.php`: a field that is **not sent at all** (the legacy form, a voice or agent
  caller) leaves the link as it is — which fixes the legacy form too; a sent id must be a
  project the member can see; a sent blank follows rule 6. `/invoices/new?project=N` now
  reaches the form. **8 · posting rules.** The row has a **Note** input and the presenter sends
  the note; no write-path change. (The legacy row still clears it until cut-over.)
  **9 · posting run.** `post-documents.php` reports `posted`, `skipped_count` and up to 25
  `skipped` entries (source, id, reason) through `emit_action_status()` — so the assistant and
  the actions MCP get the reasons too — and the React Books home shows PHP's own result panel
  through a small dedicated action (`books/postDocumentsAction.ts`). **Exercised only through
  refusals:** a blank task title as Sam, a draft invoice with no customer and a project id that
  does not exist ("That project is not one you can see."), a sent invoice, a converted quote, a
  blank project name, a posting period that is not a date — all 422, nothing written. 8 routes
  pass `verify.sh`. **Not exercised:** a successful save through any of the five handlers, or a
  posting run.
- [x] **The Ask page (2026-09-19) — the assistant's other door, on decision 2's pattern.** The
  shell's footer links to `/ask`, which was still the "has not moved yet" card. `ask/index.php`
  got a read branch and `ask/send.php` the same JSON answer as `assistant/message.php`
  (`{answer, navigate, triggers}`; 9 lines added, none changed). `components/ask/AskThread.tsx`
  is `ask/page.php` + `partials/exchange.php` with the same ids; it reuses the bar's server
  action with a `door` argument. The thread lives in the page, as the HTMX thread did. The copy
  is still the cert-study wording ("your exams, plans, the community") — left as PHP has it.
  Proved only by refusal (an empty message → 400 before anything is logged) and `verify.sh`.
  **Triage of what still has no JSON branch:** `members/` (the cert-study member directory —
  exams taken, certifications, study plans) and `calendar/index.php` (the exam / events calendar)
  are cert-study legacy and retire at cut-over with the rest; the business counterparts are
  People (`/team`) and the `schedule` stub. `notifications/read.php` and the tag / comment
  handlers are writes (the adapter serves them). `applications/access.php` becomes a redirect at
  cut-over. **With that, every business screen that exists in PHP exists in React.**
- [x] **R5 Agent View — the two parts that needed no new API were done first; the focused view
  waited for a spec approval (2026-09-19) and has since been built — see the last R5 note.** Done: the Agent View's disabled "Goto Human View" is a link
  to `/dashboard` in the live workspace (the plan's "a plain dashboard is always one click
  away"; the sample workspace keeps it disabled — nobody is signed in), and every node's profile
  panel links to its day-to-day screen — an agent to `/agents/{id}`, a person to `/team/{id}`, a
  department to `/team/departments/{id}`. Checked only in the sample workspace (renders, no
  errors): **loading the live Agent View writes an `api.org_graph.read` activity row under a
  real name, so it was not loaded** — the links are yours to click. **Not built:**
  `/api/v1/graph?focus=`, `/view/<kind>/<id>` and the `AgentViewButton`. That is a new API
  surface with product choices in it (what orbits a project, a company, a location), so it has
  a build spec instead of an improvisation: **`docs/build-specs/agent-view-focus-graph.md`
  (DRAFT)**. Its governing rule — a focused graph shows exactly what the record's own screen
  already shows that viewer, read with the functions that screen already calls — means no new
  visibility decision and no migration. **Its three questions were answered by the owner on
  2026-09-19, one at a time:** a project's rings are Team, Milestones and Blocked; an open is
  logged as ONE `screen.view` (quiet cookie honoured), not an API read; the endpoint is
  **session-only** for now. The spec reflects all three. It waits only for the owner's go.
- [x] **R6 Cut-over — DONE 2026-09-19 on the owner's "Fix and cut over" (see the last note); as first written:** not started, and not to be started without the owner's sign-off (the
  plan's own gate). It flips Apache so PHP is internal-only, deletes `app/views/` and the HTML
  branches, and retires the HTMX UI: none of that is reversible by a redeploy. Before it: a
  browser click-through of each module by the owner (no converted screen has had a successful
  write exercised), the manifest smoke through the assistant, and the legacy-URL redirects
  (`/reset.php?token=` and `/register.php?token=` links in already-sent mail must land on the
  React pages).
- [x] **The command bar's gap closed — every screen names itself (2026-09-19).** 71 more files
  now carry `data-screen` on `.main-content`, and `data-entity` + `data-record-id` wherever
  PHP's `render_screen()` options had them. Done by script, not by hand: each file's own doc
  comment already named its screen id ("Screen `invoice-view`", "screens `deal-add` /
  `deal-edit`"), a form's two ids switch on its `isEdit`, and the screen → entity map was read
  out of the PHP controllers. **Audited:** all 102 screen ids now stamped in React are ids PHP
  itself uses (`log_screen_view()` / `'screen' =>`) — none invented. Left unstamped on purpose:
  the catch-all, the module stub, the refusal card and the locked-document card (they send
  their path). Full regression sweep afterwards: **58 routes across every module pass
  `verify.sh` at 1280 and 375.**
- [x] **Owner's click-through, finding 1 — "changing an agent's photo fails" (2026-09-19): the
  save worked, the old face kept showing.** The upload reached PHP through the multipart path
  and was stored (row + file on disk, `200`); but a photo's address is the same before and
  after an upload (`/agents/photo.php?agent=N`), and both PHP and the `/api/avatar` relay let
  the browser keep its copy for five minutes — inside one React document the browser reuses it
  without asking at all. **Fix, reads only:** `present_agent_avatar()` sends the address as
  `…&v=<unix time of profile_photo_updated_at>` (a column `mcp_agents` already exposes;
  `photo.php` ignores it), so a new picture is a new address; the relay admits exactly that
  form, serves a versioned photo as immutable, and for an unversioned one (dashboard, Agent
  View) passes PHP's sha256 ETag both ways — `no-cache`, `304` when unchanged. Also closed: the
  relay followed a dead session's redirect and returned the login page as a `200` "picture";
  it now answers `401`. No write handler, gate or migration touched. The HTMX screens have the
  same five-minute staleness and are left as they are (frozen until cut-over).
- [x] **The owner's own logo, contained (2026-09-19).** The owner replaced
  `/assets/images/logo-full.png` (865 × 270). The theme sizes neither sidebar logo — it shipped
  with artwork already cut to fit — so the new one rendered at its natural size and the
  header's `overflow: hidden` cropped it to a few hexagons. `app-overrides.css` now contains
  any logo in the header's 220 × 50 content box (scaled down, never up, proportions kept:
  160 × 50 for this file), and drops the theme's `filter: invert(1)` on dark surfaces, which
  suited a black mark and turned this one's orange blue. One stylesheet serves both UIs
  (`web/public/assets` is a symlink to `html/assets`), so the HTMX header is fixed by the same
  rule. Measured inside the header at 375, 1280 (mini: the abbreviated mark) and 1700, light
  and dark. The file itself is left at full size — 30 KB, and it is what keeps the logo sharp
  on a high-density screen.
- [x] **R5 — the focused Agent View, built on the owner's go (2026-09-19).**
  `GET /api/v1/graph?focus=<kind>:<id>` (session-only), `/view/<kind>/<id>`, and an **Agent
  View** button on the department, agent, project, location and company screens. The rule the
  spec set did the work: every ring is a list the record's own screen already renders, read
  with the function that screen already calls, behind the gate that screen already applies —
  `app/features/orgchart/focus.php` holds no SQL and no visibility decision. Shown live:
  `/view/project/6` has Team (2), Milestones (2), Blocked (1) and every panel opens the right
  screen; Sam Okafor gets 404 on `/view/project/7` (hidden project), `/view/department/3` (not
  an admin) and `/view/organization/1` (no contacts reach), and no customer appears anywhere
  in his `/view/project/6`; signed out lands on `/login?next=…`. The 40-per-ring / 200-per-graph
  caps were exercised on synthetic nodes. `org-graph` and `/` are untouched (the web side
  adapts the payload to the shape `AgentView` already draws; focused views get their own
  weighted layout because a location's 25 applications do not fit an equal sector). An open
  logs ONE `screen.view` (screen `agent-view-focus`, entity = the record), quiet cookie
  honoured. 26 route checks pass `verify.sh` at 1280 and 375. Details: "As built" in
  `docs/build-specs/agent-view-focus-graph.md`.
  **A mistake to record:** the browser probe opened two members' profile panels, and the panel's
  detail fetch (`/api/v1/members`) logs — so activity rows 2222 and 2223
  (`api.members.read`, members 6 and 7, 2026-09-19 12:15 UTC, session `fv1789820102m1`) are
  the probe's, written under the owner's name. They were not deleted (the audit trail is not
  ours to edit). Rule for probes from now on: never open a member's panel in the live view.
- [x] **The owner approved the Contacts/CRM exemplar (2026-09-19) and said "begin".** What the
  approval unlocks is R4's worker-model fan-out — and there is nothing left to fan out: the
  planning-class session converted every module itself on 2026-09-19. A sweep confirms it: the
  only PHP screens with no JSON branch are the cert-study legacy ones that are not ported, plus
  `applications/access.php`, whose grant and revoke forms already live on the React application
  page. **So the next step is R6, and an exemplar approval is not a cut-over sign-off** — R6
  deletes `app/views/` and cannot be undone by a redeploy. Done instead, all additive:
  (1) `/reset.php`, `/register.php`, `/forgot.php` and `/login.php` redirect to the React pages
  with their query string (`web/next.config.mjs`; 307 until cut-over); (2)
  **`docs/react-cutover-runbook.md`** — order, checks and the way back. **Its finding: "PHP
  internal-only" cannot be a blanket flip.** `/api/v1/*` (bearer-token clients), the `/mcp/*`
  proxies, `/feed/calendar.php` (subscribed calendars), `/voice/retell-inbound.php` (the voice
  provider's webhook) and the Google OIDC start/callback pair are called from outside by things
  that are not browsers and must stay public. Also found: `APP_URL` is `http://localhost`, so
  reset and invitation mail already sent carries links nobody outside this machine can open.
  **OPEN — the owner's:** the go for the flip; Google sign-in (port it, or keep the PHP pair
  public); the soak length before the deletion; which records the manifest smoke may write to.
- [x] **The owner chose "finish testing first" (2026-09-19) — no flip; safe preparation only.**
  Two configuration faults found and fixed while preparing: **`APP_URL` was `http://localhost`**,
  so every absolute link PHP handed out was unopenable from outside — reset and invitation
  mail, the MCP URLs in Settings, calendar-feed URLs — now `https://subello.com`, which is the
  outside proxy in front of this Apache (mail sent earlier still carries dead links: those
  people need a fresh one); and **`LOGIN_URL` in `web/.env.local` sent a signed-out Agent View
  visitor to the legacy PHP sign-in on another host** — removed, so it is this app's `/login`.
  **A slip to record:** `sed -i` on `config/.env` recreated it with group `maludb`, so
  `www-data` could not read the app's configuration for a few seconds until the group was put
  back (`640 maludb:www-data`; the error log shows nothing from the window). Rule: never
  `sed -i` a file whose group matters — rewrite it in place, or restore owner and mode in the
  same command. Env backups live in `~/env-backups/`, outside the repo.
- [x] **The owner's three cut-over decisions (2026-09-19), and the first one built.** (a) **Port
  Google sign-in to the React login** — done: `web/app/auth/google/{start,callback}/route.ts`
  relay PHP's two handlers server-side through a new `apiAuthGet()` (a GET that relays the
  session cookie — the OAuth state lives in the pre-login session), both routes are on the
  middleware's public list, the login button points at `/auth/google/start`, and
  `/login?error=google` prints PHP's one sentence. One authorised handler edit:
  `html/auth/google/callback.php`'s failure closure answers JSON (`google_failed`, 401 / 429)
  after its unchanged `log_activity()`. Google is not configured on this server, so only the
  unconfigured path was exercised (both legs land on `/login`); when it is configured the
  redirect URI must be the React host's `/auth/google/callback`. (b) **No soak**: the PHP UI
  "was never completed or tested properly" and is deleted as soon as React is ready — ready
  being the owner's word once the click-through is done. (c) **The manifest smoke may write to
  anything.** Runbook updated; no decision is left open.
- [x] **The first writes ever exercised here — an action smoke through the actions MCP
  (2026-09-19, authorised: "smoke tests can write to anything").** `mcp/smoke_actions.py` +
  `mcp/smoke/*.json`; everything it made is named `SMOKE <run>` and addressed to
  `example.invalid`. **110 tool calls over 106 of the 163 built actions; 82 succeeded** — the
  whole CRM→cash chain, projects and tasks, the expense approval chain, the ledger (3 documents
  posted), settings lists, team, applications. A static audit alongside it: every one of the 176
  write handlers a React screen posts to reports its outcome, so a successful React write cannot
  show a false "not converted". **Defects found — all in the agents' door, all older than the
  migration, none touching a React screen:** ten `*_update` tools that can never succeed (the
  registry builder dropped "any field of x_create"), a new pipeline that can never get its
  first stage (`mcp_pipelines` inner join), four tools whose parameter names the handler does
  not read (bank account, location, review, prompt), creates that return no id.
  **`docs/action-smoke-2026-09-19.md`** has the table. **OPEN — the owner's:** whether to fix
  these before cut-over or after (they need a manifest + registry revision and one migration).
  **For the flip:** `actions_server.py` posts in HTMX mode; it must ask for JSON before the
  HTML branches are deleted (runbook updated).
- [x] **R6 — CUT OVER, 2026-09-19, on the owner's "Fix and cut over".** In order: safety net
  (tag `pre-cutover`, a verified dump, the Apache files aside); the agents' door fixed and moved
  to JSON mode (previous note's defects — `docs/action-smoke-2026-09-19.md`, "Fixed the same
  day"); the flip in two stages with no downtime (PHP to `127.0.0.1:8080`; the public port → the
  React app plus an allow-list: the token API, the MCP proxies, the calendar feed, the voice
  webhook); then the deletion — 249 templates, the unported cert-study screens, htmx / DataTables
  / select2, four legacy tools. **The trap avoided:** write handlers still render HTML after
  saving, so `view()` had to learn to render a missing screen template as nothing (a missing
  mail template still throws) — otherwise every write would have crashed after its commit.
  72 routes `ok` at 1280 and 375 afterwards; the write smokes pass. `https://subello.com` is now
  the React app. Full record and the way back: "As run" in `docs/react-cutover-runbook.md`.
  **Owed, not done:** (1) **invitations have no UI at all** — they lived only in the retired
  organizer screens; the handlers are kept, `invitation_send` is designed and unbuilt: the
  first slice of R7. (2) The dead HTML tails in ~230 controllers. (3) The provisioning script
  (Node + the web unit). (4) **The sync rule is owed:** the requirements (3 copies) and the
  build plan (2 copies) still describe the migration as in progress. (5) Renaming the staging
  host. (6) `fiscal_period_save` leaks a raw SQLSTATE on an overlapping period, as the
  access-grant handler did.
- [x] **Owner's click-through after cut-over, findings 2 and 3 (2026-09-19): no way to log out.**
  The avatar menu never opened — the toggle was given its own `onClick` (to stop the `#` from
  navigating), and a handler passed to react-bootstrap's `Dropdown.Toggle` REPLACES the one that
  opens the menu. Now a small `AvatarToggle` anchor prevents the navigation and then calls the
  handler it was given. And the sidebar gains **Log out** under a "Session" caption — a form
  posting the same server action (logout stays a POST with CSRF). `verify.sh` gained
  `--probe <script.mjs>`, so an interaction check runs inside its throwaway session; the probe
  showed the menu closed before the fix and open after it, at 1700 and in the 375 drawer.
  Lesson: route-render checks cannot see a dead control — menus and toggles need a click.
- [x] **A landing page (owner, 2026-09-19).** A visitor who is not signed in used to get a small
  sign-in card at `/`; now they get the Agent View itself — the fictional sample workspace,
  which needs no session and makes no call to the platform — with **Log in** in the header and a
  "Log in to your workspace" button under the heading, both to `/login`. `AgentView` takes an
  optional `loginUrl` for it; the plain card remains only for a deployment with no sign-in
  address configured. Checked signed out at 1440 and 375 (no sideways scroll, no console
  errors, both buttons land on the React login) and through `subello.com`. Nothing is logged:
  the sample data is built in the web app.
- [x] **The sign-in screens are dark (owner, 2026-09-19)** — login, 2FA, register, forgot and
  reset follow the dark landing page instead of flashing white after it. `components/shell/DarkSkin`
  puts the theme's own `app-skin-dark` on `<html>` from the auth layout: an inline script so a
  first load never paints light, a layout effect for arriving by client-side navigation (after
  logging out), and no cleanup — the workspace shell sets the skin from the person's stored
  preference the moment it mounts, so signing in lands in whichever mode they chose. No custom
  CSS: the theme's dark skin already covers the card, the inputs and the buttons.
- [x] **`agentview.subello.com` retired (owner, 2026-09-19).** The web app answers anything
  arriving under that name with a permanent redirect to `https://subello.com`, path and query
  intact (`web/next.config.mjs`). **The owner's part:** remove the name's DNS / outside-proxy
  entry on the proxy host — not reachable from this server. After that, Next.js can be bound to
  `127.0.0.1` so :3000 is no longer reachable except through Apache. `SESSION_COOKIE_DOMAIN`
  stays `.subello.com`: narrowing it now would leave signed-in people holding two competing
  cookies, and the wider one harms nothing.
- [x] **R7's first slice — Invitations (2026-09-19), closing the gap the cut-over left** (nobody
  could be invited from any UI). Whole, per the build discipline:
  **Screen** `/team/invitations` (React only — no PHP template exists for it): send form + the
  pending list with Resend / Revoke; an **Invite** button on People & access.
  **Handlers** `html/team/invitations/{index,save,resend,revoke}.php` — gate admin;
  `require_post()` + `verify_csrf()` + authorization + `check_approval()` + `log_activity()`
  (`invitation.send`, `invitation.revoke`, as the manifest names them). The rule is the approved
  view's (`mcp_business_invitations`): a super-admin invites anyone anywhere; a dept-admin only
  into a department they administer, and never a super-admin; a dept-admin invitation needs a
  department. **The accepting side was broken and is fixed:** registration (and the Google
  callback) read only the legacy cert-study role, so an invited department admin would have
  arrived as an ordinary user in no department — `apply_invitation_grants()` now applies the
  business role, the external flag and the department inside the registration transaction
  (proved in a rolled-back transaction). Mail links point at `/register?token=`.
  **Agents:** `invitation_send` / `_resend` / `_revoke` are built tools (smoke:
  `mcp/smoke/6-invitations.json`, 10/10 incl. the refusals and `needs_confirmation`), and
  `team_invitations` (the tool surface's name, A3 / A10 — pending only, as the view is) is a
  records read tool in the new `mcp/business_team.py`; the cert-study `pending_invitations`
  tool was retired with it. Checked as three people: the owner (all roles, all
  departments), Dana (User / Department admin, Accounting only; does not see an IT invitation)
  and Sam (refused). The legacy `html/organizer/` is deleted.
  **Two things found on the way:** a template-less handler's refusal reached the caller as "That
  could not be done." (`json_mode_finish()` reads the words off the rendered page) — such
  handlers now answer with `respond_invalid()`, recorded in CLAUDE.md; and **`ActionForm` lost
  what the person typed whenever PHP refused a submit** (React clears an uncontrolled form after
  its action) — the shared component now puts it back, which fixes every in-place form.
  **Not exercised:** a real person accepting a real invitation end to end (it needs a mailbox).
- [x] **The fourteen stubbed modules — questions answered up front (owner, 2026-09-19).** A
  read-only inventory found M1 had already decided most of it (every table and `mcp_*` view
  live, every screen, action and tool designed) and named the shared gaps: no secrets writer or
  `SECRETS_KEY`, no approval policies for the new send / money actions, no read views for five
  lookup tables, no PDF / RRULE / chart library, MaluMail's limits, a posting run that knows four
  sources. Twenty questions were put to the owner in five rounds; every answer, every default
  taken, the build order and the definition of done are in
  **`docs/build-specs/stub-modules-decisions.md`**, and CLAUDE.md points at it. Build progress
  follows below, one note per module.
- [x] **Stub modules — step 0, groundwork (2026-09-19).**
  **Secrets store:** `app/secrets.php` is the first writer of `tenant_secrets`, to the design
  decided on 2026-09-18 — AES-256-GCM, `SECRETS_KEY` (generated, appended to `config/.env`; the
  file is still `640 maludb:www-data`; backup in `~/env-backups/`), `key_version` and `last4`
  kept. Stored as `v<n>:base64(iv|tag|ciphertext)` with the secret's NAME as authenticated data,
  so a ciphertext copied onto another row does not decrypt; revoking destroys the value and
  keeps the row. `mcp/secrets_store.py` reads the same format for the Python jobs. Proved in a
  rolled-back transaction (store, read, swapped-ciphertext refusal, rotate keeps the id, revoke)
  and PHP → Python. **Losing `SECRETS_KEY` loses every stored credential — it belongs in the
  owner's backups.**
  **Approval policies:** `db/105` seeds the twelve the manifest implies and db/053 predates —
  mail from a shared mailbox, signature request / reminder, purchase order, report delivery,
  portal invitation (sends); pay-run approve / paid, compensation change, stock write-off, AI
  usage post / void (money). 32 policies live, all active.
  **PDF:** `maludb-os-pdf` (systemd, `www-data`, 127.0.0.1:8820; `web/scripts/pdf-service.mjs`;
  unit in `docs/deploy/`). It prints only this app's own pages — a relative path, loaded from
  the web app with the session cookie the caller hands it and `bos_quiet` — so a PDF holds what
  that person's screen would show. **Installed:** Playwright's headless Chromium to
  `/opt/ms-playwright` (the copy in the developer's home was unreadable to the service user).
  **Uploads:** PHP 25 MB / 27 MB post (`/etc/php/8.3/apache2/conf.d/99-business-os.ini`, copy in
  `docs/deploy/`), the web app's server actions 27 MB. Each feature keeps its own ceiling.
  **Not done here, on purpose:** the lookup `mcp_*` views — each module's slice adds the ones it
  needs once its schema has been read properly (`mail_thread_reads` and `content_variant_media`
  turn out to be reachable through their parents' views already).
- [x] **Stub modules — 1. Approvals (2026-09-19).** Spec: `docs/build-specs/approvals.md`. The
  decide-and-execute half existed; this adds what was missing and changes none of it.
  **Screens:** `/approvals` (Waiting for me / Asked by me, a status filter), `/approvals/{id}`
  (the request, what would be done as a key / value list, the timeline, the execution error when
  the action failed after approval, and Approve-with-note / Reject-with-reason / Withdraw for
  whoever may — PHP's `can`, and the handlers check again), `/settings/approval-policies` with
  its new / edit form. **PHP:** `html/approvals/view.php`; `app/features/approvals/policies.php`;
  `html/settings/approval-policies/{index,form,save,active,delete}.php` — reads insider-open as
  the view is, writes super-admin, events `approval_policy.save` / `.set_active` / `.delete`;
  the queue's stub fallback is gone. **Agents:** `approval_policy_save` / `_set_active` /
  `_delete` are tools (`mcp/smoke/7-approvals.json`, 12 / 12 incl. `needs_confirmation`, a bad
  pattern and a department policy with no department); read tools `approval_policy` (matches
  `invoice.send`, `invoice.*` and `*.send` for an `action_key`) and `approval_history` (with
  `decision_minutes`). **Checked as three people:** the owner sees everything; Dana and Sam read
  the policy list and are refused the forms ("This needs the super-admin"); Sam gets 404 on a
  request he is no party to and an empty history. **New tool for every later module:**
  `mcp/smoke_read.py <member> <tool> '<json>'` calls a records read tool as that member.
  No migration, no install. No OPEN decision.
- [x] **Stub modules — 2. Time (2026-09-19).** Spec: `docs/build-specs/time.md`.
  **Migration `db/106` (additive):** `time_entries.rejection_reason` (the manifest's reject takes a
  required reason and the table had nowhere to keep it) and `business_settings.default_hourly_rate`,
  both appended to their read views with `security_barrier` kept; `mcp_time_entries` also gains
  `has_rate` — THAT an entry is unpriced, not the number, which the view masks from anyone who
  does not administer the person. **Screens:** `/time` (the week Monday–Sunday, the timer, Submit),
  `/time/new`, `/time/{id}/edit` (a locked entry answers why), `/time/approvals`, `/time/report`.
  **PHP:** `app/features/time/{queries,request,present}.php`, eleven endpoints in `html/time/`.
  Rules as decided: the week starts Monday; draft → submitted → approved (locked) or sent back
  with a reason → edited back to draft; own time only, approvals `mod:time` for people whose time
  the caller may see, nobody decides their own week but the super-admin; **the rate is
  snapshotted when time is logged** — project rate → business default → none. **Agents:** eight
  tools (`mcp/smoke/8-time.json`), `time_update` a partial update (the manifest said "any field";
  all four such rows now name their create action); read tools `time_summary` and
  `missing_timesheets` in `mcp/business_time.py` — hours, never money.
  **Knock-on edits to built code:** Settings → Business has the default hourly rate; the project
  page's budget card shows hours logged and a Log time link; Unbilled work shows "No rate" and
  "—" for a masked rate instead of `0.00`. **`invoice_add_unbilled` had two real defects waiting
  for this module:** it billed `unit_price ?? '0'` — and the view masks the rate from most people
  who invoice, so their hours would have gone out at zero — and it never marked hours as invoiced,
  so every click billed them again. It now prices from the entry's own snapshot, skips unpriced or
  foreign-currency hours and says so, links and locks what it bills (`mcp/smoke/9-time-billing.json`,
  15 / 15: 95.00 billed once, the unpriced half hour skipped, a second click adds nothing).
  **Found by the smoke and fixed:** stopping a timer within a second of starting it failed the
  table's `ended_at > started_at` check (PHP's clock is coarser than the database's) — the end is
  now start + credited minutes, in SQL; the transaction had kept the timer. Also
  `app/partial_update.php` now writes a stored boolean as `'1'` / `'0'` rather than omitting a
  false (a handler whose default for "not sent" is true would have flipped it) — regression
  `mcp/smoke/4-fixes.json` still 51 / 51. My tool descriptions named a period `this_year`; the
  shared helper calls it `ytd` and reads an unknown word as this month — corrected in Time and
  Approvals. **Checked as three people:** Sam (no time module) logs and reports his own time and
  is refused approvals; `missing_timesheets` judges only people the asker may see.
  **OPEN (defaults taken):** approving locks the entries — un-approving is "reject the week",
  there is no separate unlock; `business_settings_update` (the agents' tool) does not carry the
  new default rate yet. Smoke entries sit in January 2026 on the owner's timesheet, locked.
- [x] **Stub modules — 3. Documents (2026-09-19).** Spec: `docs/build-specs/documents.md`. No
  migration (db/035 had it all). **Installed:** `poppler-utils` (`pdftotext`, for search);
  `react-markdown` + `remark-gfm` in the web app (a page's Markdown is rendered with NO raw HTML
  and no remote images). **Files** follow the rules agent photos set, at document scale: 25 MB;
  the type is decided from the file's own bytes (`finfo`), never its name; an allow-list of PDF /
  Office / OpenDocument / text / Markdown / CSV / images; stored at
  `storage/documents/<id>/<sha256>.<ext>`, `640 www-data`, outside the web root; served only by
  `html/documents/download.php` (the caller must SEE the document; always an attachment,
  `nosniff`; **every download is logged `document.download`**) through the web app's
  `/api/download` relay, whose closed allow-list gained that one path. Upload is screen-only —
  an action token is refused. Text from text / PDF / DOCX feeds the existing search trigger.
  **Screens:** `/documents` (folders, documents, full-text search across everything visible),
  `/documents/upload`, `/documents/pages/new`, `/documents/{id}`, `/{id}/edit`, `/{id}/versions`
  with a line diff for written pages. **PHP:** `app/features/documents/{storage,queries,present,
  request}.php`; 7 reads + 11 handlers in `html/documents/`. A changed body or a replacement file
  is a NEW version; restoring copies an old version into a new one — history is never rewritten;
  delete is soft. **Agents:** 11 tools (`mcp/smoke/10-documents.json`, 27 / 27) and read tools
  `find_documents`, `get_document` (a page's body, never a file's bytes), `record_documents`,
  `compare_document_versions` in `mcp/business_documents.py`.
  **Proved in a browser:** a real 176 KB PDF uploaded and downloaded back byte-identical; a shell
  script named `invoice.pdf` and an HTML page named `notes.txt` both refused; the PDF's words
  found by search; Sam (no grant, not the owner, no department) cannot find, open or edit it and
  is refused the upload screen.
  **Knock-on:** a Documents card (with Upload pointed at the record) on projects, companies and
  expenses; **`expense_attach_receipt` is real** — it was a placeholder waiting for this module —
  the receipt is one of the expense's documents, marked or detached on the expense page.
  **OPEN (defaults taken):** `desk_import_*` wait for phase 6; a deleted document's files are not
  purged after 30 days yet (no job); a page written by a person is recorded with origin
  `upload` (the enum has no "written here"); attaching a document from its own page asks for the
  record's number rather than offering a search. **Seen once, not reproduced:** the first verify
  batch after a deploy reported a 400 sub-resource on these pages; two further batches (28
  checks) and a URL-capturing probe were clean, and PHP logged no 400 — most likely chunk
  requests racing the web service's restart.
- **Memory (Hermes H7, memory part) — 2026-09-19.** `/memory` and `/memory/core/{member}`
  (`docs/build-specs/memory-screen.md`). Born after the cut-over: two JSON-only reads
  (`html/memory/index.php`, `core.php`) with whitelist presenters, no template. The search is a
  plain GET form — its state is the URL and it works without script. Scope is resolved from the
  session as the Memory MCP server resolves it from the token; there is no namespace parameter.
  The similarity score is deliberately not shown (no embedding model is configured, so it is
  arbitrary). Reached from **Memory** on `/agents` and **Core memory** on an agent's page.
- [x] **Stub modules — 4. Calendar (2026-09-19).** Spec: `docs/build-specs/calendar.md`.
  **Installed:** `rlanvin/php-rrule` (composer), `python-dateutil` (MCP venv, `requirements.txt`).
  **Migrations:** `db/107` — `appointments.recurrence_original_start` (db/033 called an exception
  "a child row pointing at the series" but a child could not say WHICH occurrence it replaces),
  appended to `mcp_appointments`; a read view `mcp_availability_blocks`; the Calendar application
  row's URL `/calendar/` → `/schedule/`. `db/108` — `mcp_busy_series`, busy TIME for recurring
  appointments (times only), because `mcp_busy_blocks` predates recurrence.
  **Recurrence (owner's decision: full RRULE with exceptions).** A series is one row; expansion
  is the library's, IN THE SERIES' TIMEZONE — proven across the US clock change (09:00 stays
  09:00, 13:00Z → 14:00Z). "This occurrence only" materialises a child row (moved / edited, or
  cancelled); an occurrence is addressed `<series>@<original start, UTC>`. The manifest gained
  the optional `occurrence` / `scope` parameters that needs (and `archived` on the two settings
  saves). **An exception row carries a copy of its series' crew and resources**, kept in step by
  every assign / unassign / respond / book / release — found when the first build left a moved
  occurrence with no crew, invisible to an ordinary assignee (`mcp_appointments` admits by the
  row's own assignees) and counted under "Nobody".
  **Conflicts warn, never block**: save / reschedule / assign / book report who else has the
  person or the resource then — names and times, never titles, counting what the asker cannot
  open. **Screens:** `/schedule` (day / week / month, in the viewer's timezone), book / edit
  ("this occurrence or the series"), the appointment page (crew answers, resources, conflicts,
  move, cancel), `/schedule/availability`, `/schedule/free`, and the two settings lists.
  **PHP:** `app/features/schedule/{recurrence,queries,request,present}.php`; 5 reads + 12 handlers
  in `html/schedule/`, 2 + 2 under `html/settings/`. **iCal feed re-pointed** at the member's
  appointments: a series is one `VEVENT` with its `RRULE`, a cancelled occurrence an `EXDATE`, a
  moved one a `RECURRENCE-ID` event. **Agents:** 15 tools (`mcp/smoke/11-calendar.json`, 38 / 38;
  `appointment_update` is a partial update, with a guard so an agent's partial update of ONE
  occurrence is not moved to the day the series began); read tools `schedule`, `find_free_time`,
  `schedule_conflicts`, `job_counts` (`mcp/business_schedule.py`).
  **Checked as two people:** Sam, an assignee with no scheduling grant, sees his occurrences
  including a moved one, answers for himself, manages his own availability, and is refused
  booking, editing and "who is free".
  **OPEN (defaults taken):** no notification goes to a customer when an appointment is booked,
  moved or cancelled (not in the manifest); working hours are per person — there is no
  business-wide default (Helpdesk's SLA hours will be their own setting); free-time slots are
  offered 07:00–19:00 on the half hour; all-day appointments are stored but entered as times;
  the iCal feed names a `TZID` without shipping a `VTIMEZONE` (Google and Apple resolve Olson
  names; a strict client may not).
- [x] **Stub modules — 5. Helpdesk (2026-09-19).** Spec: `docs/build-specs/helpdesk.md`.
  **Installed:** nothing. **Migration:** `db/109` — `business_hours` (owner's decision 8: one row
  per weekday, open / close in the business timezone, seeded Mon–Fri 09:00–17:00) with
  `mcp_business_hours`, and the two lookup views that were missing, `mcp_sla_policies` and
  `mcp_ticket_categories`. **Manifest gained** `business_hours_save` (super; the hours are a card
  on Settings → Business, shown read-only on the SLA page) and `archived` on
  `ticket_category_save`.
  **The SLA clock** (`app/features/tickets/sla.php`): a ticket takes its priority's policy (its
  department's if one exists), due times are set when it is opened and recomputed from its
  creation when the priority changes; with business hours only, minutes count inside the hours —
  Friday 16:30 + 60 min is Monday 09:30; no open day at all falls back to 24 / 7 rather than
  "never due". `pending` / `on_hold` show as *paused*, never breached.
  **Screens:** `/tickets` (status, priority, department, SLA breached / due soon, no reply yet,
  mine, search), open / edit, the ticket page (thread with internal notes marked, reply, note,
  assign, priority, status, resolve, close, reopen, delete, time logged + "Log time" which
  prefills `/time/new?ticket=`), `/settings/sla`, `/settings/ticket-categories`. **PHP:**
  `app/features/tickets/{sla,queries,request,present}.php`, 3 reads + 10 handlers in
  `html/tickets/`, 2 + 3 under `html/settings/`, and the portal's request endpoints
  (`html/portal/requests/{index,view,save,reply}.php` — own tickets only, public replies only);
  their React pages come with the `/portal` layout in module 11. **Mail:** `ticket_reply` emails
  the requester through MaluMail (`emails/ticket-reply`), says so when there is no address, and
  carries no Reply-To — a customer answers in the portal until Inbox brings mail in.
  **Agents:** 16 tools (`mcp/smoke/12-helpdesk.json`, 42 / 42 incl. refusals; `ticket_update` is a
  partial update; the one reply mail went to `example.invalid`); read tools `find_tickets`,
  `get_ticket`, `sla_status`, `similar_tickets`, `ticket_metrics` (`mcp/business_tickets.py`),
  checked as members 1, 5 and 6. **Checked as three people:** Dana (dept-admin of Accounting)
  sees the module but neither smoke ticket — one is Front Office's, one has no department; Sam,
  the assignee with no grant, reads his ticket and nothing else. Click probe
  `web/scripts/probe-ticket.mjs` (note, status, resolve, reopen at 1280 and 375).
  **OPEN (defaults taken):** (1) an assignee WITHOUT the tickets grant can read the ticket
  (`mcp_tickets` already shows it to them through every tool) but cannot work it — the manifest
  says `mod:tickets`; say if assignment should carry the right to reply. (2) The SLA clock is not
  paused while a ticket waits on the customer — the due times stand and the state reads
  "paused". (3) **An agent's reply pausing for approval was not proven through the agents' door**:
  the only seeded agent (Ledger Bot) has no agent profile, so it cannot hold the tool grants the
  MCP boundary now enforces; the handler calls the same `check_approval()` the Approvals module
  proved, against the live `ticket.reply` policy. (4) No satisfaction survey (the column exists;
  nothing in the manifest asks for it). (5) Portal requests arrive with no customer or
  department — triage assigns them.
- [x] **Stub modules — 6. Shared inbox (2026-09-19).** Spec: `docs/build-specs/inbox.md`.
  **Installed:** nothing (Python's `imaplib` / `email`). **Migration:** `db/110` — `search_tsv`
  appended to `mcp_mail_messages`, so `search_mail` (which runs as `app_records_ro`) has something
  to search. **systemd:** `maludb-os-inbox-poll.timer` (every 2 min, www-data), units in
  `docs/deploy/`, installed and enabled here.
  **Mail in — IMAP polling (owner's decision 6). Python parses, PHP files:**
  `mcp/inbox_poll.py` reads each active IMAP mailbox over TLS **read-only** (`select(readonly)`,
  `BODY.PEEK[]`, nothing deleted or moved), reduces an HTML-only mail to text, stores attachments
  by sha256 under `storage/mail/<mailbox>/` with no extension, and hands JSON to
  `php bin/inbox_ingest.php` (`app/features/inbox/ingest.php`), which owns every database rule:
  de-duplication on Message-ID, threading (In-Reply-To / References → a `[T-00042]` in the subject
  → same subject + correspondent within 30 days → new), contact matching by sender, routing
  rules on the first message of a new thread, tickets through Helpdesk's `insert_ticket()` (so
  SLA times are right — the SLA lookups moved to base tables for that), and **a customer's
  mailed answer on a ticketed thread lands on the ticket and reopens it**. The credential is one
  tenant secret (`mailbox-<id>-imap`, purpose `email`, AES-256-GCM; password first so the stored
  hint never carries it); the form is told only whether one exists. **No real mailbox is
  connected: the IMAP leg is proven by `mcp/test_inbox_poll.py` against a stand-in server (read-
  only, PEEK-only, known mail skipped) and by the timer reaching DNS failure on the smoke
  mailbox and recording it; everything after the fetch is proven with `--eml` fixtures.**
  **Mail out — MaluMail within its limits (decision 7):** `cc` and `attachments` are refused,
  never dropped; reply-all puts the others in To; a ticketed thread's subject carries the
  number; the screens say it leaves from the platform's address and that an answer to it does
  not come back to the mailbox. A refusal by the mail service records nothing as sent.
  **Screens:** `/inbox` (mailbox, status, mine / unassigned, unread, starred), the conversation
  (plain-text bodies only, attachments as forced downloads through `/api/download`, reply +
  draft, assign, status, open a ticket, file an attachment in Documents), `/inbox/compose`,
  `/inbox/search`, `/settings/mailboxes` (+ connect / edit, rules with the add form beside the
  list; `/rules/new` redirects there). **Agents:** 15 tools (`mcp/smoke/13-inbox.json`, 52 / 52
  with refusals; the harness gained a `shell` step and now refuses to call a tool with an empty
  variable — an empty name had resolved against real records); read tools `find_mail_threads`,
  `mail_thread`, `search_mail`, `mailbox_stats`, `mailbox_rules` (`mcp/business_inbox.py`).
  **Checked as three people:** Dana sees no Front Office mailbox; Sam — assigned a thread by a
  rule, no Inbox grant — sees that one conversation, sets its status and replies, and is not
  offered assign, draft, ticket or compose (`web/scripts/probe-inbox.mjs`; found and fixed: the
  page read "is the mailbox on" through a view he cannot see).
  **OPEN (defaults taken):** (1) replies to what we send go to `MAIL_FROM`, not the mailbox —
  per-mailbox senders need MaluMail sender verification and Reply-To; until then `MAIL_FROM`'s
  own mailbox should be the one polled. (2) `MAIL_FROM` here is a real address, so smoke mail to
  `example.invalid` bounces to it, and MaluMail then suppresses the address (a second send is
  refused — handled, shown). (3) Only `imap` inbound is built; `forward` / `malumail` are
  refused on save. (4) Rules run only on a new conversation's first message; a `tag` rule uses
  an existing tag and never invents one; there is no rule re-ordering UI (they run in the order
  added). (5) Attachments over 25 MB are skipped, not stored. (6) An agent's send pausing for
  approval is not proven through the door (same reason as Helpdesk); the `check_approval()`
  calls are in `send.php`, `reply.php` and `rule-delete.php` against the policies db/105 seeded.
  (7) `email_messages` (the transactional-mail log) is still written by nothing — `mailbox_stats`
  reports what the inbox sent, not delivery.
- [x] **Stub modules — 7. Content & social (2026-09-19).** Spec: `docs/build-specs/content.md`.
  **Installed:** nothing. **Migration:** `db/111` — `mcp_content_variant_media`, the read view
  db/040 never gave the media table: an attachment shows only to someone who can see BOTH the
  content item and the document (it joins `mcp_content_variants` and `mcp_documents`), so a
  variant never leaks a document's title.
  **Nothing posts to an outside network** (owner's default): `content_publish` answers "published
  by hand — record the link" for a manual channel and "not connected yet" for a connector one,
  with its `check_approval()` already where it will matter; `channel_save` takes no credentials
  and every channel is `not_connected`. What is real: an item with one variant (the words) per
  channel; **every item is reviewed** — `idea` → `draft` → `in_review` → `approved` (the named
  reviewer or an admin; a non-admin never approves their own) or back to `draft` with a note (kept
  in the activity trail, shown on the item; reviewer and author are notified, kind
  `content_review`); scheduling (a PLAN, future-only, in the caller's wall time) and **marking
  published with the link** both need an approved item; changing approved words un-approves them,
  scheduled words must be unscheduled first, published words are never rewritten; metrics are
  hand-entered snapshots on a published variant (the latest is "how it did"); archive shelves an
  item and takes its slots off the calendar, un-archive settles it from what its variants say
  (`content_settle_status()`). `content_delete` is refused once anything was published;
  `campaign_delete` leaves content, expenses and leads in place.
  **Screens:** `/content` (status, campaign, author incl. "written by agents", failed, search
  over titles, briefs and the words), new / edit, the item page (a card per channel: words,
  media from Documents, slot, link, numbers; review, archive, delete), `/content/calendar`
  (week / month in the viewer's timezone, per channel, and the channels with nothing planned in
  14 days), `/content/performance` (ranked by a chosen metric, totals per channel — tables, not
  charts), campaigns (list, plan / edit, a campaign's content, numbers, budget vs the expenses
  and hours THE VIEWER may see, attributed leads and deals), `/settings/channels`.
  **PHP:** `app/features/content/{queries,request,present}.php`; 5 reads + 13 handlers in
  `html/content/`, 3 + 3 in `html/content/campaigns/`, 1 + 2 in `html/settings/channels/`.
  **Agents:** 20 tools (`mcp/smoke/14-content.json`, 71 / 71 with refusals — approval order,
  past slots, a `javascript:` link, rewriting published words, a document the caller cannot see,
  deleting published content); `campaign_update` is a partial update, `content_update` changes
  only what it is sent; **`reviewer` and `owner` now resolve by name** in the actions server (a
  reviewer given by name had been dropped silently). The manifest gained `remove` on
  `content_attach_media`, `q` on `content-list`, `metric` on `content-performance`. Read tools
  `content_calendar`, `content_pipeline`, `content_performance`, `channel_health`,
  `find_content`, `unapproved_publishing` (`mcp/business_content.py`), called as members 1, 5, 6.
  **Checked as three people:** Dana (dept-admin of Accounting) opens the screens and sees none
  of Front Office's or the department-less items; Sam — reviewer of one item, no Content grant —
  sees that item only, is offered Approve / Ask for changes and nothing else (375 px, no
  overflow). Click probe `web/scripts/probe-content.mjs`: the whole walk, a refused bad link,
  numbers recorded.
  **OPEN (defaults taken):** (1) **every** item needs approval before it is scheduled or
  published, and a non-admin author cannot approve their own — a one-person team works only
  because its one person is an admin; say if a "no review needed" switch is wanted. (2) A
  schedule is a plan only: no reminder fires at the slot (notification kind `content_published`
  / a "due to post" nudge is unbuilt) and nothing marks a missed slot. (3) The change-request
  note lives in the activity trail, not a column. (4) Agent approval pauses
  (`content_variant.schedule`, `content_variant.publish`, `*.delete` — all seeded in db/053) are
  called but not proven through the door (no agent here can hold tool grants — as Helpdesk).
  (5) A new item takes its campaign's department; with no campaign it has none, so only its
  author, reviewer, grant-holders and super-admins see it. (6) Attribution (`source_campaign_id`
  on companies, contacts, deals) is only READ here — nothing in Contacts / Deals sets it yet, so
  a campaign's leads stay 0 until those forms offer the field. (7) Campaign cost is expenses +
  hours; AI spend and hours × rate belong to `cost_breakdown` (Reports). (8) Media is a link to
  a Document, shown as a link — no image preview on the variant card.
- [x] **Stub modules — 8. Products & inventory (2026-09-19).** Spec: `docs/build-specs/inventory.md`.
  **Installed:** nothing. **Migration:** `db/112` — `product_id` + `product_sku` appended to
  `mcp_invoice_lines` / `mcp_quote_lines` (the line tables have had the column since db/059; the
  views never showed it); GL accounts **2050 Goods received not invoiced** and **5100 Inventory
  adjustments and write-offs** (only if the chart lacks the code); posting rules for source
  `inventory` keyed by movement kind; expense category **Stock purchases** with its own rule
  (Dr 2050 / Cr 2000), so the bill made from a purchase order clears GRNI instead of counting the
  purchase twice. Nothing existing altered.
  **Weighted average cost (owner's decision 13)** — `app/features/inventory/stock.php`, ONE
  `stock_move()` for every movement, arithmetic in Postgres under a row lock. The average is per
  product per location (as db/059 has it); `products.cost_price` follows as the quantity-weighted
  average across locations. In with a cost: (on hand × avg + in × cost) ÷ new on hand — **into
  zero or negative on-hand the received cost becomes the average**; in without a cost arrives at
  the average; out leaves at the average and records it. Proven through the agents' door:
  6 @ 4.00 then 10 @ 7.00 → 5.8750; + 4 @ 4.00 → 5.5000; a transfer carries its cost; + 2 @ 9.00
  → 5.9375; count, write-off, void and credit leave it where it should be.
  **Stock out on SEND (decision 14)** — three one-line hooks (`html/invoices/send.php`,
  `void.php`, `credit-issue.php`). Idempotent by arithmetic (what the invoice's product lines
  need minus what its movements have issued net): a re-send issues nothing. A void returns
  everything at the cost it left at. **A credit note is an amount, not lines: stock comes back
  only when issued credits cover the whole invoice.** **Not enough stock never blocks a sale** —
  the level goes negative (proven at −38), the action's answer says so, screens flag it.
  **Product picker (decision 15)** — the shared invoice / quote line editor
  (`web/components/sales/DocumentParts.tsx`) gains "or pick a product" beside the catalogue;
  `line_fields_from_request()` reads `product_id` and fills blank description / price / tax;
  both line upserts and the quote→invoice copy write it; an edited line carries its product in a
  hidden field (otherwise an inline edit would have detached it and silently stopped its stock
  leaving). Found and fixed on the way: an edited line kept showing its OLD quantity until a
  reload (uncontrolled inputs — now keyed by the saved value). `mcp/smoke/1-crm-sales.json`
  still 33 / 33.
  **Ledger (decision 16)** — the posting run gains source `inventory` by its own pattern
  (`unposted_stock_movements()`: left join on `journal_entries` by `stock_movement`, period-aware,
  a movement with no cost skipped with that reason, `stock_movements.journal_entry_id` stamped):
  receipt Dr 1400 / Cr 2050; sale Dr 5000 / Cr 1400 and its return reversed; write-off,
  adjustment and count Dr 5100 / Cr 1400 (a gain reversed); transfers move no value. A product's
  own inventory / COGS account wins over the rule's. Proven: 13 entries balanced, a second run
  posts nothing, and **the 1400 movement for the product equals its stock value (98.75)**; the
  PO's bill posts Dr 2050 / Cr 2000.
  **Purchase orders:** draft → sent (emailed through MaluMail if the supplier has an address —
  template `emails/purchase-order` — else marked sent and said so; admin; confirm; an agent's
  waits) → partial / received → bill (once; what was received; unpaid, awaiting approval; also
  `mod:expenses`). Cancel only before anything arrives.
  **Through the agents' door:** repeated params are flat text — `lines[]` =
  `product:quantity:unit_cost`, `counts[]` = `product:qty`, `received[]` = `line:qty` — and
  product / location / supplier / order accept an id or a SKU / exact name / PO number, resolved
  in PHP. 12 tools, `mcp/smoke/15-inventory.json` **101 / 101** incl. refusals. Read tools
  `find_products`, `stock_levels`, `stock_movements`, `product_sales`, `purchase_orders`
  (`mcp/business_inventory.py`). **Screens:** 15 (adjust · transfer · write off share one page;
  the location add form sits under its list). Probes: `web/scripts/probe-invoice-product.mjs`,
  `probe-inventory.mjs` (PO form, send, receive page, count — the parallel-array forms).
  **Gate (found by verifying as Dana):** `require_module()` admits any dept-admin, but products
  and stock carry no department — so every product / stock endpoint and every purchase-order
  WRITE uses `require_module_grant('inventory')`; a dept-admin still reads the orders of their
  departments. Without the grant: products, quantities and locations yes; cost, value, movements,
  orders no (the views mask them).
  **OPEN (defaults taken):** (1) negative stock is allowed and flagged, never blocked.
  (2) A partial credit note returns no stock — record the return with an adjustment. (3) Stock
  always leaves the DEFAULT location; an invoice cannot name another. (4) Revenue still posts to
  the invoice rule's account — a product's income account is stored but not used until invoice
  posting splits by line. (5) Purchase tax is part of the bill's gross, as expenses already post.
  (6) The bill covers what has been received when it is made; a later receipt is not billed
  again (one bill per order). (7) No FX: a product, its orders and its stock value are in one
  currency. (8) Agent approval pauses (`purchase_order.send`, `stock_movement.write_off`,
  `expense.create`) are called but not proven through the door — same reason as Helpdesk.
  (9) `mcp/smoke/2-projects-expenses-books.json` fails 4 steps on its own fixed-date fiscal
  period colliding with an earlier run's — not from this module.
- [x] **Stub modules — 9. People (2026-09-19).** Spec: `docs/build-specs/people.md`.
  **Installed:** nothing. **Migration:** `db/113` — a trigger that refuses an employment record
  for an agent (db/058 kept agents from SEEING people data; nothing kept one from BEING an
  employee). **Cron:** `bin/grant_annual_leave.php` is in `docs/deploy/crontab.example` (daily,
  idempotent) but **NOT installed**: the installed www-data crontab already differs from the
  example (it lacks `run_recurring_expenses.php` and `post_documents.php` too), so re-installing
  from the example would switch on two other jobs nobody asked for here — OPEN, one command:
  `sudo crontab -u www-data docs/deploy/crontab.example` once the owner wants all three.
  **Pay is the tightest data in the system and nothing here widens db/058's rule**
  (`app_can_see_person()`: yourself, your reports, HR for the people they administer, the
  super-admin; agents nothing). HR writes ask the people GRANT of the database plus
  `app_can_admin_member()` — never `has_module()`, which admits every dept-admin; pay runs use
  `require_module_grant('people')`. **Activity rows carry no figure**: a pay change logs that it
  changed, its date and type; an employment save lists the changed fields but never the pay,
  home details or bank details (scanned after the smoke: 0 rows naming a figure). Home contact
  details are read only by the HR edit form; bank details are a write-only tenant secret.
  **Checked as three people and an agent:** Dana (dept-admin of Accounting, where Sam works, no
  people grant) and Sam each see only their own record and pay — the other's page is 404, the
  edit / pay-change forms and every pay-run screen are refused, and the five read tools answer
  "not found" or nothing; given the people grant Dana sees Sam and the runs, and loses them
  again on revoke; Ledger Bot is refused at the MCP boundary.
  **Leave (owner's decision 12: granted upfront each year):** the allowance is granted when an
  employment record becomes active and by the yearly job, pro-rated from a start date inside the
  year and **rounded DOWN to the half day** (start 1 July: 20 → 10, 12 → 6; the job's second run
  creates nothing); carry-over is `leave_balance_adjust`. Days = the business's open weekdays
  (Helpdesk's `business_hours`). A request over the balance or overlapping another is accepted
  and flagged; **approving over the balance is refused unless HR passes `override`** (added to
  the manifest). A type needing no approval is approved as it is made. Approval draws the balance
  down and puts an `unavailable` block on the person's calendar — `find_free_time` is honest —
  and cancelling gives both back. Nobody decides their own leave (the super-admin excepted).
  **Pay runs — no tax is calculated, nothing is filed, no money moves** (said on both screens):
  salary = annual rate ÷ the schedule's periods; hourly = APPROVED time in the period not already
  on another live run, traced in `time_entry_ids` (a second run for the same period finds 0 h);
  anything else — daily, per invoice, no schedule, another currency — puts the person on the run
  with **no amount and a note saying why**. HR keys in deductions, employer costs and
  reimbursements (`kind:code:amount:description` through the agents' door). Approve / mark paid /
  void are super-admin only. **Posting (decision 16):** `unposted_pay_runs()` joins the posting
  run beside stock — a PAID run posts on its pay date, Dr 6000 (or a line's own account) for
  earnings + reimbursements + employer costs, Cr 2200 for the same total, by the rule db/023
  seeded; `post_to_books` posts that one run at once under the same lock and period guards
  (proven: 6,500 + 100 + 50 gross, 300 employer → Dr 6000 6,950 / Cr 2200 6,950; a second
  posting run adds nothing).
  **Screens:** `/people` (+ people with no record, for HR), the person (employment / pay / leave
  tabs, end employment, adjust a balance), edit / first record, pay change, `/people/payruns`
  (+ new, the run with per-person line editing), `/people/leave` (+ request, who is off),
  `/settings/leave`. **PHP:** `app/features/people/{queries,leave,payroll,request,present}.php`;
  4 reads + 3 handlers in `html/people/`, 3 + 6 in `payruns/`, 3 + 4 in `leave/`, 1 + 1 in
  `html/settings/leave/`. **Agents:** 14 tools (`mcp/smoke/16-people.json`, 67 / 67 with
  refusals; `employment_profile_save` keeps what is not sent); read tools `find_people`,
  `employment_profile`, `payroll_summary`, `pay_runs`, `leave` (`mcp/business_people.py`).
  Click probe `web/scripts/probe-people.mjs`: Sam requests a day at 375px, the owner approves it
  (10 → 9 days, shown on "who is off"), then cancels it (back to 10). Regression:
  `15-inventory` 101 / 101 after the posting change.
  **OPEN (defaults taken):** (1) the cron line above. (2) A manager sees their reports' PAY —
  that is db/058's rule, kept as written; say if managers should see employment and leave only.
  (3) Marking a run paid does not post the bank side (Dr 2200 / Cr bank): the liability is
  cleared by a bank-side entry, because which account paid is not recorded. (4) Only PAID runs
  post (an approved run can still be voided); there is no accrual at approval. (5) `birth_date`
  and `national_id_last4` have no screen; the person page has no Documents tab (HR paperwork is
  linked in Documents, which has no `member` link target yet). (6) No notification is sent when
  leave is requested or decided (no in-app notification helper exists to call). (7) A leave
  request may not cross a calendar year, and half days are whole-request only. (8) An agent's
  pay change / run approval pausing for approval is called (`check_approval()` with the amount)
  but not proven through the door (same reason as Helpdesk) — and such a paused request keeps
  the posted figures in `approval_requests`, visible to its approvers, which is what a replay
  needs. (9) Smoke pay runs are real postings in August 2026 (6,950 each run) — a paid run cannot
  be voided by design, so they stay, like Inventory's.
- [x] **Stub modules — 10. E-signature (2026-09-20).** Spec: `docs/build-specs/signatures.md`.
  **Installed:** nothing. **Migration:** `db/114` — db/060 modelled requests, signers and events
  but not WHAT was signed or HOW: `signature_requests` gains `document_version_id`,
  `document_sha256`, `executed_render_error` and a one-time render token (hash + expiry);
  `signature_signers` gains `signed_name`, `consent_at`, `signature_image_path`, `user_agent`;
  the three views get columns appended (fingerprint, typed name, addresses, "has a drawn
  signature") — never a token, a token hash or an image path.
  **Built-in signing only (owner's decision 17):** `provider_id` stays NULL, `/settings/signatures`
  explains how signing works, and `signature_provider_save` answers "no outside provider is
  built yet" and stores nothing — no credential.
  **The signer's side** is the first PUBLIC page after the landing and login pages: `/sign/<token>`
  in a new bare `(public)` layout (no sidebar, command bar or Agent View), on the PUBLIC list in
  `web/middleware.ts`, NOT on Apache's allow-list. Typed name + consent tick + optional drawn
  signature (a pointer-event canvas, PNG checked byte-for-byte, ≤ 200 KB, stored under
  `storage/signatures/`), or Decline with a reason (which ends the request). **The no-session
  POST is protected the way the login form's is:** the server action calls `apiPost()`, which
  opens PHP's anonymous pre-login session, takes its CSRF token and posts with it —
  `verify_csrf()` is untouched; the token is the authority (32 random bytes, only its sha256
  kept, looked up by hash and re-checked with `hash_equals`, one signer per link, expiring with
  the request — 30 days by default; wrong links are counted per address in `login_attempts`,
  20 in 15 minutes). A link that cannot be used gets ONE plain sentence and nothing about the
  document. Because only the hash is kept, **a reminder re-issues the link and the earlier one
  stops working** (the mail says so); `php bin/signature_link.php <signer-id>` is the operator's
  version and what the smoke signs with.
  **What is signed is fixed at send:** the document's current version and the sha256 of its exact
  bytes (the stored file, re-hashed from disk; or a written page's Markdown). If the document has
  a newer version when someone comes to sign, signing is refused. A file is offered to the signer
  through a token-scoped relay (`/api/sign-document`), always as a download. Sequential order is
  enforced — the next signer's link is issued when the previous one signs.
  **The executed copy:** completion happens FIRST; then PHP mints a one-time render token and has
  `maludb-os-pdf` print `/sign/executed/<token>` — the written page in full, a signature block
  per signer, then the audit page (certificate id, fingerprint, every step with its address and
  browser) — and files the PDF as a NEW Document (`origin = generated`), tied to the same record.
  **Found by the smoke:** with the page not yet deployed the printer happily printed the LOGIN
  page (it answers 200) and that was filed as the executed copy — so the real page prints a
  certificate id (`SR-<request>-<start of the hash>`) and PHP reads the PDF back and refuses one
  without it. A failed print is recorded and `signature_document_file` makes it again (proved by
  replacing that bad copy); it also moves the copy into a folder.
  **Screens:** `/signatures` (status, expiring), `/signatures/new?document=&entity_type=&entity=`
  (signers as rows, order = row order), the request page (signers with typed name, drawn
  signature and address; the trail; send, remind one or all, void with a reason, executed copy),
  `/settings/signatures`. **Agents:** 8 tools (`mcp/smoke/17-signatures.json`, 88 / 88, with
  `mcp/smoke/sign_as.py` acting as the signer against the token endpoints: wrong, replaced, used,
  voided and not-your-turn links refused; no name, no consent and a fake PNG refused; a changed
  document refused; the fingerprint equal to the file on disk and to what the signer downloads;
  the executed PDF read back for its names, hash and certificate; no link in any activity row);
  read tools `find_signature_requests`, `signature_audit` (`mcp/business_signatures.py`) — no tool
  can return a link, because none is stored. **Checked as three people:** the owner, all routes;
  Dana (dept-admin, no grant) opens the module and gets 404 on requests outside her departments
  and nothing from the tools; Sam is refused the module. Probes: `web/scripts/probe-sign.mjs` (NO
  session: wrong link, draw, sign, thanked, same link refused — 1280 and 375, a sequential pair)
  and `probe-signatures.mjs` (add signer, send, remind, void at 375).
  **OPEN (defaults taken):** (1) for a FILE original the executed copy is a certificate naming
  the file and its fingerprint — the original PDF's pages are not re-stamped. (2) `reminder_days`
  is stored but nothing reminds on its own — no job exists yet; Remind is a person's click.
  (3) `cc` people are recorded and mailed nothing — MaluMail cannot attach the executed copy and
  a link to it would need the portal; nobody is mailed on completion either (the sender sees it
  on the request). (4) Delivery is not tracked: a bounced signer still reads "Sent" (the
  `email_messages` log is written by nothing). (5) An expired request is marked so lazily, when
  a list, a request page or a link is next opened — no job. (6) A signer's name with a comma or
  colon cannot be passed through the agents' flat `signers[]`; add that signer with
  `signature_signer_save`. (7) An agent's send / remind pausing for approval is called
  (`signature_request.send` / `.remind`, db/105) but not proven through the door — same limit as
  Helpdesk. (8) Identity is possession of the mailbox the link went to — no SMS code, no ID check.
  (9) A draft is withdrawn by voiding it; there is no delete (the manifest lists none).
- [x] **Stub modules — 11. Portal & Forms (2026-09-20).** Spec: `docs/build-specs/portal-forms.md`.
  **Installed:** nothing. **Migration:** `db/115` — `invitations.share_organization_id` (a portal
  invitation names the company the External person is for); columns appended to `mcp_forms`
  (`appointment_type_id`, `notify_member_ids`, `redirect_url`, `spam_protection`, `created_at`) and
  `mcp_form_submissions` (`submitted_by`), barriers and grants kept; **the Portal application row
  now opens at `/forms/`** — settled: `/forms` is the insiders' module, `/portal` is what an
  External person sees.
  **The portal (owner's decision 18):** its own layout (`web/app/(app)/(portal)/`) — business
  name, who is signed in, Log out; no sidebar, no command bar, no Agent View. **The `(shell)`
  layout sends an External member to `/portal` whatever URL they tried** (observed: `/dashboard`,
  `/contacts`, `/tickets`, `/settings/portal`, `/forms/submissions` all end at `/portal`), and PHP
  refuses them on workspace reads regardless (403s sampled). An insider at `/portal` gets a note
  and a link back; a switched-off portal says so. **Nothing was widened** — every list is an
  existing view asked as the External caller: requests (Helpdesk's endpoints, now with React
  pages — list, new, thread with public replies only, reply), sent invoices and quotes of the
  company shared with them (a draft never shows — proven with a draft quote), projects (no
  rates), documents shared one by one (downloaded through `html/portal/document.php`, which asks
  `mcp_documents`; an unshared document is 404). **Appointments stay OFF**: `mcp_appointments` is
  insider-only. Online payment is stored and shown as "not available yet".
  `portal_access_invite` issues an External invitation; accepting it (password or Google) makes
  the person External and shares that one company with them (`apply_invitation_grants()`); its
  own mail template, because the ordinary invitation mail still speaks of certification study.
  `bin/invitation_link.php` re-issues a link for an operator. **The external test user** (member
  46, `SMOKE Keep Portal Customer`, `smoke-portal-keep@example.invalid`) was made that way: the
  invite action → a re-issued link → the real registration endpoint.
  **Public forms (`/f/<slug>`, PUBLIC in `web/middleware.ts`, the `(public)` layout Signatures
  made):** only a published form answers; the server action posts with PHP's anonymous session
  CSRF token, so `verify_csrf()` is untouched. **Spam = a trap field + a rate limit**: a filled
  trap is thanked like anyone and stored as `spam` (creates nothing, notifies nobody, not
  counted); 5 answers per form per address per 10 minutes (`login_attempts`, marker
  `public-form-<id>`), then a plain "try again later". Unknown keys are ignored, values capped,
  choices checked against the form's own, what a stranger wrote is only ever shown as text.
  `redirect_url` is a site path or `https://` — `http://`, `//host` and `javascript:` are refused
  on save and re-checked on use. **`submit_action` runs at once** for contact / ticket / deal
  (manifest, "Public form endpoint"; the contact is matched by email first; a stranger's form
  never creates a company); **an appointment is never booked automatically.** Insider screens:
  forms, settings + routing, the field builder (up / down, no modal), submissions, one submission
  (process into records, spam, reject), portal settings with who has access. **Agents:** 12 tools
  (`mcp/smoke/18-portal-forms.json`, 78 / 78, with `mcp/smoke/submit_form.py` acting as the
  visitor — good, invalid, tampered choice, injected key, trap, burst, closed); `assign_member` /
  `assign_to` now resolve by name. Read tools `find_forms`, `form_submissions`, `portal_status`
  (`mcp/business_forms.py`) — checked as 1, 5, 6 and the External member, who gets only their own
  shares. **Probes:** `probe-public-form.mjs` (no session, 1280 + 375), `probe-portal.mjs`,
  `probe-forms.mjs`; regression: 18 workspace routes `ok` as the owner after the shell change;
  smokes 6, 12 and 18 re-run clean.
  **OPEN (defaults taken):** (1) **there is no way to share a document or project with a customer
  yet** — `record_share_create` / `_revoke` are in the manifest (Team & access) and unbuilt; the
  one document share used to prove the portal was inserted by hand. (2) `sections` per customer
  is refused — the schema has only business-wide switches. (3) No uploads on public forms
  (`file` fields are refused). (4) Portal shows lists only — no invoice / quote page or PDF for
  the customer. (5) Notifications for a submission are in-app only (kind `system`; the schema has
  no form kind) — no mail. (6) A ticket from a form has origin `portal` (nearest the constraint
  allows). (7) Agent approval on `portal_access_invite` is called, not proven through the door
  (same reason as Helpdesk). (8) The smoke leaves the portal **switched on** with a SMOKE welcome
  and its latest form as the support form — switch it off on `/settings/portal` if unwanted.
  (9) A dept-admin without the grant may only save forms into a department they administer.
  (10) The legacy invitation mail's cert-study wording is still what ordinary invitations send.
- [x] **Stub modules — 12. AI Ops (2026-09-20).** Spec: `docs/build-specs/ai-ops.md`.
  **Installed:** nothing. **Migration:** `db/116` — `journal_entry_id` appended to
  `mcp_ai_usage_postings` (the view predated the general ledger; barrier and grants kept).
  **Already there, verified and linked to — not rebuilt:** the model registry screens and
  actions (`/settings/models…`, `model_save`, `model_set_status`); the runner's `agent_runs`,
  `prompt_ledger` and `prompt_payloads`; tools `agent_runs`, `ledger_calls`,
  `prompt_for_request`; the `ai_usage` posting rule (Dr 6050 / Cr 2000, db/056) and the
  agent-approval policies for posting and voiding (db/105).
  **Built — the prompt log** (`/ai/prompt-log`, a call's page, `/ai/runs/{id}`): every model call
  with who, model, outcome, tokens, latency, cost; one call's full prompt and response as
  pretty-printed JSON in **plain pre-wrapped text, never HTML**, capped at 400 KB a side, with
  what that request did in the activity trail; a run with what it was asked, what it answered,
  its calls, the runs it delegated and what it changed. **The views decide who reads what and
  nothing widens them:** the `ledger` grant sees all; a person their own calls; an agent's calls
  whoever may see that agent; the PROMPT (`mcp_prompt_payloads`) the same people, humans only. A
  payload past retention reads "payload expired". Opening a call logs one `screen.view` carrying
  the ledger id — **no prompt text ever reaches the activity trail** (checked in the smoke).
  **Spend** (`/ai/spend`): by agent, model, provider, department or day, with what caching saved
  (cached tokens × the gap between the input and cache-read price) and a note when the viewer is
  not seeing the whole business.
  **AI usage reaches the books (owner's decision 16).** `ai_usage_post` (month `YYYY-MM`;
  super-admin or the expenses grant; an agent pauses with the amount) summarises a CLOSED
  month's ledger into `ai_usage_postings` — one row per provider × model, base currency only —
  and the posting run carries each to the GL on the month's last day (`unposted_ai_usage()` in
  `app/features/books/posting.php`, added the way stock and pay runs were). It refuses the month
  in progress ("has not ended"), a month with no cost, and a month already posted;
  `ai_usage_void` (super, a reason) reverses the journal entry and frees the month. No expense
  row is made — it would post the same money twice. `/ai/spend/postings` shows every month:
  ledger cost, posted, not posted, and "Not yet" for the month in progress.
  **What was posted to the books: NOTHING.** The ledger holds only September 2026 (77 calls,
  3.63 USD of real agent work), which is rightly "not yet". The GL leg is proven instead by
  `bin/test_ai_usage_posting.php`, which runs the whole chain — a made-up call in August →
  summary (1.234567 → 1.23, the zero-cost call counted) → posting row → the run sees it → Dr 6050
  1.23 / Cr 2000 1.23, posted, dated 31 August → linked back → a second run finds nothing —
  **inside one transaction that is rolled back**, then checks nothing of it is left. An invented
  row in an append-only subledger would have been a permanent lie; this leaves none.
  **Evals: authoring is real, running is not (owner's decision 19).** Sets (for an agent or a
  role), cases (written, or promoted from a real call or run — the server re-reads the trace, the
  case keeps its source), active / inactive, standing schedules, the Audit watch, graded traces,
  run and alert pages. **`eval_run_start` answers 409 "Evals cannot run yet — the eval runner is
  not built. The set and its cases are saved." and writes no run and no score** (proved:
  `eval_runs` stays 0; the attempt is logged so Audit can see evals being asked for). A schedule
  is saved with `next_run_at` empty and says nothing will run it. Every eval screen and the three
  eval tools say "no runner yet", so an empty list is never read as "all passed". Eval endpoints
  refuse agents; cases are humans-only in the view itself. `eval_result_grade`,
  `eval_alert_acknowledge` and `eval_alert_resolve` are built though nothing can yet produce a
  result or an alert. The eval gate on configuration changes (db/096) is untouched.
  **Agents' door:** 11 new action tools (`mcp/smoke/19-ai-ops.json`, 49 / 49 with refusals);
  read tools `ai_spend` (usage / postings / reconciliation), `model_catalog`, `eval_status`,
  `eval_findings`, `eval_watch`, `ungated_deployments` (super) in `mcp/business_aiops.py`.
  **Checked as four people:** the owner — all 19 routes at 1280 and 375. **Dana (dept-admin of
  Accounting, no `ledger` grant) and Sam see NO calls, NO prompts and NO spend** — the Accounting
  agents' calls are not theirs to see (`app_can_see_agent` is the manager / HR rule, not the
  department's), a call's URL is 404, postings and eval authoring are refused, `ai_spend` returns
  nothing. The external user ends at `/portal`. Click probe `web/scripts/probe-aiops.mjs`.
  The agent page's "not answerable yet" note now links to the agent's prompt log, spend and sets.
  **OPEN (defaults taken):** (1) months post only once ended — no mid-month accrual. (2) No
  expense row behind a posting (`expense_id` stays NULL); the credit side is 2000 Accounts
  payable, as the seeded rule says, and paying the provider's invoice is ordinary AP work.
  (3) Posting is per provider × model for the whole business — `department` is refused "not
  available yet" (the unique slice allows it; nothing allocates cost to departments yet).
  (4) Only the base currency posts; other-currency calls are reported and left (no FX, by
  decision). (5) A late or re-priced call in a posted month shows as a reconciliation difference
  — void and re-post to take it in. (6) Accounting "owns token-usage metering" (CLAUDE.md) but
  its dept-admin sees spend only with the `ledger` or `expenses` grant — the views' rule, not
  changed here. (7) An agent's approval pause on `ai_usage_post` / `_void` is called, not proven
  through the door (as every module since Helpdesk). (8) Payload retention is READ here
  ("expired"), not enforced — nothing archives payloads yet. (9) Seen on the way, not this
  module's: 16 older manifest rows still carry a parameter the registry cannot parse.
- [x] **Stub modules — 13. Reports & dashboards (2026-09-20).** Spec: `docs/build-specs/reports.md`.
  **Installed:** `chart.js` 4.5.1 + `react-chartjs-2` 5.3.1 (npm, bundled — the browser loads
  nothing from a CDN). **Migration:** `db/117` — `report_definitions.presentation` (which column
  names a row, which are drawn, which the table shows), appended to `mcp_report_definitions`
  (barrier and grants kept); the five starter reports of db/062 given parameters their tools now
  take, and `receivables` corrected to the tool that exists, `receivables_aging` (only rows
  still exactly as seeded were touched).
  **A report is a tool call, not SQL.** A saved report = a READ tool of the records (or activity)
  MCP server + parameters + how to draw it; there is no SQL editor anywhere. **PHP runs it as
  the VIEWER** through the new `app/mcp_client.php` (streamable HTTP to localhost: initialize →
  tools/call; a tool's or pydantic's error becomes a sentence, never a 500). **Token mechanics:**
  per run — per page for a dashboard — ONE `mcp_access_tokens` row for the viewer, label
  `report-run`, `expires_at` = now + 2 minutes, **deleted in a `finally`**; only its sha256 is
  stored, the raw value lives in one PHP variable and never reaches the browser, a log or an
  answer. Proven: 0 `report-run` rows after the smoke, after the probes, and 1 during a call.
  An agent's run gets the agent's token, so its tool grants apply. **Runs as the viewer, proven:**
  one shared report over `find_tickets` — the owner 3 rows, Sam (given the report's module for
  the test) 1 row, the ticket assigned to him; with the grant revoked, "Report not found".
  **The catalogue** is the server's own `tools/list` (123 read tools), cached five minutes; the
  tool's JSON schema draws the form (choices → select, yes / no, number, text; "ask each time"
  per parameter) and checks what is saved (unknown key, wrong type, bad choice, missing
  required). A tool that answers one record is drawn as a **detail**; an object holding one list
  (a financial statement) is its rows. **Nothing of a result is stored** — `report_runs` keeps
  who / when / params / status / row count / duration / error; no cache; an export files no
  document. **Charts:** bar / line / pie with the table ALWAYS beneath, one number, short list,
  table; 500 rows a screen, 50 points a chart, 5 000 rows a CSV (`/api/download`, formula-safe
  cells). **Dashboards** (`/dashboards`, as the manifest has it — the main `/dashboard` is
  untouched): ≤ 12 tiles (report / first number / first rows / note), half or full width, up /
  down; one MCP session per page, 8 s a tile; a tile the viewer may not run says so in itself —
  seen: Dana gets the P&L tile and three polite refusals on the owner's dashboard.
  **Scheduled delivery mails a LINK, never the data**; recipients are active people of this
  business (an address, an agent and an external customer are each refused);
  `bin/run_report_schedules.php` claims a slot by moving `next_run_at` before sending, writes a
  `report_runs` row and logs `report_schedule.deliver`; `--dry-run` prints who would be mailed
  which link and **writes nothing at all** — the only mode the smoke uses (members 1, 5 and 6
  have real-looking addresses), so **no report mail has ever been sent**. **Agents:** 9 tools
  (`mcp/smoke/20-reports.json`, 60 / 60 with refusals incl. an unknown tool, a WRITE tool named
  as the report's tool, parameters failing the schema); read tools `find_reports`, `run_report`
  (calls the report's own tool inside the records server as the caller — mints nothing; an agent
  must also hold the underlying tool's grant), `report_schedules` (`mcp/business_reports.py`).
  **Checked as four people:** the owner all 16 routes at 1280 and 375; Dana sees only the books
  report, 404 on the rest, may schedule (admin) and arrange a shared dashboard; Sam holds no
  module — empty list, 404s, schedules refused, shared dashboard visible with refusals; the
  external customer lands on `/portal`. Probe `web/scripts/probe-reports.mjs`: form → chart
  canvas + table → re-run by URL → CSV → dashboard tile, at both widths.
  **OPEN (defaults taken):** (1) the cron line for `run_report_schedules.php` is in
  `docs/deploy/crontab.example` and NOT installed (with the other uninstalled lines — owner's
  call); the schedules screen says nothing is being sent. (2) Recipients are insiders only;
  `recipient_emails` is never written. (3) Reports over `prompt_for_request`, `ledger_calls`,
  `payroll_summary`, `pay_runs`, `employment_profile` can be saved and run by whoever could call
  the tool, but not scheduled. (4) PDF export is refused as not available (the tokenised-render
  pattern of Signatures would do it); `format` on a schedule is `html` only. (5) A recipient who
  does not hold the report's module gets a link they cannot open — the form says so; nothing
  checks it. (6) The report's `module` is the saver's choice among modules they hold (a
  suggestion is made from the tool's name); it decides who LISTS the report, never what they see
  in it. (7) No dashboard delete and no "default dashboard" setting (neither is in the
  manifest). (8) `run_report` as a tool writes no `report_runs` row (the records server is
  read-only), so "unused" counts screen and action runs only. (9) `report_schedule_save`'s agent
  approval pause is called but not proven through the agents' door (as the earlier modules).
  (10) The dataviz palette is the nxl theme's hues; no dark-mode pass on the charts.
- [x] **Stub modules — 14. My Work (2026-09-20) — the last of the fourteen.** Spec:
  `docs/build-specs/my-work.md`. **Installed:** nothing. **Migration:** `db/118` —
  `app_my_work(horizon_days, limit)`, **the one gatherer**: a `SECURITY INVOKER` function that
  reads only `mcp_*` views as the caller, each section in its own exception block (a failing
  section is a WARNING and a skipped section, never a broken page), returning typed rows
  `(section, waiting, kind, id, title, detail, due_at, state, href, urgency, total)`. The screen
  (`html/my-work.php` → `my_work_sections()` in `app/features/home/work.php`) and the new tool
  `my_work` (`mcp/business_mywork.py`, running as `app_records_ro`) both call it, so they cannot
  disagree. The one thing SQL cannot do — expanding a repeating appointment for "today and
  tomorrow" — reuses the Calendar: PHP `find_schedule_window()`, Python `occurrences_in_window()`
  (lifted out of the `schedule` tool, which now calls it too; `11-calendar` still 38 / 38).
  `home_work()` and the dashboard are untouched.
  **Sections** (drawn only when they have rows; a module the viewer cannot use never appears):
  *waiting on me* — approvals to decide, open tickets (SLA state, breached first), mail assigned
  to me whose last word came from outside, tasks due within the horizon or overdue, appointments
  I have not answered, time to approve, leave to decide, content to review, form submissions on
  forms assigned to me, overdue invoices I own, my rejected / never-submitted timesheets; *coming
  up, and waiting on others* (shown, not counted) — today's and tomorrow's appointments, my
  pending approval requests, my purchase orders awaiting receipt, signature requests still out,
  my leave, and an agent's duties (the tool adds an agent's monthly budget and what is left).
  The header counts only what waits on the viewer; with nothing waiting it is one calm sentence.
  No actions — nothing was added to the manifest or the registry. **The stub map is empty**
  (`STUB_PATHS` in `web/lib/schemas/modules.ts`): all fourteen modules have their own routes.
  **Checked as four:** the owner — 3 waiting (2 approvals, Sam's leave request) plus 2 purchase
  orders and 1 signature request out; Dana — "Nothing is waiting on you."; Sam — 3 waiting (his
  ticket, a task, an item to review) plus his own leave request; each count agrees with the
  owning module's own tool (`approval_queue`, `leave` view=pending, `find_tickets`,
  `content_pipeline`). Ledger Bot is refused `my_work` at the MCP boundary (no tool grant — it
  has no agent profile to hold one). External member 46 ends at `/portal`.
  `web/scripts/probe-my-work.mjs` at 1280 and 375; `mcp/smoke/21-my-work.md` says why there is
  no JSON scenario.
  **OPEN (defaults taken):** content "sent back for changes" is not a section — a change request
  returns the item to `draft` with its note in the activity trail, so the view cannot tell it
  from a fresh draft; eval alerts have no assignee and are left out; "time to approve" goes to
  every holder of the time module and every admin for the people whose time they can see (there
  is no named timesheet approver in the schema); the catch-all page for an unknown URL still
  says "has not moved to the new front end yet", which stopped being true at the cut-over.
- [x] **The fourteen modules — closing checks (2026-09-20).** One list route per module (25
  routes) as the owner: 50 / 50 `ok` at 1280 and 375. Write paths through the agents' door:
  `1-crm-sales` 33 / 33, `7-approvals` 12 / 12, `10-documents` 27 / 27, `11-calendar` 38 / 38,
  `12-helpdesk` 42 / 42, `14-content` 71 / 71, `15-inventory` 101 / 101, `17-signatures`
  88 / 88, `19-ai-ops` 49 / 49, `20-reports` 60 / 60 (not re-run, on purpose: `16-people` posts
  a real pay run each time, `13-inbox`'s fixture sender is suppressed by MaluMail, `18-portal-
  forms` trips its own rate limit, `2-…books` collides with its own fixed-date fiscal period).
  Every `maludb-os-*` service and both timers are up; `php -l` is clean over the 375 PHP files
  changed since `5c917f2`; `tsc --noEmit` is clean.

- [x] **The company's own logo (2026-09-22, db/134).** A super-admin uploads the logo on Business
  settings (a card of its own, its own action `business_logo_update` → `logo-save.php`), and it
  heads the sidebar of every signed-in screen where the shipped `/assets/images/logo-full.png`
  sits; "Use the standard logo" goes back. The shape of the agent photos: the bytes under the
  storage root as `business/logo/<sha256>.<ext>`, the row (`business_settings.logo_*`) holds the
  facts, the type is read from the bytes (JPEG/PNG/GIF/WebP, 2 MB, no SVG), and the file is
  reachable only through `/settings/business/logo.php` behind the session — the browser gets it
  from the picture relay `/api/avatar`, whose allow-list gained that one address. The session
  payload carries `business.logo_url`, versioned by the upload time so a new logo is a new
  address; the shell falls back to the shipped file when the relay cannot produce it. The mini
  sidebar's abbreviated mark is unchanged. Proven against PHP with a test action token (refusals,
  upload, byte-identical serving, 304, 401 for a stranger, removal); not yet built into the
  running web app — the hosts session (A2) owned the web tree at the time.

## The fourteen modules — what is owed to the owner

Gathered from the fourteen done-notes above (2026-09-19 / 20), one line each. Nothing here
blocks using what was built; each is a default that was taken, a piece left unbuilt, or a limit.

### Needs the owner's decision
- **Cron**: four lines of `docs/deploy/crontab.example` are NOT in www-data's live crontab —
  `bin/grant_annual_leave.php` (People) and `bin/run_report_schedules.php` (Reports), and two
  older ones, recurring expenses and the posting run. Re-installing from the example switches
  all four on. Until then: no yearly leave grant, no scheduled report mail, no unattended posting.
- **Helpdesk**: should being ASSIGNED a ticket carry the right to reply without the tickets
  module? (Today the assignee reads it and cannot work it.) Should the SLA clock pause while a
  ticket waits on the customer? (Today the due times stand and the state reads "paused".)
- **Inbox**: answers to what we send go to `MAIL_FROM`, not to the mailbox — per-mailbox senders
  need MaluMail sender verification and Reply-To; until then poll `MAIL_FROM`'s own mailbox.
  `MAIL_FROM` here is a real address and receives the smoke's bounces.
- **Content**: every item needs a second person's approval unless its author is an admin — is a
  "no review needed" switch wanted for small teams?
- **Inventory**: negative stock is allowed and flagged, never blocked; a partial credit note
  returns no stock; stock always leaves the default location.
- **People**: a manager sees their reports' PAY (db/058's rule, kept) — or employment and leave
  only? Marking a run paid does not post the bank side (which account paid is not recorded);
  only paid runs post, with no accrual at approval.
- **Signatures**: identity is possession of the mailbox the link reached — no SMS code or ID
  check; a file original gets a certificate page carrying its fingerprint, its own pages are not
  re-stamped.
- **Portal**: it is switched ON with a SMOKE welcome message — switch it off on
  `/settings/portal` if unwanted. Recipients of scheduled reports and portal `sections` are
  business-wide / insiders-only by default.
- **AI Ops**: Accounting "owns token-usage metering" but its dept-admin sees no spend without
  the `ledger` or `expenses` grant (the views' rule, unchanged) — grant it, or widen the rule?
  A month posts only once it has ended; a late call in a posted month shows as a difference.
- **Time**: approving locks entries and the only undo is "reject the week"; "time to approve"
  on My Work goes to every time-module holder and admin (no named approver exists).
- **SMOKE data left in place** (none of it deletable through the product by design, all named
  `SMOKE …`): the `SMOKE Keep Support` mailbox, which polls a host that does not exist every two
  minutes and records the failure; the portal switched on; external member 46 `SMOKE Keep
  Portal Customer` sharing company 37; SMOKE pay runs POSTED to August 2026 (6,950 per run —
  a paid run cannot be voided); SMOKE stock postings; locked SMOKE time entries in January 2026
  on the owner's timesheet; SMOKE tickets, mail threads, products, purchase orders, content,
  signature requests, forms, reports and documents. Say whether a clean-up script is wanted
  (it would need rules for the posted ones).

### Needs building
- **`record_share_create` / `record_share_revoke`** (manifest, Team & access) — without them
  nothing can share a document or project with a portal customer; the one test share was SQL.
- **The agents' approval pause, proven through the agents' door.** Every module calls
  `check_approval()` with the manifest's event; none could be smoke-tested as an agent, because
  tool grants are enforced at the MCP boundary and the only seeded agent (Ledger Bot, member 7)
  has no agent profile to hold one. Needs a hired test agent with grants.
- **Notifications**: nothing tells a person their leave was decided, a content slot is due, a
  form was submitted (in-app `system` only), an appointment moved, or a signature completed;
  `email_messages` (the delivery log) is written by nothing, so bounces are invisible.
- **Jobs that do not exist yet**: signature reminders (`reminder_days`) and expiry, purging
  deleted documents after 30 days, prompt-payload retention, content "due to post" nudges.
- **PDFs for customers**: no invoice / quote page or PDF in the portal; report PDF export is
  refused (Signatures' tokenised-render pattern would do both).
- **Smaller gaps**: product income accounts unused until invoice posting splits by line; AI
  usage cannot be allocated to departments; campaign attribution is read but no Contacts / Deals
  form sets it; `business_settings_update` (agents) lacks the default hourly rate; no Documents
  tab on a person (no `member` link target); `birth_date` / `national_id_last4` have no screen;
  no dashboard delete or default dashboard; no mail-rule re-ordering; only IMAP inbound
  (`forward` / `malumail` refused); no uploads on public forms; no image preview for content
  media; ordinary invitation mail still carries cert-study wording; 16 older manifest rows carry
  a parameter the registry cannot parse; `fiscal_period_save` leaks a raw SQLSTATE and makes
  `mcp/smoke/2` collide with itself; the catch-all page's "not moved yet" wording is stale.
- **Provisioning script** does not yet know about: Node + `maludb-os-web`, `maludb-os-pdf`
  (Chromium under `/opt/ms-playwright`), `maludb-os-inbox-poll.{service,timer}`,
  `poppler-utils`, composer's `rlanvin/php-rrule`, `python-dateutil` in the MCP venv, npm's
  `react-markdown` / `remark-gfm` / `chart.js` / `react-chartjs-2`, PHP's 25 MB upload ini, and
  `SECRETS_KEY`.
- **The sync rule is OWED**: the requirements (3 copies) and the build plan (2 copies) say
  nothing yet of the React cut-over or of these fourteen modules. Left for the owner's review —
  not done in this run.

### Known limits (by decision or by the platform)
- MaluMail sends no cc, attachments, Reply-To or threading headers, and suppresses an address
  after one bounce; no real mailbox is connected, so the IMAP leg is proven against a stand-in.
- No statutory payroll, no FX, no bins / lots / serials / BOMs, no outside signature provider,
  no online payment, no eval runner ("no runner yet" is what Run answers), connector publishing
  answers "not connected yet".
- Calendar: no customer notifications; all-day appointments are entered as times; the feed names
  a `TZID` without a `VTIMEZONE`. Leave cannot cross a calendar year. One bill per purchase
  order. A signer's name with a comma or colon cannot go through the agents' flat `signers[]`.
- **Dashboard: a Tasks card — 2026-09-20.** First tile of `#home-counts-row`, full width above the
  2×2 of counts below 1400px and the wide first tile of a single row above it, so it is in the top
  row at every width. `home_counts()` gained `open_tasks`, `new_tasks` (created in the last 24
  hours, still open) and `unassigned_tasks`, read from `mcp_tasks`. The figures link to `/tasks`
  (the agents' tasks have no project, so `/projects` cannot list them); **Projects** is a link in
  the card's corner. Same commit: activation now copies a version's model and budget onto the
  agent's profile (db/119 repaired three), which is what these cards and `mcp_agents` display.
- **Company Profile — built 2026-09-20** (`docs/build-specs/company-profile.md`; not one of the fourteen — a new slice
  the owner asked for and approved the same day). `/company` for every insider (story, facts, contact, social links,
  logo, hero, the cards of what the business offers — catalog items, inventory products or free-form showcase cards);
  `/company/edit` and `/company/items/…` for a super-admin; identity stays in `business_settings`, whose address,
  email, phone and website this is the first screen to edit. Published, it is one versioned JSON document behind a
  bearer token (`/api/v1/company-profile` + `-media`) — the source a display website is built from — and the
  `company_profile` MCP tool. db/120. Smoke 39/39 through the agents' door, a browser probe of the React write path
  with files, the feed before/after publishing, three members + an External. The two API paths are on the live Apache allow-list (owner, 2026-09-20; reloaded and checked on the public port:
  401 without a token, `404 not_published` with one). **Deferred by the owner:** replacing the sample words and test pictures
  and publishing; minting the website builder's API token.
- **Dashboard top row — 2026-09-20 (owner's request).** The Tasks card is now an ordinary tile (`col-6`, `col-xxl-2`;
  "open" and "new · 24h", the unassigned count moved to the figure's tooltip) and an **Approvals** tile sits beside it:
  the requests still pending, unexpired and waiting for the viewer's own decision — exactly what `/approvals` opens
  to, which is where the whole tile links — with "N with others" when `mcp_approval_requests` shows them more.
  `home_counts()` gained `pending_approvals` and `pending_approvals_others`. Six equal tiles on a large screen, 2×3 below.
- **Deals board: a deal moved to Won or Lost vanished — fixed 2026-09-20 (owner's report).** The board drew a column
  for every stage, Won and Lost included, but `find_deals_board()` loaded only `closed_at IS NULL` — and moving a deal
  into a won/lost stage is what closes it, so it left the very column it was dropped in (both columns had always
  been empty: 6 won and 2 lost deals were on no screen). The board now passes `DEALS_BOARD_CLOSED_DAYS` (30): Won and
  Lost show deals closed in that window, newest first, with "closed MM-DD" on the card and a line saying what window
  it is and how many older ones are not shown. Other callers (the interaction form's deal picker) still get open
  deals only; "Gone quiet" never includes a closed deal. Moving a card back to an open stage reopens it, as before.

