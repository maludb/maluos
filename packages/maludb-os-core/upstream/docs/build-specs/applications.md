# Build spec: Applications slice (the technical asset registry)

2026-09-18 · **pulled forward** from phase 4 at the owner's request · planning-class spec
Third of the "setup first" group, after Estate and Agent HR.

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`). **Read the "Review
findings" sections of `expenses.md`, `bookkeeping-ledger.md`, `estate.md` and `agent-hr.md`
before starting** — between them they record a dozen defects found in review, and this slice can
repeat most of them.

Module grant: `applications` · Manifest section: **Applications**
Schema tables (never modify): `applications`, `application_endpoints`, `application_access`
(`db/055_estate_applications.sql`, extended by `db/075`).
Read views: `mcp_applications`, `mcp_application_endpoints`, `mcp_application_access`,
`mcp_my_applications`, plus `mcp_locations`, `mcp_departments`, `mcp_recurring_expenses`.
Questions this slice must answer: **AC1–AC5** (AC6 is `access_changes`, already built).

## Why this slice matters more than its size suggests

`db/075` made this registry the single source of truth for **every MCP server an agent can
use** — ours and anyone else's. `agent_tool_grants.application_endpoint_id` points here. So:

- Registering an asset and its MCP endpoint is now what makes new agent capability possible.
  Without these screens, adding a data lake means writing SQL by hand.
- An endpoint marked `agent_reachable` with `kind = 'mcp'` and `status = 'active'` is
  immediately offerable in the agent tool-grant picker. **A careless edit here silently changes
  what agents can be granted**, which is why every change is logged and why retiring an endpoint
  must say what depends on it.

## What already exists (do not re-seed, do not migrate)

- **25 applications**: the 23 built-in modules (`is_builtin = true`, each carrying the `module`
  grant it maps to), plus **PostgreSQL 17** and **MaluDB memory**, registered by `db/075`.
- **5 endpoints**: Records / Activity / Actions MCP on the `platform` application
  (`agent_reachable`), and the Postgres and MaluDB endpoints (not agent-reachable — an agent
  asks an MCP server, it does not open a database connection).
- **0 access grants.** `application_access` has never been written to.
- `mcp_applications` already derives **`i_can_use`**; do not recompute it.

## Gate and visibility

Checked 2026-09-18 so you do not have to guess:

- `mcp_applications` and `mcp_application_endpoints` are gated on **`app_is_insider()`**, and the
  tool surface gives `find_applications` / `get_application` the `insider` gate. So this module
  takes the Estate shape: **GET screens use `require_insider()`; every write uses
  `require_module_grant('applications')`.**
- `mcp_application_access` is gated more tightly in SQL — insider **and** (applications grant
  **or** super-admin **or** the row is your own grant **or** it belongs to a department you are
  in). **Do not re-implement that in PHP.** Read the view and show what comes back; the access
  tab for someone without the grant legitimately shows only their own row.
- `application_access_grant` / `_revoke` are `mod:applications, admin` — **a comma means OR**.
- `application_health_check` is `insider`: anyone who works here may ask whether a thing is up.

## Secrets: the reference exists, the store does not

`application_endpoints.secret_id` references `tenant_secrets`, which **has no writer yet** — the
Stripe slice builds it (AES-256-GCM, `SECRETS_KEY`). So:

- The endpoint form collects `auth_kind` and notes, and **leaves `secret_id` NULL**, with a line
  saying credentials attach once the secret store exists.
- `mcp_application_endpoints` exposes **`has_credential`**, a boolean — never a value. Show that.
- **No screen, view, tool, log row or error message may ever carry a secret value.** The
  manifest says so and it is the one rule in this slice with no exceptions.

## Health checks

`application_health_check` runs a check now and writes `health_status` + `last_health_check_at`.

- Checkable kinds: `mcp`, `http_api`, `ui` — a short-timeout (3s) HTTP request to the endpoint's
  `url`, following no redirects. `up` on a 2xx/3xx or on a 401/403 (reachable and asking for
  auth **is** up), `down` on a connection failure or 5xx, `degraded` on a timeout.
- Not checkable from here: `database`, `filesystem`, `smtp`, `imap`, `ssh`, `webhook`. Report
  "not checkable from the platform" rather than guessing — a `database` endpoint reported `up`
  because nobody checked is exactly the kind of false fact this project keeps removing.
- An application's health is the **worst** of its checkable endpoints, and `unknown` when it has
  none. Never invent `up`.
- Checks run on demand only in this slice. The scheduled checker is a cron job the manifest
  lists under "written by the system"; note it and leave it.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `applications-list` | `/applications/` | what we run and where | `category`, `department`, `location`, `health`, `gaps` |
| `application-add` | `/applications/new` | register an application | `category`, `location`, `department` |
| `application-view` | `/applications/{id}` | one application: office, owner, endpoints, access, cost, health | `tab` |
| `application-edit` | `/applications/{id}/edit` | edit details, office, owner or cost link | — |
| `application-endpoint-add` | `/applications/endpoints/new?application={id}` | add an endpoint | — |
| `application-endpoint-edit` | `/applications/endpoints/{id}/edit` | edit an endpoint | — |
| `application-access` | `/applications/{id}/access` | who may use it, at what capability | — |

**Two URL corrections this slice makes to the manifest**, in the same commit, because no
installed rewrite rule serves a three-segment path with the id in the middle — the mistake the
ledger slice made and the estate slice repeated:
`application-endpoint-add` → `/applications/endpoints/new?application={id}` (was
`/applications/{id}/endpoints/new`), and `application-access` →
`/applications/access?application={id}` (was `/applications/{id}/access`).

## `applications-list`

Columns: Name (link) · Category · Owner department · Location · Criticality · Status ·
Health badge (+ "checked 3d ago", or "never checked") · Endpoints (count, with a marker when any
is agent-reachable MCP) · Monthly cost where a `recurring_expense_id` is linked.

Filters `category`, `department`, `location`, `health`, and **`gaps=1`** — AC4, the one that
earns its place: no owner department, **or** no health check in 30 days, **or** an endpoint
whose `auth_kind` is not `none` and has no credential. Show which gap each row has, not just
that it has one.

Sort allowlist `name`, `category`, `criticality`, `health_status` (default `name`). Page size 25.
Built-in modules are included but rendered quietly (a `builtin` badge) — they are real
applications and hiding them would make the inventory a lie, but nobody needs to act on them.

## `application-view` tabs

`overview` (default) · `endpoints` · `access` · `cost`.

- **Overview** — category, description, vendor, self-hosted, location (linked to the estate,
  with its control/siting badges), owner department and accountable person, url, version,
  criticality, status, health with its last check and a **Check now** button.
- **Endpoints** — every endpoint: name, kind, url, `auth_kind`, **`has_credential`** (never a
  value), `agent_reachable`, `mcp_surface_version`, status. An agent-reachable MCP endpoint is
  marked as such, with a line saying agents may be granted tools on it. Add / edit / remove.
- **Access** — `mcp_application_access` rows: grantee (member or department), capability,
  granted by, granted at, expires. Grant and revoke. When the viewer lacks the grant the view
  returns only their own row, and the tab says so rather than looking empty.
- **Cost** — the linked recurring expense and its monthly equivalent (AC5), or "no cost
  recorded" with a link to create one. Do not compute a cost the Expenses module does not hold.

`data-screen="application-view"`, `data-entity="application"`, `data-record-id="{id}"`.

## Forms

**Application** (`application-add|edit`), ids `application-form-field-{name}`:
`name` (✔, unique), `app_key` (✔, unique, lowercase/underscore, **read-only on edit** — it is an
identifier other things point at), `category` (✔, the schema's 13), `description`, `vendor`,
`is_self_hosted`, `location_id` (offices and desks), `owner_department_id`, `owner_member_id`
(humans), `url`, `version`, `criticality`, `recurring_expense_id`, `notes`.

**Endpoint** (`application-endpoint-add|edit`), ids `endpoint-form-field-{name}`:
`name` (✔, unique per application), `kind` (✔, the schema's 9), `url`, `auth_kind` (✔),
`agent_reachable` (checkbox, with help text: an agent-reachable MCP endpoint becomes grantable
in Agent HR), `mcp_surface_version`, `notes`. **No secret field** — see above.

**Access grant** (on the access tab): grantee is **member XOR department** (the schema's
`application_access_one_grantee` CHECK — surface its refusal rather than pre-empting it with
clever JS), `capability` (✔ read/write/admin), `expires_at`, `note`.

## Removing things must name what depends on them

- `application_endpoint_remove`: **refused while a live `agent_tool_grants` row points at it**,
  naming the agents. `db/075` made `application_endpoint_id` `ON DELETE RESTRICT`, so the
  database will refuse anyway — catch it and say who. This is the `retire_location()` pattern.
- `application_set_status` to `retired`: confirm, and say how many live access grants and
  endpoints it has. Do not cascade; retiring is a status, not a delete.

## Files (exactly these — no additions)

```
html/applications/index.php · form.php · view.php · save.php · status.php · health-check.php
                 · access.php · access-grant.php · access-revoke.php
