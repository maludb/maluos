# Build spec: Estate slice (buildings, offices & desks)

2026-09-18 · **pulled forward** from phase 4 at the owner's request · planning-class spec

**Why this is here and not in phase 4.** The build plan grew the business modules first and left
the setup modules until the estate was needed by the agent workforce. Reordered 2026-09-18: a
super-admin should be able to set the business up — its estate, then its people and agents —
before more business modules land. This slice is the first half of that; Agent HR is the second.

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`), with the review
lessons of the Expenses and Bookkeeping slices — **read the "Review findings" section of
`docs/build-specs/expenses.md` and of `docs/build-specs/bookkeeping-ledger.md` before starting.**
Between them they record five mistakes this slice could repeat.

> **Naming (2026-09-18):** the module is **presented as "Work Locations"** in the UI — sidenav,
> page titles, breadcrumbs, the module-grant label and the registered application's name. The
> documents, screen ids (`locations-list`, …), URLs (`/locations/`),
> the module grant key (`locations`) and the tables all keep saying *estate*, deliberately: they
> are identifiers, and the manifest and action registry point at them. A title that disagrees
> with an id is not a defect here — do not "fix" it by retitling the screens.

Module grant: `locations` · Manifest section: **Estate: buildings, offices & desks**
Schema tables (never modify): `locations`, `location_residents` (`db/043_locations_task_queue.sql`).
Read views: `mcp_locations`, `mcp_location_residents`, plus `mcp_applications`,
`mcp_departments` and `mcp_members` for the panels and pickers.
Questions this slice must answer: **L1–L6, L8–L13** (L7 is `record_history`, already built).

> **The cross-location task queue is NOT in this slice.** `location_tasks`, `consent_grants`,
> the screens `location-tasks`, `location-task-add`, `location-task-view`, `desk-permissions`
> and the six actions `location_task_*` / `consent_grant_*` belong with the desktop companion
> (phase 6) — a task queue with nothing at the far end to answer it is a screen that can only
> ever show an empty list. Build the estate; leave the queue. `location-view`'s queue panel says
> "cross-location tasks arrive with the desk companion" instead of showing a count of zero.
> **Desk enrollment is also phase 6** — `enrollment_token_id`, `enrolled_at`, `app_version`,
> `os_platform` and `mcp_surface_version` are displayed when present and never written here.

## Revision 2026-09-18 — control and siting (`db/067`, undone by `db/094` and `db/095`)

Asked for after the slice shipped, and it changes the model rather than adding a field:

- **`control`** — **removed from the product by db/095.** It was `managed` | `unmanaged`,
  stated on the building and inherited down the tree, and it briefly decided who could live
  where. See the two bullets below: the rule went first, then the field, both at the owner's
  word and both on the day they shipped.
- **`siting`** — `onsite` | `offsite`, on offices and desks only. Onsite is a VM inside our own
  host; offsite is reached over the internet. **Stored, not inferred from the tree**, because
  the minimum platform is one office with no building recorded and it is emphatically onsite,
  while a parent building can belong to somebody else.
- **The residency rule** is `location_allows_resident(id, member_kind)`: nobody resides in a
  building; people and agents may reside at any office or desk. It briefly also refused an agent
  wherever the effective control was unmanaged — **reversed by db/094 the same day** at the
  owner's word, because in use it was untenable: a hire failed with a Postgres exception over
  how a location happened to be recorded, and nothing on the hiring screen could fix it. The
  office-manager trigger went with it, an office manager being an agent.
- **Then control left the product entirely (db/095).** db/094 had kept it as information — a
  badge on the locations table, a note on the agent form's options, a line on the location page.
  Asked whether that was worth keeping, the owner said no, and the reasoning is worth recording:
  a business running this platform does not need the platform's opinion about which machines it
  runs, and a field nobody acts on is a field everybody reads past. Gone: the column, the
  inheritance function, the two view columns, the form field, every badge, and the `control`
  filter on the `locations` MCP tool. `siting` is untouched — it answers a different question,
  and db/074's Front Office seed depends on it.
- **A trigger's message must never reach a screen raw.** The refusal that started this arrived
  as `SQLSTATE[P0001]: Raise exception: 7 ERROR: … CONTEXT: PL/pgSQL function …` because the
  hire endpoint tried to trim one particular message with a regex that no longer matched it.
  `db_message()` (app/db.php) is now the single rule: a P0001 — our own RAISE, written for a
  person — is shown as its sentence alone; anything else gets the caller's own words, and the
  full error goes to the error log.
- `mcp_locations` carries `control`, `effective_control`, `siting`, `allows_agents` and
  `allows_humans`, so **no caller re-derives the rule** — this is the same principle the ledger
  slice follows with `db/056`: the database owns the rule, the app presents it.

## Revision 2026-09-18 (2) — what a machine is, and how we get in (`db/069`)

- **The platform vocabulary was replaced.** It read `proxmox, kvm, lxc, bare_metal, cloud,
  workstation, other` — products and categories mixed together, answering the hypervisor's
  question rather than the operator's. It is now five machine kinds:
  `physical_hypervisor` (Physical Server with Hypervisor), `physical_os` (Physical Server with
  OS), `vps` (Virtual Private Server), `desktop`, `laptop`. Keys are stored,
  `location_platform_label()` renders them. There is deliberately **no "other"**; a machine
  whose kind is not recorded has a NULL platform, which is honest where "other" was not.
- **Four facts added**: `operating_system`, `os_version`, `ssh_access`, `root_access`.
- **SSH and root are tri-state, not Y/N.** NULL means *not recorded*, which is not the same as
  "no". The form offers Yes / No / Not recorded and stores NULL for the third, because an estate
  record that reports "no root access" for a machine nobody has checked is stating a fact it
  does not have. `yes_no_unrecorded()` renders them.
- **`operating_system` overlaps `os_platform` on purpose, and they are not the same field.**
  `operating_system` is what the people maintaining the estate recorded; `os_platform` is what
  the desktop companion reports about itself at enrolment (phase 6). Recorded versus observed.
  If they ever disagree, that disagreement is information.

## What the database already guarantees (do not re-implement in PHP)

- `locations_desk_has_owner` — a desk must have an `owner_member_id`.
- `locations_building_is_root` — a building can have no parent.
- `name` is `UNIQUE`; `parent_location_id` is `ON DELETE RESTRICT`, so a parent with children
  cannot be deleted out from under them.
- `kind` ∈ `building` | `office` | `desk`; `status` ∈ `active` | `retired`;
  `presence` ∈ `online` | `offline` | `unknown`.
- `office_manager_member_id` references **`agent_profiles(member_id)`**, not `members` — the
  office manager is an agent by construction. Until Agent HR is built there are no agent
  profiles, so that picker is empty and the screen says why.

Catch the `PDOException`, read it, show it as a field error — the `citext`-unique handling in
the expense-categories screen is the pattern.

## Gate and visibility

- **Reading the estate is insider-open; changing it needs the grant.** *(Corrected in review
  2026-09-18 — this spec originally said `require_module_grant('locations')` everywhere and
  justified it with `app_can_see_locations()`, a function that does not exist. The installed
  view is gated on `app_is_insider()` — any non-external member — and
  `docs/business-os-mcp-tool-surface.md` gives every estate read tool the `insider` gate, while
  every estate **action** in the manifest is `mod:locations`. Reading with the grant would
  refuse at the screen someone the MCP surface answers happily: the same screen-versus-data
  mismatch as the money slices, pointing the other way.)*
  - GET `locations-list`, `location-view` → **`require_insider()`**, the PHP mirror of
    `app_is_insider()`.
  - The Work Locations table offers its **Add location** button and **Edit** column only to a
    member `has_module_grant('locations')` admits — the same rule the endpoints enforce, asked
    rather than enforced, so nobody is walked into a refusal by a button.
  - Every write, and the form and its fragment → **`require_module_grant('locations')`**.
- `location_retire` is `desk owner, super` and `consent_grant_revoke` is `desk owner, super` —
  **a comma means OR**. `location_retire` = the desk's `owner_member_id` **or** a super-admin.
  Getting this backwards locks the owner out of their own desk.
- `location_rename` is `desk owner, admin` — the owner of that desk, or a business admin.
- Everything else in this slice is `mod:locations`.
- Reads through `mcp_*` views only; writes to base tables after the gate.
- **No department stamping.** `locations` has no `department_id`: a location is not owned by a
  department, it *hosts* departments (`departments.home_location_id`). Do not invent one.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `locations-list` | `/locations/` | **Work Locations**: the whole estate as one table — every building, its offices, desks, who is online | `kind`, `parent`, `online` |
| `location-add` | `/locations/new` | add a building, office or desk | `kind`, `parent` |
| `location-edit` | `/locations/{id}/edit` | edit name, parent, description, specs | — |
| `location-view` | `/locations/{id}` | one location: specs, residents, manager, applications, departments | — |

The installed rewrite rules serve all four: `/locations/new` → `form.php`,
`/locations/{id}/edit` → `form.php?id=`, `/locations/{id}` → `view.php?id=`, and `/locations/`
from its own `index.php`. No new Apache configuration — and unlike the ledger
spec, that claim has been checked: every one of these is a shape the installed rules already
serve.

## Retired: the `estate-map` tree *(2026-09-18, owner's decision)*

This slice shipped a second screen at `/estate/`: the whole estate as a **tree, not a table**,
built from `estate_tree()`. In use it was neither readable nor actionable — it offered no way
to edit anything — so the owner replaced it with the table below, which is now the one Work
Locations screen and what the nav points at. `/estate/` redirects to `/locations/` for old
links, `estate-map` is gone from the manifest, and `estate_tree()`, `map.php`,
`location-tree.php` and `location-row.php` are deleted.

What the tree carried and the table must therefore keep answering: a building is optional (the
minimum platform is one office plus one desk, so a parentless office is **not an error**, it is
the normal state of a new tenant), and the applications and departments that reside at a
location are shown on `location-view` rather than in the list.

## `locations-list`

Columns: Name (link) · Kind badge · Parent · Presence badge (+ `last_seen_at` as "seen 3h ago"
when offline/unknown) · Owner (desks) · Specs (cores/memory/storage, dashes where unknown) ·
Residents · Status. Filters `kind`, `parent`, `online=1`. Sort allowlist `name`, `kind`,
`last_seen_at` (default `kind, name`). Page size 25. Retired locations are hidden unless
`status=retired` is asked for, and render with a `dark` badge.

## `location-view`

Header: name, kind badge, presence, parent (linked), status. Panels in order:

1. **Specs** — platform, external_ref, hostname, ip_address, cores, memory, storage,
   `is_always_on`. A desk additionally shows `app_version`, `os_platform`,
   `mcp_surface_version`, `enrolled_at` **when present**, with "not enrolled yet" otherwise.
2. **Residents** — `mcp_location_residents` where `removed_at IS NULL`, each with human/agent
   glyph and `is_primary`, plus add and remove.
3. **Office manager** (offices only) — the agent, with a picker over `agent_profiles`. Until
   Agent HR ships: "an office manager is an agent — agents arrive with Agent HR."
4. **Departments** — departments whose `home_location_id` is this location, with add/remove.
5. **Applications** — `mcp_applications` residing here (read-only in this slice; the
   Applications module owns their CRUD).
6. **Cross-location tasks** — the carve-out message, not a zero.
7. **Activity** — `/activity?entity_type=location&entity_id={id}`.

`data-screen="location-view"`, `data-entity="location"`, `data-record-id="{id}"`.

Header actions: Edit · Move (offices) · Set office manager (offices) · Retire (confirm) ·
Delete (super-admin only, confirm).

**Retire vs delete** *(delete added 2026-09-18 at the owner's request)*. Retire ends a
location's working life and keeps everything: the row, its specs, and the record of what
happened there. Delete is the super-admin's remedy for a location that should never have
existed — a mistyped desk, a duplicate office — and it removes the row. It is refused, naming
what is in the way, while anything still points at the location: locations inside it, residents,
departments homed there, applications, agents, duties, runs, prompt-ledger entries, tasks,
documents, employment profiles, stock locations. Thirteen of the sixteen foreign keys into
`locations` are NO ACTION or RESTRICT, so an unchecked DELETE would surface a constraint name
and tell the super-admin nothing; the screen therefore offers Delete as a disabled button
carrying the reason when a location is in use. The three that cascade — past residency rows,
consent grants, desk imports — belong to the location and go with it. The activity trail does
not: `activity_log` holds no foreign key to `locations`, and `location.delete` logs what the
location was, so its history stays answerable after the row is gone.

## `location-add` / `location-edit` form

Field ids `location-form-field-{name}`:

| Field | Input | Required | Validation |
| --- | --- | --- | --- |
| `name` | text | ✔ | 1–200, unique — a duplicate is a field error, never a 500 |
| `kind` | select | ✔ | building / office / desk; **read-only on edit** — a desk does not become a building |
| `parent_location_id` | select | conditional | **required for a desk**, optional for an office, **must be empty for a building** (the schema's CHECK). Options: buildings when adding an office, offices when adding a desk |
| `owner_member_id` | select | **✔ for a desk** | the schema's CHECK; humans only |
| `description` | textarea | | |
| `platform` | select | | proxmox / kvm / lxc / bare_metal / cloud / workstation / other |
| `external_ref`, `hostname` | text | | |
| `ip_address` | text | | must parse as an IP (`inet`) — validate in PHP with `filter_var()` before the insert, so a typo is a field error rather than a Postgres cast error |
| `cpu_cores`, `memory_mb`, `storage_gb` | number | | > 0 when given |
| `is_always_on` | checkbox | | defaults **on** for an office, off for a desk |

The `kind` param on `location-add` preselects the kind and the `parent` param preselects the
parent, so "add a desk to this office" arrives from `location-view` with both filled.

On `location-edit` the header carries a **Delete** button (`location-form-delete`) for the
super-admin only — the same `location_delete` action, gate `super`, as on `location-view`, and
the same courtesy: when anything still points at the location the button is disabled and its
title names the blockers, so the answer is "retire it instead", not a refusal after the click.
Everyone else never sees it.

## Files (exactly these — no additions)

```
html/estate/index.php                (redirect to /locations/ only)
html/locations/index.php · form.php · view.php · save.php · move.php · rename.php
             · retire.php · office-manager.php · resident-add.php · resident-remove.php
             · department-add.php · department-remove.php · parent-options-fragment.php

