# Build spec: Public JSON API v1 — the AI Agent View org graph

2026-09-18 · new surface, requested for the APEX-UI React front end · planning-class spec

**This is the platform's first browser-facing JSON API.** Until now there are two surfaces: HTMX
screens behind PHP sessions, and three MCP servers behind bearer/action tokens. Neither serves a
separately-hosted SPA. So this slice is not "add some endpoints" — it establishes an API surface,
its auth, its CORS policy and its error shape, and the first thing it serves is the org graph.

Consumer: **APEX-UI** (`https://github.com/RubenM1990/APEX-UI`) — Next.js 15, React 19,
TypeScript, three.js / react-three-fiber. Its `ReasoningWeb` component already renders an "agent
constellation", which is the view this feeds. The design is `AI Agent View`
(`https://images.skilliks.ai/APEX-UI.png`): a centre node, department nodes fanning out, member
nodes beyond them, and a left panel carrying **people / teams / levels** counts, a search box, a
per-team filter list with counts, and a connections toggle.

## Decisions taken before this spec (2026-09-18)

| Decision | Chosen |
| --- | --- |
| Transport and auth | **A new REST API with bearer tokens** under `/api/v1/`, CORS-configured — not MCP reuse, not a shared session cookie |
| Centre of the graph | **The signed-in human.** "Your organisation, from where you sit" |
| What the graph contains | **Humans and agents, agents marked** — three levels: centre → departments → members |
| Liveness | **Static fetch, refresh on demand.** The motion is decorative; the org changes rarely |

Two smaller ones taken here rather than asked, because they are configuration and scope rather
than product:

- **CORS origins are configuration**, not code: a new `API_CORS_ORIGINS` in `config/.env`
  (comma-separated). Nothing is hard-coded, and no origin is allowed by default.
- **v1 is read-only.** The view only reads. A write API is a much larger security surface and
  nothing in this design needs one; `GET` and `OPTIONS` are the only methods.

## The rule that does most of the work

**The API sets the member context and lets the existing `mcp_*` views do the filtering.**

Every endpoint resolves its bearer token to a member, sets `app.member_id`, and then reads the
same views the screens and the agents read. That means the graph a caller receives is already
exactly what that person may see — no second visibility implementation, and no chance of the API
disagreeing with the screens. This project has found that disagreement seven times; the API must
not become the eighth.

Concretely: read `mcp_departments`, `mcp_department_members`, `mcp_agents`, `mcp_team_directory`.
**Never a base table, ever** — and note `app_records_ro` is not the role here (the API runs as
`app_rw` like the rest of PHP), so a base-table read would *work* and silently over-disclose,
which is worse than failing.

## Auth

**Revised 2026-09-18, after the decision to build the front end here.** agentview is a Next.js
app on this same box at `/var/www/agentview`, served on :3000 behind `agentview.subello.com`.
The **browser never calls this API**: it talks only to agentview, and agentview's *server* calls
`http://localhost/api/v1/…` forwarding the caller's session cookie. That removes CORS, keeps any
token out of JavaScript, and needs no `Allow-Credentials`.

So the API accepts **two** credentials, in this order:

1. **A PHP session** — `session_start()` has already resolved a member. This is the agentview
   path, and the reason it is safe is that the call is server-to-server on localhost. Only `GET`
   exists in v1, so there is no CSRF surface.
2. `Authorization: Bearer <token>` — for any other client (a script, a second front end, a
   future mobile app).

**`SESSION_COOKIE_DOMAIN` becomes a config key** (`config/.env`, empty by default). Empty keeps
today's host-only cookie, which is what localhost testing depends on; set to `.subello.com` in
production so one login covers both hosts. `app/bootstrap.php` applies it **only when the
request's host actually ends with that domain**, so a value set for production cannot silently
break a `localhost` session. Widening the cookie means every `*.subello.com` host becomes
trusted with it — a deliberate trade, recorded here so it is not rediscovered later.

- `Authorization: Bearer <token>` against `mcp_access_tokens`, which already holds
  `member_id`, `token_hash`, `expires_at`, `revoked_at` and `last_used_at`.
- **`db/078` adds `mcp_access_tokens.scope`** — `'mcp'` | `'api'`, NOT NULL, existing rows
  backfilled to `'mcp'`. An MCP token must not authenticate the API and an API token must not
  authenticate the MCP servers: they are different surfaces with different blast radii, and one
  revocation should not have to mean both. `bin/mint_mcp_token.php` gains `--scope`.