html/applications/endpoints/form.php · save.php · remove.php

app/features/applications/queries.php   (applications, endpoints, access)
app/features/applications/health.php    (the check and its rules)
app/features/applications/render.php    (the shared re-renders)

app/views/applications/applications.php · application.php · application-form.php
                 · endpoint-form.php · access.php
app/views/applications/partials/application-table.php · overview.php · endpoints.php
                 · access-table.php · cost.php · health-badge.php

mcp/business_applications.py
```

## Query functions (signatures fixed)

```php
// app/features/applications/queries.php
const APPLICATION_PAGE_SIZE = 25;
const APPLICATION_SORT_ALLOWED = ['name', 'category', 'criticality', 'health_status'];
const APPLICATION_CATEGORIES = ['platform','accounting','crm','calendar','email','documents',
    'storage','database','communication','automation','development','security','other'];
const ENDPOINT_KINDS = ['mcp','http_api','database','filesystem','smtp','imap','ssh','ui','webhook'];
const ENDPOINT_AUTH_KINDS = ['none','bearer','oauth','basic','api_key','os_credential','mtls'];
const ACCESS_CAPABILITIES = ['read','write','admin'];

find_applications(PDO, array $filters, string $sort, int $page): array
find_application(PDO, int $id): ?array
application_gaps(PDO, int $id): array            // the AC4 reasons for one row
upsert_application(PDO, ?int $id, array $f): array
set_application_status(PDO, int $id, string $status): array
find_application_endpoints(PDO, int $applicationId): array
find_application_endpoint(PDO, int $id): ?array
upsert_application_endpoint(PDO, ?int $id, array $f): array
remove_application_endpoint(PDO, int $id): bool  // refuses while tool grants point at it
endpoint_dependents(PDO, int $id): array         // the agents to name in that refusal
find_application_access(PDO, int $applicationId): array
grant_application_access(PDO, int $applicationId, array $f, int $by): array
revoke_application_access(PDO, int $id, int $by): bool
find_my_applications(PDO): array                 // mcp_my_applications, for AC2