app/features/estate/queries.php   (locations, residents)
app/features/estate/render.php    (the shared re-renders)

app/views/estate/locations.php · location.php · location-form.php
app/views/estate/partials/location-table.php
                 · residents.php · specs.php · parent-options.php

mcp/business_estate.py
```

## Query functions (signatures fixed)

```php
// app/features/estate/queries.php
const LOCATION_PAGE_SIZE = 25;
const LOCATION_SORT_ALLOWED = ['name', 'kind', 'last_seen_at'];
const LOCATION_KINDS = ['building', 'office', 'desk'];
const LOCATION_PLATFORMS = ['proxmox', 'kvm', 'lxc', 'bare_metal', 'cloud', 'workstation', 'other'];

find_locations(PDO, array $filters, string $sort, int $page): array
find_location(PDO, int $id): ?array
estate_tree(PDO): array              // buildings -> offices -> desks, parentless offices included
insert_location(PDO, array $f): array
update_location(PDO, int $id, array $f): array
move_location(PDO, int $id, ?int $parentId): array
rename_location(PDO, int $id, string $name): array
retire_location(PDO, int $id): array // refuses while it has active children, applications or residents
set_office_manager(PDO, int $id, ?int $agentMemberId): array
find_location_residents(PDO, int $id): array
add_location_resident(PDO, int $id, int $memberId, bool $isPrimary): array
remove_location_resident(PDO, int $id, int $memberId): bool
find_location_departments(PDO, int $id): array
set_department_home(PDO, int $departmentId, ?int $locationId): array
find_location_applications(PDO, int $id): array
parent_options(PDO, string $kind): array   // buildings for an office, offices for a desk
```

**`retire_location()` refuses and names what is in the way** — the manifest says "a building or
office is never retired while it still has active children, applications or resident members;
the endpoint refuses and names them." Not a generic "cannot retire": the message lists the
children, the applications and the residents, because that list is the user's next task.

## Action-manifest entries

*(Note: `location_remove_department` below was added to the manifest by this session before the build, so a worker reading the manifest finds it already there.)*

The manifest's eight estate actions that belong to this slice — `location_save`, `location_move`,
`location_rename`, `location_retire`, `location_set_office_manager`, `location_add_resident`,
`location_remove_resident`, `location_add_department` — plus **one this slice adds**, because
the manifest has an add with no remove (and, since 2026-09-18, `location_delete`, gate `super`):

| Action | File | Params | Undo | Confirm | Approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `location_remove_department` | `/locations/department-remove.php` | **location**, **department** | add it back | | | `department.set_home_location` | mod:locations, admin |

The six `location_task_*` / `consent_grant_*` actions stay unbuilt and keep their manifest rows.
Spell every endpoint in full with the endpoint's own field names, then
`php bin/build_action_registry.php`.

## Activity log events

One `log_activity()` per state change with the manifest's exact event name, plus
`log_screen_view()` on every GET. `location.save` carries `kind` and `name` in `after`;
`location.retire` carries what was retired; the department actions log
`department.set_home_location` with the department and the location, before and after.

## MCP tools this slice must leave working

`mcp/business_estate.py`, registered from `records_server.py` as the other modules are:

| Tool | Questions | Views |
| --- | --- | --- |
| `estate` | L11 | `mcp_locations`, `mcp_applications`, `mcp_location_residents` |
| `locations` | L1, L9 | `mcp_locations` |
| `get_location` | L2, L12 | `mcp_locations`, `mcp_location_residents`, `mcp_applications`, `mcp_departments` |
| `who_is_where` | L13 | `mcp_location_residents`, `mcp_locations` |

*(Corrected in review 2026-09-18. This spec first invented three tool names and mapped them to
questions the deferred task queue owns. `docs/business-os-mcp-tool-surface.md` is the
authoritative source a spec may never contradict, and it names these four with the `insider`
gate, separating `find_location_tasks`, `desk_permissions`, `queue_metrics` and `route_request`
as the queue's own. The worker spotted the contradiction and built to the authoritative doc,
which is exactly right.)* Leave the task-queue tools unbuilt rather than stubbing them.

## Out of scope for this slice

- The cross-location task queue and consent grants (phase 6, with the desk companion).
- Desk enrollment and the desktop app's sign-in flow (phase 6) — enrollment fields are
  displayed, never written.
- Applications CRUD — its own module; this slice only lists what resides at a location.
- Presence and `last_seen_at` updates: written by the scheduled presence job, not by a screen.
  Display them; never set them.
- Provisioning: nothing here creates a VM. A location is a *record of* infrastructure.

## Acceptance (the demo this slice owes)

1. The map renders with only the seeded `Office` row — the state a new tenant starts in — and
   does not treat its missing building as an error.
2. Add a building (`Proxmox host`), move the office into it, and watch the tree re-parent.
3. Add a desk under the office with an owner; confirm the schema refuses a desk with no owner
   and that the refusal reads as a field error, not a 500.
4. Add both humans as residents of the office, one primary; remove one.
5. Give a department a home at the office, then remove it.
6. Try to retire the office: refused, **naming** the desk, the residents and the applications in
   the way. Retire the desk instead; it leaves the list and the map.
7. A member without the `locations` grant is refused at the door with a message naming the
   grant — not shown an empty estate.
8. `find_locations` and `estate_summary` answer through MCP against the same tree.
9. Spoken: "add a desk called Ed's Desk to the office", "what's in the estate", "who lives at
   the office".
10. 375px: the tree indents without horizontal scroll, specs wrap, header actions collapse.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none)
