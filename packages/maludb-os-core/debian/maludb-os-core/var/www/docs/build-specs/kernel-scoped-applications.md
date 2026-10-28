# Kernel scoped applications — sites, application roles, grants per scope (C1)

2026-09-25 · Business OS build plan, phase 7 Part C, step C1. Design: `docs/business-os-integration.md`,
"Adopted and scoped applications". The application's side: the `maludb-os-integration` plugin 0.3.0
(C2). First user: ZozoCal-Restaurant (C3), scoped by location. **Checkpoint: the schema, the MCP tool
surface and the action manifest below are approved together before any PHP is written.**

## What it is

One installation of an application may serve several **locations** (ZozoCal: each restaurant) or several
**departments** (a project tool: each department's own plans). The application declares which, and its
own **roles**. The kernel records which sites or departments the installation serves (its **scopes**), and
a person reaches a scope only through a grant that names the scope and one of the application's roles.
Application users are not OS users: nobody is granted anything by default, and no grant reaches `os.`.

The owner's decisions (2026-09-25): a restaurant is a new location kind, `site`; each application declares
its own roles; application users are not OS users by default; fresh installs only.

## The model

```
locations (kind site)  ──┐
                         ├─ application_scopes ── application_access (scope + role) ── member | department | residents of a site
departments ─────────────┘          │
applications (scope_kind) ── application_roles (key, name, capability, is_admin)
```

- **A site** is a place the business trades from — a restaurant, a shop, a branch. It is not a machine:
  no parent, nothing parented to it, no siting, no hardware, no platform. It has an `address` and a
  `timezone` (IANA). People and agents reside at it (`location_residents`, as today). Departments may
  work at it (`location_add_department`, as today). An application never *resides* at a site
  (`applications.location_id` is the office it runs on); it *serves* sites through its scopes.
- **`applications.scope_kind`** ∈ `none` (default — HR, every application so far), `location`, `department`.
  It can change only while the application has no scopes and no live grant.
- **Application roles** are the application's own words (`admin`, `manager`, `user` for ZozoCal). Each role
  carries the kernel **capability** it amounts to (`read` / `write` / `admin`) so everything that already
  reads capability — the launcher, `app_can_use_application()`, an agent's access — keeps working. Exactly
  one role is `is_admin`: the role a super-admin holds in every scope. An application without roles works
  as today (capability only). A role in use by a live grant cannot be removed.
- **A scope** is one site (for `location`) or one department (for `department`) the installation serves.
  Removing a scope revokes every grant on it, in the same transaction, logged.
- **A grant** on a scoped application names a scope; on an application with roles it names a role, and its
  capability is the role's (set by trigger, never typed). The grantee is exactly one of: a member, a
  department (its live members), or the **residents of a site** (its live residents) — the last so that
  "everyone at Airport is staff at Airport" is one grant. A member may hold grants on several scopes with
  different roles; on one scope the highest capability wins (ties: the role declared first).
- **A super-admin** holds the admin role in every live scope, as today they hold `admin` on every
  application. **An agent** is granted per scope like a person.

## Schema — `db/141_scoped_applications.sql` (additive)

```sql
-- 1. Sites
ALTER TABLE locations DROP CONSTRAINT <kind check>;   -- by name, looked up in the migration
ALTER TABLE locations ADD CONSTRAINT locations_kind_check
    CHECK (kind IN ('building','office','desk','site'));
ALTER TABLE locations DROP CONSTRAINT <siting-by-kind check>;
ALTER TABLE locations ADD CONSTRAINT locations_siting_by_kind
    CHECK ((kind IN ('building','site')) = (siting IS NULL));
ALTER TABLE locations ADD COLUMN address  text;       -- sites only (CHECK)
ALTER TABLE locations ADD COLUMN timezone text;       -- sites only; IANA name, checked against pg_timezone_names
ALTER TABLE locations ADD CONSTRAINT locations_site_shape CHECK (
    kind <> 'site' OR (parent_location_id IS NULL AND platform IS NULL AND hostname IS NULL
                       AND ip_address IS NULL AND cpu_cores IS NULL AND memory_mb IS NULL
                       AND storage_gb IS NULL AND owner_member_id IS NULL));
ALTER TABLE locations ADD CONSTRAINT locations_site_fields CHECK (
    kind = 'site' OR (address IS NULL AND timezone IS NULL));
-- trigger locations_parent_not_site: nothing is parented to a site
-- trigger applications_not_at_site: applications.location_id never names a site

-- 2. The application's scope kind and roles
ALTER TABLE applications ADD COLUMN scope_kind text NOT NULL DEFAULT 'none'
    CHECK (scope_kind IN ('none','location','department'));
-- trigger applications_scope_kind_frozen: refused while scopes or live grants exist

CREATE TABLE application_roles (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    role_key       text   NOT NULL CHECK (role_key ~ '^[a-z][a-z0-9_]{0,39}$'),
    name           text   NOT NULL,
    capability     text   NOT NULL CHECK (capability IN ('read','write','admin')),
    is_admin       boolean NOT NULL DEFAULT false,
    sort_order     integer NOT NULL DEFAULT 0,
    UNIQUE (application_id, role_key)
);
CREATE UNIQUE INDEX application_roles_one_admin ON application_roles (application_id) WHERE is_admin;
-- is_admin implies capability = 'admin' (CHECK)

-- 3. Scopes
CREATE TABLE application_scopes (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id bigint NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    location_id    bigint REFERENCES locations(id),
    department_id  bigint REFERENCES departments(id),
    added_by       bigint NOT NULL REFERENCES members(id),
    added_at       timestamptz NOT NULL DEFAULT now(),
    removed_at     timestamptz,
    removed_by     bigint REFERENCES members(id),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((location_id IS NULL) <> (department_id IS NULL))
);
CREATE UNIQUE INDEX application_scopes_live_location ON application_scopes (application_id, location_id)
    WHERE removed_at IS NULL AND location_id IS NOT NULL;
CREATE UNIQUE INDEX application_scopes_live_department ON application_scopes (application_id, department_id)
    WHERE removed_at IS NULL AND department_id IS NOT NULL;
-- trigger application_scopes_check: the kind matches applications.scope_kind; a location scope names a
--   live site; a department scope names a live department
-- trigger application_scopes_removed: removal revokes the scope's live grants (revoked_by = removed_by)

-- 4. Grants per scope, with a role, to a member, a department or a site's residents
ALTER TABLE application_access ADD COLUMN scope_id bigint REFERENCES application_scopes(id);
ALTER TABLE application_access ADD COLUMN role_key text;
ALTER TABLE application_access ADD COLUMN resident_location_id bigint REFERENCES locations(id);
ALTER TABLE application_access DROP CONSTRAINT application_access_one_grantee;
ALTER TABLE application_access ADD CONSTRAINT application_access_one_grantee CHECK (
    num_nonnulls(member_id, department_id, resident_location_id) = 1);
DROP INDEX application_access_member_live_idx;   -- recreated with the scope in it
DROP INDEX application_access_dept_live_idx;
CREATE UNIQUE INDEX application_access_member_live_idx ON application_access
    (application_id, member_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND member_id IS NOT NULL;
CREATE UNIQUE INDEX application_access_dept_live_idx ON application_access
    (application_id, department_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND department_id IS NOT NULL;
CREATE UNIQUE INDEX application_access_residents_live_idx ON application_access
    (application_id, resident_location_id, COALESCE(scope_id, 0)) WHERE revoked_at IS NULL AND resident_location_id IS NOT NULL;
-- trigger application_access_scope_role (BEFORE INSERT OR UPDATE):
--   scoped application → scope_id required, of this application, live; unscoped → scope_id NULL
--   application with roles → role_key required and declared; capability := the role's capability
--   application without roles → role_key NULL
--   resident_location_id names a live site or office (people reside at desks too, but a desk has one resident)

-- 5. Who holds what
-- app_member_application_scopes(p_application bigint, p_member bigint)
--   RETURNS TABLE (scope_id, scope_kind, location_id, department_id, scope_name, role_key, role_name, capability)
--   SECURITY DEFINER; the member's live grants on live scopes through all three grantee routes, one row per
--   scope (highest capability, then the role declared first); a super-admin gets every live scope with the
--   is_admin role; an inactive member gets nothing.
-- app_can_use_application(): unchanged in meaning — any live grant; the residents route added.
-- mcp_my_applications: capability also through the residents route; adds scope_kind.

-- 6. Read views (security_barrier, same gate as mcp_applications; grants to app_records_ro checked after)
--   mcp_application_roles, mcp_application_scopes (scope + its site/department name + live grant count),
--   mcp_application_access gains scope_id, scope_name, role_key, role_name, resident_location_id,
--   resident_location_name (appended last);
--   mcp_locations gains address, timezone (appended last);
--   mcp_my_application_scopes: app_member_application_scopes(a, app_current_member_id()) for each
--   application in mcp_my_applications — the launcher's scope picker.
```

`location_residents_check` needs no change (only a building refuses residents). The activity log has no
entity-type CHECK (only `source`), so `application_scope` needs nothing there.

## Sign-on — claims and launch (`app/features/applications/sso.php`, `html/launch.php`)

Claims stay exactly as today and **gain** two fields (additive within the major version):

```json
"role":   "manager",                          // unscoped application with roles: the member's role; else null
"scopes": [ {"scope_id": 7, "kind": "location", "id": 12, "name": "Airport",
             "role": "user", "capability": "write"} ],     // scoped application: every scope held; else []
"scope":  7                                   // the scope the person chose on the launcher, or null
```

`capability` (existing) stays the highest capability held. `/launch/<id>?scope=<scope_id>`: the scope must
be in the member's scopes (else 404, the same sentence as an application they cannot see); with no `scope`
and exactly one held, that one; with several and none chosen, `scope` is null and the application offers
its own switcher over `scopes`. The launcher card of a scoped application lists the scopes held as links
(one tap per restaurant); one scope = the card itself.

## Directory feed — `GET changes.php` (`app/api/directory.php`)

Two lists are added to `os.directory-changes/1` (additive), both **about the calling application only**:

| List | Rows | Changed when |
| --- | --- | --- |
| `scopes[]` | `scope_id, kind, location_id, department_id, name, address, timezone, removed_at, updated_at` | The scope is added or removed, or its site or department is renamed, moved or archived |
| `access[]` | `member_id, role, capability, scopes[{scope_id, role, capability}]` — the member's **whole** holding on this application, replacing what the mirror had | Any input to it changed since the cursor: a grant on this application granted, revoked or expired (for a department or residents grant, every member it reaches); a membership joined or left; a residency added or removed; the member's status changed; a scope removed |

A member who holds nothing any more appears with `capability: null, scopes: []` — the mirror drops their
access; that is how a revoked scope closes within a minute. A full answer (`since` absent) carries every
live scope and every member holding anything. `members[]` is unchanged. The overlap rule (10 s) stands.

`GET scopes.php` (new, same token): the application's live scopes — what a new installation materialises
before its first sign-in.

Run facts (`html/api/v1/runs/facts.php`) gain `scopes[]` for an agent, the same shape as the claims, so an
application knows which of its restaurants an agent may act in.

## MCP tool surface (records server, `mcp/business_applications.py`, `mcp/business_estate.py`)

| Tool | Change | Answers |
| --- | --- | --- |
| `locations` | `kind` accepts `site`; rows carry `address`, `timezone` | "Which sites do we have?" |
| `get_location` | A site shows its residents, the departments working there, and the applications serving it (scopes) | "Who works at Airport, and what do they use there?" |
| `get_application` | Adds `scope_kind`, `roles[]`, scope count | "Is Reservations per restaurant, and what are its roles?" |
| `application_scopes` *(new)* | `application` (id or key), optional `scope`: each live scope with its site or department and its grants (grantee, role, capability, route) | "Who is a manager at Airport in Reservations?" |
| `member_application_access` *(new)* | `member`, optional `application`: every application and scope the member holds, with role and route | "What can Maria use, and where?" |

Both new tools read the `mcp_*` views only; gate as `find_applications`.

## Action manifest (section Applications; section Estate)

| Action | Handler | Gate | Log event | Change |
| --- | --- | --- | --- | --- |
| `location_save` | `html/locations/save.php` | `mod:locations` (as today) | `location.create` / `location.update` | `kind = site`: `name`, `address`, `timezone`, `description`, `status`; parent, siting and hardware fields refused for a site |
| `location_move` | `html/locations/move.php` | as today | as today | Refuses a site, and refuses a site as the new parent |
| `application_save` | `html/applications/save.php` | as today | as today | Adds `scope_kind` (frozen while scopes or grants exist — the trigger's sentence) |
| `application_roles_set` *(new)* | `html/applications/roles-set.php` | super-admin | `application.roles_set` | The whole list `roles` (`key`, `name`, `capability`, `is_admin`) replaces the declared roles; a role in use by a live grant cannot be dropped; undo = set the previous list (in the log's `before`) |
| `application_scope_add` *(new)* | `html/applications/scope-add.php` | `mod:applications` | `application_scope.add` | `application`, `location` or `department` → `record_id` = the scope |
| `application_scope_remove` *(new)* | `html/applications/scope-remove.php` | `mod:applications`; confirm | `application_scope.remove` | Revokes the scope's grants (counted in the log); approval category `access_change` for agents |
| `application_access_grant` | `html/applications/access-grant.php` | as today | as today | Adds `scope`, `role`, and grantee `residents` (a site or office id); `capability` ignored when the application has roles |
| `application_access_revoke` | as today | as today | as today | Unchanged |

Screens (React, the Bootstrap nxl look, no modals, 375 px, lists as cards):

- **Work Locations** (`/locations`): a Sites group beside buildings/offices/desks; the site card shows
  address, timezone, residents and applications served. New/edit form: kind `site` shows only its fields.
- **Application** (`/applications/[id]`): a **Scopes** tab when `scope_kind ≠ none` — the scopes as cards
  (site or department, grants count), add/remove; a **Roles** panel on the Overview (read-only unless
  super-admin). **Access** tab: each grant shows scope and role; the grant form gains Scope and Role pickers
  and a third grantee, "Everyone at <site>".
- **Launcher** (`/launcher`): a scoped card lists its scopes as links.
- **Member** (`/team/[id]`): an Applications panel from `member_application_access`.

## Order of work

1. Migration db/141 on a copy first (the three constraint names looked up, not guessed); the trigger
   sentences; grants to the read roles checked afterwards; `app_member_application_scopes` proven by SQL
   for all three routes, a super-admin, an inactive member, a removed scope.
2. PHP: location save/move, application save, roles-set, scope-add/remove, access-grant; presenters;
   `emit_action_status()`; `record_id` on scope add. Registry rebuilt (`bin/build_action_registry.php --check`).
3. Claims, launch with `?scope=`, the feed's two lists, `scopes.php`, run facts.
4. MCP tools; React screens.
5. Proof (below), then the plugin's references (C2) are written from this code.

## Proof

- A site cannot take a parent, a child, hardware, or an application residing at it; the trigger sentences
  reach the form.
- Test application `scopetest` (scope `location`, roles admin/manager/user): two sites, Downtown and Airport,
  added as scopes. Maria: `user` at Airport by direct grant. Airport residents: `manager` by a residents
  grant. Sam, resident at Airport: `manager` there through residency. A super-admin: `admin` at both.
- The launcher shows Maria one link (Airport); `?scope=<Downtown>` answers 404. The claims she carries are
  exactly the shape above.
- The feed: a full answer lists both scopes and the three holders; revoking Maria's grant puts her in the
  next `since` answer with `scopes: []`; removing Sam's residency does the same for him; removing the Airport
  scope revokes its grants and appears in `scopes[]` with `removed_at`.
- `scope_kind` cannot change while a scope exists; a role in use cannot be dropped; a grant without a scope on
  a scoped application is refused with the trigger's sentence.
- A department-scoped test application: the same, with two departments — the project-tool case.
- The existing proofs still pass: HR (unscoped, no roles) signs in unchanged; kernel smokes 3, 5, 6, 7, 19, 22.
- The test applications and sites are retired afterwards.

## Open

- Whether an office can be a scope as well as a site (not needed by ZozoCal; refused for now).
- Whether an application may declare a role that grants nothing on some screens (the application's rule —
  the kernel never knows screens).

## Built and proven (2026-09-25)

Built as specified: db/141 (proven on a copy first); PHP — `html/locations/{save,move,view}.php`,
`html/applications/{save,access-grant,view,roles-set,scope-add,scope-remove}.php`, `html/launch.php`,
`html/launcher.php`, `html/team/view.php`, `html/api/v1/directory/{changes,scopes}.php`, `html/api/v1/runs/facts.php`;
the one holding function every consumer shares, `sso_member_holding()` (`app/features/applications/sso.php`), so
claims, feed and run facts cannot disagree; MCP `application_scopes`, `member_application_access`, sites in
`locations`/`get_location`, roles and scopes in `get_application`; React screens for all of it (deploy is the owner's).

Proven:
- `mcp/smoke/23-scoped-applications.json` (32/32) through the Actions MCP: sites saved, a site with a parent or a
  bad time zone refused, a site cannot be moved; roles set, an admin role that is not admin refused; two scopes,
  a duplicate, an office and a department refused; grants by member and by residents; a grant without a scope,
  with an unknown role, without a role refused; the holdings by SQL for a direct grant, a residency, the
  super-admin and a stranger; scope kind frozen; a role in use cannot be dropped; the department-scoped case.
- `mcp/smoke/24-scoped-applications-revoke.json` (7/7): a grant revoked, a residency removed, a scope removed
  (its grant revoked, counted in the log), a second removal refused.
- A launch/feed proof over HTTP (24/24): Priya launches into Airport only, `?scope=` Downtown and a stranger 404;
  the owner carries both scopes and the chosen one; the launcher card lists her one scope; the full feed lists
  both scopes and every holder; `scopes.php`; run facts carry the holding; HR's launch unchanged; after the
  revocations the next `since` feed carries Priya and Sam with nothing, the owner down to one scope, and the
  Airport scope with `removed_at`, and Priya's launch is refused.
- Kernel smokes: 5, 6, 7, 22 pass. 3 (14/34) and 19 (39/40) fail on steps this work does not touch — smoke 3 sends
  `parent_location` to `location_save` and omits `application` on `application_access_revoke`, both refused by the
  tools' own argument checks; 19's failing step looks for an `eval_run.start` log row.

Fixed on the way (broken since the kernel cut): a super-admin's location page counted rows in dropped tables;
`get_application` read the dropped `mcp_recurring_expenses`. The actions server keeps a `record_id` a handler
states itself (a scope add names the scope, not the application).

SMOKE data left: sites 18–21, applications 40–43 ("SMOKE … Scoped Reservations", "SMOKE … Dept Projects").
