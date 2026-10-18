# Build spec: the focused Agent View — `/api/v1/graph` and `/view/<kind>/<id>` (migration step R5)

2026-09-19 · **BUILT 2026-09-19** on the owner's go, after the owner answered the three open
questions (see the end). "As built" at the bottom records where the build says more than the spec.
Read `docs/react-migration-plan.md` ("Agent View integration") and
`docs/build-specs/public-api-org-graph.md` first: this spec generalises that API and inherits
every rule it does not restate (auth, CORS, errors, "the API returns structure, never
positions", reads from `mcp_*` views only, the caller's own visibility decides every row).

## What already exists (do not rebuild)

- `/` is the Agent View of the organisation from where the signed-in person sits:
  `GET /api/v1/org-graph` → `web/lib/org-graph.ts` → `components/AgentView.tsx`.
- Done 2026-09-19 (R5, the two parts that needed no new API): the header's **Goto Human View**
  is a link to `/dashboard` in the live workspace, and every node's **profile panel links to
  its day-to-day screen** — an agent to `/agents/{id}`, a person to `/team/{id}`, a department
  to `/team/departments/{id}`.

## What this spec adds

1. `GET /api/v1/graph?focus=<kind>:<id>` — the same payload shape as `org-graph`, centred on a
   record instead of a person. **Session-only** (owner's decision 3): it answers this app's own
   server carrying a signed-in person's session cookie, like `/api/v1/session` — no bearer
   token, no CORS, no public contract yet.
2. `/view/<kind>/<id>` — a full page (never a modal) that renders that payload with the existing
   `AgentView` component.
3. `AgentViewButton` on the five screens the owner chose (2026-09-18): department, agent,
   project, location, organization.

## The rule that does most of the work

**A focused graph shows exactly what the focus record's own React screen already shows that
viewer, as a picture — never more.** Every ring below is a list that screen already renders,
read with the query function that screen already uses. So there is no new visibility decision
anywhere in this slice: if a member cannot see a project's customer on `/projects/6`, the
customer is not in `/view/project/6` either, and db/080's masking arrives already applied.

## Focus kinds, and what orbits each

| `focus` | Centre (level 0) | Level 1 (groups) | Level 2 (members of each group) | Source — the functions the screen already calls |
| --- | --- | --- | --- | --- |
| `department:<id>` | the department | **People**, **Agents**, **Sub-departments** | its members; its agents; its child departments | `find_department()`, `department_members()`, `find_departments()` |
| `agent:<member id>` | the agent | **Roster** (or **Orchestrators** for a subagent), **Tools**, **Duties** | roster agents; tool grants (application — endpoint — tool); duties | `find_agent()`, `find_agent_roster()` / `find_agent_orchestrators()`, `find_agent_tool_grants()`, `find_agent_duties()` |
| `project:<id>` | the project | **Team**, **Milestones**, **Blocked** | project members (people and agents); milestones; blocked tasks | `find_project()`, `find_project_members()`, `find_milestones()`, `project_blockers()` |
| `location:<id>` | the location | **Residents**, **Departments**, **Applications**, **Inside** | who works there; departments that call it home; applications that run there; child locations | the location page's own reads (estate feature) |
| `organization:<id>` | the company | **People**, **Deals** | its contacts; its deals (stage + `money()` display string) | `find_organization()`, `find_people_for_organization()`, `find_deals_for()` |

Caps: at most **40** level-2 nodes per group and **200** nodes per graph; a group that was cut
carries `truncated: true` and its true `member_count`, so the picture never implies it is
complete. A voice agent has no Roster group (db/091).

## Payload

The `org-graph` shape, with three additive changes. Existing clients of `org-graph` are
unaffected — that endpoint does not change.

```jsonc
{
  "generated_at": "2026-09-19T12:00:00Z",
  "focus": { "kind": "project", "id": 6 },
  "centre": { "id": "project:6", "name": "Riverside Depot Fit-out", "title": "P-00001 · Active", "href": "/projects/6" },
  "summary": { "groups": 3, "nodes": 11 },
  "nodes": [
    { "id": "project:6", "type": "project", "level": 0, "name": "…", "title": "…", "href": "/projects/6", "is_centre": true },
    { "id": "group:team", "type": "group", "level": 1, "name": "Team", "member_count": 2, "truncated": false },
    { "id": "member:6", "type": "member", "level": 2, "name": "Sam Okafor", "title": "contributor",
      "member_kind": "human", "avatar_url": "…", "href": "/team/6" }
  ],
  "edges": [ { "source": "project:6", "target": "group:team", "kind": "centre_of" },
             { "source": "group:team", "target": "member:6", "kind": "has_member" } ]
}
```

- `type` gains `group`, `project`, `task`, `milestone`, `location`, `application`,
  `organization`, `contact`, `deal`, `tool`, `duty` beside `member` and `department`.
- Every node that has a traditional screen carries **`href`** — the React path, computed in PHP
  (the one place that knows the canonical URLs). A node without a screen (a tool grant, a duty)
  has `href: null`. A masked node (a blocking task the viewer cannot see) is **omitted**, as the
  screen shows only "a task you cannot see" for it.
- `title` is the one line the screen prints under the name (role, stage + amount, due date).

Whitelisted by presenter functions in `app/features/orgchart/present.php` — the migration's
presenter rules apply: named keys only, ids as ints, money as `money()` strings.

## Files (exactly these)

| File | What |
| --- | --- |
| `html/api/v1/graph.php` | the endpoint: session only (`require_login()` — **not** `api_authenticate()`, no `api_cors()`), parse `focus`, dispatch, `log_screen_view($pdo, 'agent-view-focus')` with the focus record as the entity |
| `app/features/orgchart/focus.php` | `focus_graph(PDO, string $kind, int $id): ?array` and one builder per kind; **calls existing query functions only** |
| `app/features/orgchart/present.php` | node / edge / group presenters, `href` builder |
| `web/lib/focus-graph.ts` | server-side loader (forwards the session cookie, as `org-graph.ts` does) |
| `web/app/(agentview)/view/[kind]/[id]/page.tsx` | the full page; 404 for an unknown kind or a record the API answers 404 for |
| `web/components/AgentView.tsx`, `web/lib/layout.ts`, `web/lib/types.ts`, `ProfilePanel.tsx` | accept the wider `type`; a `group` node lays out where a department does; the panel shows `title` + the `href` link and skips the member-detail fetch for non-members |
| `web/components/kit/AgentViewButton.tsx` | a `<Link>` to `/view/<kind>/<id>` in the page header; added to the five screens |

No migration. No new `mcp_*` view. No new MCP tool (agents already have the underlying reads).

## Errors

`401` (no session), `400 bad_focus` (malformed, unknown kind), `404 not_found` (the record does
not exist **or the caller may not see it** — indistinguishable on purpose).

## Activity logging

**One `screen.view` per open, like every other screen** (owner's decision 2): screen
`agent-view-focus`, entity = the focus record. Because the endpoint is session-only, every
caller is this app's own server, so it uses `log_screen_view()` — which in JSON mode already
logs only when the Next.js server marks a real page render (`X-Screen-View: 1`) and therefore
honours the quiet cookie. The web loader reads through `apiGet(path, { screenView: !quiet })`,
as `renderScreen()` does. A person looking at a picture of their project no longer reads in the
audit trail as an integration pulling it. The home view's `api.org_graph.read` row is **not**
changed by this slice (the owner chose not to widen it); `org-graph` stays a public API.
If the focused graph is ever made public, token-authenticated calls log `api.graph.read`.

## Acceptance (the demo this slice owes)

1. `/view/project/6` as the owner shows Team (2), Milestones (2) and Blocked (1); every node's
   panel opens the right traditional screen.
2. `/view/project/7` as Sam Okafor is a 404 — he cannot open that project. `/view/project/6`
   as Sam shows no customer node (he has no contacts reach).
3. `/view/agent/<voice agent>` has no Roster group.
4. A department with more than 40 members shows 40, `truncated: true`, and the real count.
5. The five screens carry the button; `/` is unchanged; `org-graph`'s payload is byte-identical
   to before.

## Open questions — all three answered by the owner, 2026-09-19

**Answers:** (1) a project's rings are **Team, Milestones, Blocked** — the table above; the other
kinds as tabled. (2) An open is logged as **one screen view**, honouring the quiet cookie — not
an API read. (3) **Session-only for now**; promoted to a public, versioned API later, when a
client asks to draw their own (the auth call plus a spec). The questions as they were put:

1. **The rings.** Are the groups in the table the right ones for each kind? (The plan's own
   sketch said: agent → roster, applications, tools; project → members, tasks, agents;
   organization → people, deals. This spec proposes Milestones + Blocked instead of every task —
   a project with 80 tasks is not a readable orbit — and folds "agents" into Team, where the
   project page already lists them with a kind badge.)
2. **Logging.** Should a focused view write an `api.graph.read` activity row per open, as the
   home view does, or should reads made by this app's own server on a person's behalf be marked
   and treated like screen views (one `screen.view`, honouring the quiet cookie)?
3. **Public API or internal?** `org-graph` is a public, token-authenticated API with CORS.
   Should `/api/v1/graph` be public too (clients' own tools can draw a project), or
   session-only like `/api/v1/session` until somebody asks for it?

## As built (2026-09-19)

Everything above, in the files listed. What the build adds to the spec:

- **Each builder applies its screen's gate, not only its screen's reads** — department: admin;
  agent and location: insider; project: signed in (`find_project()` is the row rule);
  organization: `mod:contacts`. A refused gate answers the same 404 as a missing record.
- **Rows that are people or agents get their name, kind, job title and picture from
  `orgchart_member_identities()`** — the read the home view already makes — with the screen's own
  line (project role, "Department admin", "Office manager", an agent's role key) as `title`
  when there is one. No SQL exists in `focus.php`.
- **Inside** (a location's child locations) is `find_locations()` — the estate list's own read —
  filtered to the parent; its `total_count` is the ring's true size.
- **The web side adapts rather than widens.** `web/lib/focus-graph.ts` turns the payload into the
  shape `AgentView` already draws (a ring becomes a department-typed node, a record a
  member-typed node, ids are positions) and carries what each node really is in `node.focus`.
  `/`'s code path is untouched; `org-graph`'s PHP was not edited.
- **A layout of its own** (`computeLayout(..., { weighted: true })`): rings are not peers the way
  departments are (a location has 1 desk inside it and 25 applications), so a ring's sector is
  sized by what it holds, a ring of more than 5 alternates between rows and drops the sub-line,
  and a ring's label sits on the inward side of its node where no record can land.
- **Header**: "Goto Human View" opens the record's own screen; "Organisation" goes to `/`.
- **Logging**: written out in `graph.php` (`screen.view`, screen `agent-view-focus`, entity = the
  focus record, only with `X-Screen-View: 1`) because `log_screen_view()` carries no entity.
  Opening a person's or agent's profile panel still calls `/api/v1/members`, which logs
  `api.members.read` exactly as it does on the home view — unchanged, by the owner's decision
  not to widen question 2.
- **Acceptance**: 1, 2 and 5 demonstrated on live data; 4 (the 40 / 200 caps) on synthetic nodes
  through `focus_assemble()`, since no ring here holds 40; 3 (voice agent) by code only — the
  tenant has no voice agent yet.
