# Data-driven side navigation — plan

Status: **approved 2026-09-20, the owner's four decisions recorded at the end. Step 1 is BUILT**
(db/127: the tables, the seed, `app_nav()`; `nav_modules()` reads it — the menu verified
byte-identical before and after for a super-admin, a dept-admin, two users and an external
member). **Step 2 is BUILT** (db/128): `module_catalog()` and React's `NAV_OWNER` are deleted —
highlighting reads `active_patterns`, an external entry opens its own address in a new tab, the
Dashboard's `/dashboard` is data; `module_by_key()` reads `nav_items`. **Step 3 is BUILT** (db/129): Settings → Navigation
(`html/settings/navigation/`, `web/app/(app)/(shell)/settings/navigation/`) — rename, regroup,
reorder, the three statuses — and DISABLED closes an application at three doors, see "How
disabled is enforced". **Extended 2026-09-22: headings and links.** A super-admin adds, renames and
removes (empty) groups, and adds, edits and deletes entries — see "Links: entries of the
super-admin's own". Steps 4–6 are not built.

## Why

The sidebar is a PHP array, `module_catalog()` in `app/business.php`: 29 rows of
group / key / label / url / icon / module grant. Three things follow from that, all unwanted:

1. **Adding an application means a code change and a deploy.** The `applications` table already
   registers the 23 built-in modules and any external system — but the sidebar does not read it,
   so a newly registered application never appears in the menu.
2. **A business cannot switch off what it does not use.** A shop with no stock still sees
   Products & Stock; the only lever today is withholding the module grant, member by member —
   and admins see everything regardless.
3. **The grouping is one opinion, frozen in code.** We regrouped it once already (d493352) and
   the owner expects to again. That should be an edit on a settings screen, not a commit.

## Database, not a JSON file

| | Database | JSON file |
|---|---|---|
| Change without a deploy | yes — a settings screen | no — edit a file on the server |
| Per-business (tenant) menus | natural: each tenant has its own DB | one file per tenant to ship and keep |
| Per-person hide/show | a row per person | impossible in a shared file |
| Joins to what already decides visibility (module grants, `application_access`, roles) | one SQL function | re-implemented in PHP |
| Agents/MCP can answer "what applications do we have / turn X off" | yes, same tables | no |
| Audit trail (`log_activity`) | yes | no |

**Recommendation: the database.** A JSON file survives only as the *seed*: the migration inserts
today's catalog, so a fresh tenant starts with the Option A menu.

## Schema (one additive migration, next free number — db/127 at the time of writing)

**`nav_groups`** — the headings.
`id`, `name` (may be `''`: the unheaded top group), `sort_order`, timestamps.

**`nav_items`** — one row per sidebar entry.