// app/features/applications/health.php
ENDPOINT_CHECKABLE_KINDS = ['mcp','http_api','ui']
check_endpoint(string $url, string $kind): array     // pure-ish: ['status'=>..,'detail'=>..]
check_application_health(PDO, int $id): array        // worst of its checkable endpoints; writes both columns
```

## Action-manifest entries

The manifest's seven Applications rows, unchanged in substance, plus the two URL corrections
above. Spell every endpoint in full with its real field names, then
`php bin/build_action_registry.php`.

## Activity log events

One `log_activity()` per state change with the manifest's exact event name, plus
`log_screen_view()` on every GET. `application_access.grant` / `.revoke` carry the grantee and
capability in `after` — **AC6 is answered from these rows** by the existing `access_changes`
tool, so the event names must be exact. `application_endpoint.save` carries the endpoint's name,
kind and `agent_reachable`, because changing that flag changes what agents can be granted.
**Never log a secret**, including in `before`/`after`.

## MCP tools this slice must leave working

`mcp/business_applications.py`, registered from `records_server.py` as the other modules are.
**Take names, parameters and gates from `docs/business-os-mcp-tool-surface.md`** — it names
`find_applications` (AC1, AC4), `get_application` (AC1, AC3, AC5) and `my_applications` (AC2).
Do not invent others; the estate spec invented three and the worker was right to build to that
document instead.

`my_applications` reads `mcp_my_applications` and is the **first call an agent makes when a job
needs an outside system**, so it must return the endpoint an agent would actually use — url,
kind, `mcp_surface_version` — and never a credential.

## Out of scope for this slice

- **The secret store** — the Stripe slice builds it; `secret_id` stays NULL.
- **Scheduled health checks** — on-demand only here; the cron job is listed under "written by
  the system" in the manifest.
- **Provisioning anything.** Registering an application does not install it. This is a record of
  what exists.
- Application-to-application dependency mapping, licence tracking, SSO configuration.

## Acceptance (the demo this slice owes)

1. The list shows all 25 seeded applications, built-ins quietly badged, with PostgreSQL 17 and
   MaluDB memory among them.
2. Register a new application — say a Data Lake (`category = storage`) at the Office, owned by
   Accounting — then add an **agent-reachable MCP endpoint** to it.
3. **Open Agent HR and confirm the new endpoint now appears in the tool-grant picker.** That is
   the whole point of `db/075`, and this step proves the two modules are one system.
4. Try to remove that endpoint after granting an agent a tool on it: refused, **naming the
   agent**. Revoke the grant, then the removal succeeds.
5. Grant a department read access and a member admin access; both appear on the access tab with
   who granted them and when; revoke one and it leaves the live list.
6. `gaps=1` lists the applications with no owner, no recent check, or an unattached credential,
   saying which gap each has.
7. **Check now** on the Records MCP endpoint reports `up`; on the Postgres endpoint it reports
   "not checkable from the platform" rather than a guess.
8. A member without the `applications` grant can read the list and an application, sees only
   their own access rows, and is refused every write, naming the grant.
9. `find_applications`, `get_application` and `my_applications` answer through MCP against the
   same data.
10. 375px: the tabbed view, the endpoints table and the access table all work; no horizontal
    scroll.

## Inventory and expertise (added 2026-09-21, db/130 — approved by the owner)

The registry table confused the people it was for. `applications-list` is now an **inventory of
cards**, and an application that runs can name who knows it and what skills come with it.

- **Business areas are `nav_groups`.** The menu and the Applications page share one vocabulary:
  `applications.business_area_id` → `nav_groups`. The unheaded menu group is shown as "Everyday";
  db/130 adds "Technology & Infrastructure" for what sits under the business (a group with no
  sidebar entry renders nothing in the menu — `app_nav()` joins from `nav_items`). A built-in was
  backfilled from its first sidebar entry. An application with no area shows under "Other".
- **The catalog** (`application_catalog`, read through `mcp_application_catalog`): everything a
  business could run — the 23 built-ins plus a curated list of outside products (33 at db/130).
  The list is data; a later migration adds or removes rows. `applications.catalog_key` ties a
  registered application to its entry.
- **Card states.** `active` = status active/degraded and, for a built-in, its module not
  disabled (`mcp_applications.module_enabled`). `off` = a built-in whose module is disabled
  (super-admin: "Turn on in Navigation"). `planned`. `available` = a catalog entry no
  non-retired application carries (an outside product: "Register" → `/applications/new?catalog=<key>`,
  prefilled; mod:applications). `retired` = hidden unless `?retired=1`. Filters: `area`,
  `department`, `health`, `gaps`, `active`, `retired`; a department, health, gap or "active only"
  filter leaves the merely available entries out. No paging.
- **The expert** (`applications.sme_agent_member_id` → `agent_profiles`, one per application).
  Action `application_sme_set` (`html/applications/sme-set.php`, mod:applications, log
  `application.sme_set`): an active agent, or none to clear; refused unless the application is
  active. **Naming an expert grants nothing** — an expert who cannot use the application is a
  new gap ("expert … has no access to this application"), here and in `find_applications`.
  Retiring an application clears its expert.
- **Application skills.** `skill_assignments.scope_kind = 'application'` + `application_id`.
  Assigned with the existing `skill_assign` / `skill_unassign` actions (gate for this scope: mod:hr
  or mod:applications; never an agent; active applications only). Delivery: the application's
  expert and **every agent that may use the application** — `app_agent_skill_application_ids()`,
  built on `app_member_application_ids()` (module grant for a built-in, live `application_access`
  for anything, and a built-in nothing in the menu gates is open to every insider). Specificity:
  agent → role → department → application → org; `pinned_skills` still overrides all.
- **Screens.** `application-view` gains the **Expertise** tab (expert picker, the skills table,
  add/withdraw — inline forms, as the Access tab). The form gains "Business area".
- **MCP.** `find_applications` gains `business_area`, `expert_agent_member_id`,
  `include_available` and answers business area, expert and skill count; `get_application`
  answers `skills`; `skill_catalog` reaches the application scope.
- **Smoke.** `mcp/smoke/22-application-expertise.json` (registers and retires a `SMOKE <run>`
  application; uses the enabled MaluDB skill `file-a-vendor-bill`).
- **Known, not part of this change:** `application_save`'s manifest parameters `owner_department`,
  `owner_member`, `recurring_expense` do not match the handler's field names (`…_id`), so an agent
  cannot set those three through the tool. New parameters here use the handler's own names.

## Where this is going (the owner's vision, 2026-09-21 — not built, no worker starts from this)

Recorded in the requirements ("Three kinds of application, one catalog") and the build plan (phase 7):

- The catalog gains a third kind: **an application from us** — a separate memory-first application on
  the Apache/PHP/HTMX stack, installed on the business's own server by the installation agent, with
  its own database, memory and MCP servers. "Registering an application does not install it" stays
  true of *registering*; installing is the installation agent's job, and it registers what it installs.
- Such an application **ships its skills**, assigned at application scope on install; the platform
  **signs people in** to it (a live `application_access` grant admits — mechanism to design).
- Each one is **its own Apache virtual host at its own DNS name** on the office's one Apache — by
  name, or by port behind the reverse proxy in front (`reservations.subello.com` → :81,
  `crm.subello.com` → :82) — its MCP servers proxied under that name, so humans (browser) and agents
  (MCP) reach it independently. `applications.url` is the name, the port sits on its endpoints; the
  installation agent writes the vhost, the proxy entry when the proxy is ours, and obtains the
  certificate where TLS terminates.
- **The expert stops being optional**: installing, turning on or registering an application proposes
  its expert and a person confirms in one click. An active application with no expert becomes a gap
  beside the three AC4 gaps and "expert has no access".
- **The contract an application from us builds to** is the Claude Code plugin `maludb-os-integration`
  (`~/maludb-os-integration`): `maludb-os.json` at its repo root names catalog key, business area,
  vhost label, endpoints, action registry, shipped skills and the proposed expert. The platform-side
  work it needs is build plan phase 7, item 7 — including `application_catalog.kind = 'ours'`.
- An outside product with **no MCP server** can be recorded but no agent can be granted tools on it —
  already how `agent_reachable` + `kind = 'mcp'` behaves; whether the catalog should say which
  products have a server is open.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none)