- A missing, malformed, expired, revoked or wrong-scope token is **401** with the same body in
  every case — never "no such token" versus "expired", which is an enumeration oracle.
- `last_used_at` is stamped on each successful call, as the MCP servers already do.

## CORS

**agentview does not need CORS at all** — its server does the fetching. This section exists for
any *other* browser client, and remains off unless an origin is configured.

- Allowed origins come from `API_CORS_ORIGINS`; an origin not on the list gets no CORS headers
  at all (the browser then refuses it) and the request is still answered normally for non-browser
  callers.
- `OPTIONS` preflight answers 204 with `Access-Control-Allow-Methods: GET, OPTIONS`,
  `Access-Control-Allow-Headers: Authorization, Content-Type`, and `Vary: Origin`.
- **No `Access-Control-Allow-Credentials`** — this API is token-authenticated and must never be
  reachable by a browser's ambient session cookie, which is what would make it CSRF-able.

## Endpoints

All responses are `application/json; charset=utf-8`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | liveness; **no auth**, returns `{"status":"ok","time":...}` and nothing about the business |
| GET | `/api/v1/me` | the signed-in member: id, name, title, kind, departments |
| GET | `/api/v1/org-graph` | the whole AI Agent View payload |
| GET | `/api/v1/members/{id}` | one node's detail, for "select a node to explore" |

`/api/v1/org-graph` takes one optional parameter, `include_retired` (default false). It takes no
root parameter in v1: the centre is the caller.

### `GET /api/v1/org-graph`

One call returns everything the view needs — the constellation and the left panel — because two
calls would let the counts disagree with the graph.

```json
{
  "generated_at": "2026-09-18T20:14:03+00:00",
  "centre": { "id": "member:1", "member_id": 1, "name": "Edward Honour",
              "title": "Founder", "member_kind": "human",
              "avatar_url": "/assets/img/avatars/avatar-01.svg" },
  "summary": { "people": 4, "agents": 1, "teams": 5, "levels": 3 },
  "teams": [ { "department_id": 3, "name": "Accounting", "member_count": 3, "agent_count": 1 } ],
  "nodes": [
    { "id": "member:1", "type": "member", "level": 0, "name": "Edward Honour",
      "title": "Founder", "member_kind": "human", "is_centre": true,
      "avatar_url": "/assets/img/avatars/avatar-01.svg" },
    { "id": "department:3", "type": "department", "level": 1, "name": "Accounting",
      "parent_department_id": 4, "manager": { "id": "member:5", "name": "Dana Reyes" },
      "member_count": 3, "agent_count": 1 },
    { "id": "member:7", "type": "member", "level": 2, "name": "Ledger Bot",
      "title": "Bookkeeping agent", "member_kind": "agent",
      "avatar_url": "/agents/photo.php?agent=7",
      "agent": { "status": "active", "agent_kind": "subagent", "role_key": "bookkeeper",
                 "manager_member_id": 5, "is_office_manager": false } }
  ],
  "edges": [
    { "source": "member:1", "target": "department:3", "kind": "centre_of" },
    { "source": "department:3", "target": "member:7", "kind": "has_member" }
  ]
}
```

Fixed rules for the payload:

- **Node ids are prefixed** (`member:7`, `department:3`) so the front end can key a mixed graph
  without collisions. The raw id is also present as `member_id` / `department_id`.
- **`level`** is 0 for the centre, 1 for departments, 2 for members — the "03 LEVELS" the panel
  shows. Do not compute levels from edges in the client.
- **`member_kind`** is on every member node. This is what lets APEX style agents differently, and
  it is the whole reason the view is called the AI Agent View.
- **`agent`** is present only on agent nodes, carrying what `mcp_agents` exposes. Never a budget
  figure: `mcp_agents` masks `monthly_budget_amount` behind `app_can_see_agent()`, so pass
  through whatever the view returns and never reconstruct it.
- **The centre appears once**, as a node with `is_centre`, and also in `centre` for convenience.
- **A department the caller cannot see is absent entirely** — node and edges — because the view
  returns no row for it. Do not emit a placeholder.