| column | meaning |
|---|---|
| `item_key` (unique) | today's catalog key (`contacts`, `my-work`…); `nav-<key>` DOM ids and the smokes depend on it |
| `application_id` → `applications` (nullable) | which registered application this entry opens. Several entries may share one (`platform` → Dashboard, My Work, Activity, Company, Settings), which is why this is its own table and not columns on `applications` |
| `group_id` → `nav_groups`, `sort_order` | where it sits |
| `label`, `icon`, `url` | what it shows and opens |
| `opens` | `same` (a screen of ours) or `new_tab` (an external application's URL) |
| `module` | the module grant that admits a member (null = no grant needed) — moves here from the catalog |
| `audience` | `everyone` / `internal` (hidden from external members — Company today) / `admin` (Departments, People today). Replaces the three `if`s in `nav_modules()` |
| `active_patterns text[]` | path patterns that light this item up (`/quotes`, `/payments` → invoices). Replaces the hard-coded `NAV_OWNER` table in `web/lib/nav.ts` |
| `status` | **the business-wide switch**: `active` / `hidden` / `disabled` — see below |
| `is_locked` | true for Dashboard, My Work, Settings: cannot be disabled or hidden (nobody can lock themselves out of the screen that undoes it) |

**`member_nav_hidden`** (`member_id`, `nav_item_id`, PK both) — a person's own "I don't use this".

**`app_nav()`** — a SQL function returning the current member's menu, in order: enabled items ∩
audience ∩ (`app_has_module(module)` or admin, exactly today's rule) ∩ for external applications
a live `application_access` grant, minus the member's hidden rows. One gatherer, the same idea as
`app_my_work()`: the session endpoint, the MCP tool and the settings preview all call it.

RLS/grants follow the existing pattern (`app_rw` policy, `app_records_ro` read through an
`mcp_nav` view with `security_barrier`).

## Three statuses, plus a personal hide

Every entry has one status, set by a super-admin in Settings → Navigation (owner, 2026-09-20):

| Status | Sidebar | People by URL | Agents and MCP |
|---|---|---|---|
| **active** | shown | yes | yes |
| **hidden** | not shown | yes | yes — the application works, it just has no menu entry |
| **disabled** | not shown | no — `require_module()` refuses | no — its tools refuse, `app_my_work()` skips its section |

Data is never touched by a status change; going back to `active` restores everything. A locked
entry (Dashboard, My Work, Settings) can only be `active` — a check constraint, not a convention.

Separately, **any member may hide an entry from their own menu** (`member_nav_hidden`): gone
from *their* sidebar only; their grants, the screens and everyone else are unaffected. Hide
only — a person does not reorder their menu.

## How disabled is enforced (built, db/129)

Handlers gate in many ways (`require_module()`, `require_insider()`, the people rule) and many
read views are gated on something other than the module grant, so no single existing gate could
close an application. Three doors, each where everything already passes:

| Door | What it closes | How |
|---|---|---|
| `refuse_disabled_application()` — the end of `app/bootstrap.php` | every PHP screen and write handler, for a person AND for the actions MCP server (it POSTs to the same paths) | `app_path_closed(path)`: the entry whose address or `active_patterns` is the longest prefix of the request path owns it; disabled ⇒ 403 with the entry's name |
| `mcp/module_status.py`, called from `agent_grants.install()` | the read servers' tools — not listed, and refused if called, for people's tokens and agents alike | a tool belongs to the application whose `business_*.py` registered it (`OWNER`); `app_disabled_modules()` |
| `app_has_module()` and `app_can_see()` | the row rule behind the `mcp_*` views, `app_nav()`, `app_my_work()` | `app_module_enabled(module)` — true unless EVERY entry carrying that grant is disabled |

Verified with Products & Stock, as the super-admin: active → listed, screen and tool answer;
hidden → not listed, screen and tool still answer; disabled → not listed, screen and write
handler 403, `find_products` gone from the tool list and refused by name. **Known limits:**
the records server's free-form `search` tool can still read a disabled application's views that
are not gated on its grant; a module's own settings pages under `/settings/…` stay open; a new
`business_*.py` must be added to `OWNER`. Entries of the platform itself that no grant guards
(Activity, Company, Departments) can be hidden but not disabled.

## Links: entries of the super-admin's own (built 2026-09-22)

A **link** is a `nav_items` row with no `application_id`: the super-admin adds it on Settings →
Navigation (each group's *Add entry*, `/settings/navigation/items/new?group=<id>`), giving it a
name, an icon, a group, a status and an **address** — a path of ours (`/reports/sales`) or a full
web address (`https://…`; `nav_url_problem()` refuses anything else) — and whether it **opens in
this tab or a new tab** (`opens`). Its key is `link-<slug of the label>`, made unique with a
number, immutable as every key is. It carries no module and no application, so it admits
everyone who sees the menu (`app_nav()` unchanged); it can be `active` or `hidden` — there is
nothing of its own to switch off, so never `disabled`.

What may be edited and deleted follows one rule (`nav_item_address_editable()`,
`nav_item_deletable()` in `app/features/navigation/queries.php`, presented as `address_editable`
and `deletable`):

| entry | name, icon, group, status | address and opens | delete |
|---|---|---|---|
| a link (no application) | yes | yes | yes |
| an external application's entry | yes | yes | yes |
| a built-in application's entry | yes | no — the address is the application's own; add a link and hide this entry instead | no — hide it, it is there to bring back |
| a locked entry (Dashboard, My Work, Settings) | name, icon, group | no | no |

Handlers: `item-save.php` without `item` adds (log `nav_item.save`, `record_id` returned);
`item-delete.php` (log `nav_item.delete`; `member_nav_hidden` rows go by cascade). A built-in's
`url`/`opens` sent to `item-save.php` are ignored, not refused. Groups: `group-save.php` without
`group` adds a heading (last), `group-delete.php` removes only an empty one — both were built with
step 3. Verified 2026-09-22 as member 1 through the action-token path: add (full URL, new tab),
key made unique on a second add, the link in `/api/v1/session`, edit to a path in this tab,
`disabled` refused for a link, a built-in's address change ignored, delete refused for a built-in
and a locked entry, a group with entries refused, then links and group deleted; every write logged.

## What changes in code

**PHP**
- `nav_modules()` becomes `SELECT * FROM app_nav()` grouped — same return shape, so
  `html/api/v1/session.php` barely changes; items gain `opens` and `active_patterns`.
- `module_catalog()` is deleted. `module_by_key()` (used by `app/features/modules/stub.php`)
  reads `nav_items`.
- `has_module()` additionally requires that the module is not `disabled` (every entry carrying
  that module grant is disabled ⇒ the module is closed). The actions and records MCP servers
  apply the same test before a tool of that module runs.
- New slice `html/settings/navigation/` (gate `super`): `index.php` (read, JSON via a presenter
  in `app/features/navigation/present.php`), `group_save.php`, `group_delete.php`,
  `item_save.php`, `item_toggle.php`, `reorder.php`; and `html/me/navigation/toggle.php` for
  the personal hide. Every write: `require_post()` + `verify_csrf()` + gate + `log_activity()`
  + `emit_action_status()`; template-less, so each says its own refusals
  (`respond_invalid($errors)`), per the post-cut-over rule.
- Applications create/edit gains a **"Show in the menu"** section (group, label, icon, URL,
  opens) that writes the `nav_items` row — this is how "add an application at any time" happens
  with no code.

**React**
- `web/lib/api.ts`: `NavItem` gains `opens`, `active_patterns`. `web/lib/nav.ts`: `NAV_OWNER`
  goes; `activeNavKey()` reads patterns from the items. The `/` → `/dashboard` special case
  becomes data too (the seed stores `/dashboard`).
- `Shell.tsx`: external items render `<a target="_blank" rel="noopener">` with an
  external-link icon; nothing else changes — it already renders whatever groups arrive.
- Screens (nxl look, no modals, 375px): **Settings → Navigation** — groups as cards, items as
  rows with a three-way status (Active / Hidden / Disabled), rename, icon, move up/down and move-to-group (buttons, not
  drag-and-drop: works on a phone and by keyboard); a "Preview as…" member picker fed by
  `app_nav()`. **Profile → My menu** — a checklist of the member's available items.

**Agents / MCP**
- Records server: `navigation_list` (what is in the menu, what is off, for whom).
- Actions server + manifest: `nav_item_set_status`, `nav_item_move`,
  `nav_group_save` (super-admin only; approval policy: none needed — reversible, no data
  touched). Manifest notes obey the no-comma / no-trailing-note rule.
- Smoke `mcp/smoke/2x-navigation.json`: create a `SMOKE <run>` group and link item, disable it,
  assert the session payload drops it, re-enable, delete.

## Order of work

1. **Migration + seed + `app_nav()`**; `nav_modules()` reads it. Byte-for-byte the same menu as
   today — verified by diffing `/api/v1/session` before and after for member 1, an ordinary
   user and an external member. *Shippable alone; the menu is now data.*
2. **Active patterns + external links** in React; delete `NAV_OWNER` and `module_catalog()`.
3. **Settings → Navigation** (rename, regroup, reorder, the three statuses) + closing a
   `disabled` module to people, agents and MCP + activity logging.
4. **"Show in the menu" on Applications** — adding an application end to end.
5. **Profile → My menu** (personal hide).
6. **MCP tools, manifest entries, smoke, docs** (CLAUDE.md "23 built-in modules" paragraph,
   requirements + build plan, under the sync rule).

Steps 1–2 are mechanical; 3–5 are one ordinary slice each.

## Risks and how they are handled

- **Locking yourself out** — `is_locked` items; the last enabled route to Settings can never be
  disabled; super-admin can always reach `/settings/navigation` by URL.
- **Every page reads the session** — `app_nav()` is one indexed query over ~30 rows; React
  already caches `getSession()` per request. No extra cache layer.
- **A disabled module with work in flight** (open approvals, scheduled agent duties) — the
  disable screen shows what is pending and asks for confirmation on a full page; agent duties
  for a closed module fail with a clear refusal rather than silently.
- **Keys are load-bearing** (`nav-<key>` ids, smokes, `activeNav`) — `item_key` is immutable
  after creation; only the label is renameable.

## The owner's decisions (2026-09-20)

1. **Three statuses per application** — ACTIVE (in the sidebar), HIDDEN (works for agents and
   MCP, not in the sidebar), DISABLED (not shown, and closed to agents and MCP).
2. **Super-admin only** arranges the menu.
3. **No per-department menus now**; the schema leaves room (`nav_item_departments`).
4. A person may **hide** entries from their own menu, **not reorder** them.