- **`avatar_url` is never null** (2026-09-18). It resolves in that order: an agent's uploaded
  photo (`db/090` — `/agents/photo.php?agent=N`, exposed as `profile_pic_url` on `mcp_agents`),
  else `default_avatar_url(member_id)` from `db/079`, a deterministic pick out of the twelve
  shipped SVGs at `/assets/img/avatars/`. Humans take the same fallback, which matters because a
  human is the centre node. Read it from the view — **do not rebuild this precedence in PHP**,
  and never invent a gravatar URL. `agent_profiles.profile_pic_url` no longer exists; `db/090`
  replaced it with stored-file columns and a derived URL.
- **Empty is legitimate.** A member in no department gets a graph of one node, themselves. Say so
  with real values rather than a 404.

### `GET /api/v1/members?id={id}`

**Corrected 2026-09-18.** This spec claimed the installed rewrite rules already served
`/api/v1/members/{id}` — "verified, unlike two earlier specs that claimed it and were wrong".
That claim was itself wrong, and is now the *third* spec in this project to make it: none of the
five rules matches a bare `/api/v1/members/7`, and Apache 404s it before PHP runs. The canonical
call is `/api/v1/members?id={id}`. The endpoint also reads `PATH_INFO`, so adding a rewrite
later needs no code change. **The lesson, since claiming it verified did not make it so: curl the
URL.**


The node detail: the member, their departments, their manager, and for an agent its model,
status, role, `agent_kind` and — if an orchestrator — its roster from `mcp_agent_subagents`.

**`agent_kind` has three values, not two** (`db/091`, 2026-09-18): `orchestrator`, `subagent`
and **`voice`** — an agent that answers inbound calls, which employs nobody and is employed by
nobody, so it sits outside the delegation tree entirely. Read the value through; never
enumerate it as a pair, and never infer "subagent" from "not an orchestrator". A voice agent is
an ordinary department member in the graph, at level 2, marked by its kind like any other. **404 when the caller cannot see that member**, never 403: the same rule
the screens use, so the API does not become an existence oracle the UI is not.

## Errors

One shape everywhere, so the client has one branch:

```json
{ "error": { "code": "unauthorized", "message": "A valid API token is required." } }
```

`400 bad_request` · `401 unauthorized` · `404 not_found` · `405 method_not_allowed` ·
`500 server_error`. **No exception text, no SQL, no stack** — the screens already route those to
`error_log()` and this must too.

## Files (exactly these — no additions)

```
html/api/v1/health.php · me.php · org-graph.php · members.php

app/api/bootstrap.php     (token auth, member context, CORS, JSON helpers, the error shape)
app/features/orgchart/queries.php   (the graph: nodes, edges, summary, teams)

bin/mint_mcp_token.php    (gains --scope, defaulting to mcp)
db/078_api_token_scope.sql
```

`html/api/v1/members.php` serves `/api/v1/members/{id}`: the installed rewrite rules already map
a trailing numeric segment, and `^/(.+?)/?$ → /$1.php` already serves the three-segment paths, so
**no Apache change is needed** — verified, unlike two earlier specs that claimed it and were
wrong.

## Query functions (signatures fixed)

```php
// app/api/bootstrap.php
api_authenticate(): array            // resolves the bearer token -> member row, or 401s
api_cors(): void                     // Vary: Origin, allow-list, OPTIONS short-circuit
api_json(array $payload, int $status = 200): never
api_error(string $code, string $message, int $status): never

// app/features/orgchart/queries.php
org_graph(PDO $pdo, int $centreMemberId, bool $includeRetired): array
    // returns ['centre'=>..,'summary'=>..,'teams'=>..,'nodes'=>..,'edges'=>..]
member_node_detail(PDO $pdo, int $memberId): ?array
```

## Activity logging

Every API call writes `log_activity()` with `source => 'api'` — the column's CHECK already allows
`web|assistant|mcp|cron`, so **`db/078` adds `'api'` to it**. Screen views log
`api.org_graph.read` and the like rather than `screen.view`: an API read is not a screen view,
and conflating them would corrupt the activity memory that answers "who looked at what".

## The API returns structure, never positions

Decided 2026-09-18. The proof of concept hand-authored `x`/`y` for thirteen fictional people;
live data cannot. **agentview computes the radial layout in the front end** — departments spaced
around the centre, members fanned on their department's arc, on the ring radii the handoff fixes
(146, 156, 194, 205, 254). The API therefore returns nodes, edges and levels and **no
coordinates at all**: position is a presentation concern, and a second consumer should not
inherit a layout tuned for this one view. Adding a department must not require a backend change.

## Out of scope for v1

- **Any write.** GET and OPTIONS only.
- **Rate limiting** — noted, not built. Worth adding before this is exposed beyond a known origin.
- **Pagination** — the org graph is small by nature (a business with 10,000 members is a
  different design problem). Return the whole graph; revisit if a tenant ever needs otherwise.
- **The orchestrator→subagent fourth level** — `db/072`'s rosters appear in `members/{id}`
  detail but not as graph edges, because the mock's layout is three levels. (A `voice` agent has
  no roster either way — it is outside the delegation tree.) Adding a level later
  is an additive change to `nodes`/`edges`, not a new shape.
- Websockets/SSE, avatars for humans, and anything the front end can compute itself.

## Acceptance (the demo this slice owes)

1. `GET /api/v1/health` with no token returns 200 and discloses nothing about the business.
2. No token / malformed / expired / revoked / an **`mcp`-scoped token** each return **401 with
   an identical body**.
3. A valid `api` token returns `/api/v1/me` for its own member.
4. `/api/v1/org-graph` as the super-admin returns the full org: 5 departments, 5 members,
   `summary.levels = 3`, every agent node carrying `member_kind: "agent"`.
5. **The same call as `sam.okafor` returns the SAME organisation**, differing only at the
   centre — because the whole org is visible to anyone who works here (owner's decision
   2026-09-18; question H1's audience is *all*, and the views are insider-open by design). This
   criterion originally demanded a *smaller* graph, which was wrong and caused the first build
   to invent a scoping rule the API had no business owning. Counts may still differ where a
   member belongs to no department: the centre is always present, everyone else arrives through
   a department.
6. `/api/v1/members/{id}` returns detail for a visible member and **404 for one the caller
   cannot see**, with the same body as any other 404.
7. A browser preflight from an allowed origin gets the CORS headers; one from an unlisted origin
   gets none.
8. Every call appears in `activity_log` with `source = 'api'`.
9. The payload renders: hand it to APEX-UI's `ReasoningWeb` shape, or failing that assert the
   contract in a fixture — centre at level 0, departments at 1, members at 2, every edge
   referencing node ids that exist.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none) — the four design decisions were taken with the owner on 2026-09-18; CORS origins and
  read-only scope were decided here as configuration and scope rather than product.

- **2026-09-18, worker escalation (substitution made, not a decision — flagging for review):**
  "Concretely: read mcp_departments, mcp_department_members, mcp_agents, mcp_team_directory
  ... that means the graph a caller receives is already exactly what that person may see"
  does not hold as written. All four views are gated on `app_is_insider()` alone (verified via
  `pg_get_viewdef`) — identical for every non-external logged-in member regardless of role or
  department. Reading them unfiltered would give `sam.okafor` (a plain `user`, no admin
  departments) the exact same node/edge set as the super-admin, failing acceptance #5
  ("a genuinely smaller graph"). Substitution: `org_graph()` scopes *which departments* enter
  the graph to `app_admin_department_ids() ∪ app_my_department_ids()` — the platform's own,
  already-audited department-visibility functions (the same ones `app/business.php`'s
  `admin_department_ids()`/`my_department_ids()` wrap for the screens), not a new rule invented
  here. This reproduces the spec's own worked numbers exactly (super-admin: 5 departments, 5
  members incl. centre, summary `{people:4, agents:1}`; a plain department member: 1
  department, a visibly smaller graph), so it is very likely the intended mechanism, but the
  spec never names it — please confirm or correct. See `app/features/orgchart/queries.php`'s
  file docblock for the same note in code.

- **2026-09-18, worker escalation (substitution made, not a decision):** "`html/api/v1/members.php`
  serves `/api/v1/members/{id}` ... no Apache change is needed — verified, unlike two earlier
  specs that claimed it and were wrong" is itself wrong, re-verified against the access log:
  none of the five installed RewriteRules in `/etc/apache2/sites-enabled/000-default.conf`
  match `/api/v1/members/7` (Apache answers its own 404 HTML page before PHP ever runs).
  Apache config is out of this slice's scope either way. Substitution, precedented by the
  bookkeeping-ledger slice's own `?bank_account={id}` fix for the same class of gap: the
  canonical call is **`/api/v1/members.php?id={id}`** (also reachable as
  `/api/v1/members?id={id}`, matched by the existing generic `.php` rule). `members.php` still
  reads `PATH_INFO`/the trailing segment too, so it needs no further change if a future Apache
  rule is added for the `{id}` segment.
