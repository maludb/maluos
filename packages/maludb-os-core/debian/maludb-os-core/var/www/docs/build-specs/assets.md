# Build spec: Assets (one register, physical and technical)

> Plan approved by the owner 2026-09-21 with all five defaults. Schema `db/131` (register) and
> `db/132` (depreciation). Built on the React slice template, cards from `web/components/kit/RecordCard.tsx`.
> **The URL is `/asset-register/`** — `/assets/` is the static files directory (css, images) and can
> never be a screen. The module key, the grant and the tables are still `assets`.

## The idea

One register of what the business owns and operates. **Every asset belongs to a department and
sits at a location** (both required); it may have a custodian — a person **or an agent**.

- **Physical**: computers, phones, servers and network gear, printers, vehicles, furniture,
  equipment, premises.
- **Technical**: relational databases (PostgreSQL 17), memory systems (MaluDB), MCP servers and
  APIs, AI models and provider accounts, domains, certificates and keys, licences, cloud accounts,
  backups, repositories. Seeded: `A-0001 PostgreSQL 17`, `A-0002 MaluDB memory`, under IT at the
  Main Office, each linked to its applications row.

It links to what exists and duplicates none of it:

| Existing | Relation |
|---|---|
| Applications | `assets.application_id` — the application a technical asset stands behind. Endpoints, access, health and agent tool grants stay in Applications. **An asset grants nothing.** |
| Work Locations | `assets.location_id`. Machine specs stay on the location; a desk's laptop is an asset *at* that desk. |
| Calendar | `assets.bookable_resource_id` — a vehicle or a room is booked in Calendar, registered here. (Closes the requirements' open question on physical assets.) |
| Expenses | `assets.recurring_expense_id` — what it costs to run. |
| Documents | `document_links` with `entity_type = 'asset'`. |
| Books | Depreciation, on demand (below). |
| My Work | Section `assets_due` in `app_my_work()`: open maintenance, warranty ending, renewal — within max(horizon, 30) days — for assets you hold, departments you administer, or all with the grant. |

## Schema

`asset_categories` (class, icon, default useful life; seeded, editable; the class is fixed once
saved; archive, never delete) · `assets` (tag `A-0001` from `asset_tag_seq`; status planned /
in_service / in_repair / in_storage / retired / disposed / lost; parent asset = "runs on" / "part
of"; `serial_number` holds a serial or an account/licence **reference — never a secret**) ·
`asset_movements` (one row per change of department, location or custodian; the first is
"Registered") · `asset_maintenance` · `asset_depreciation`.

**Visibility** — `app_can_see_asset(custodian, department)`: the Assets grant or super-admin sees
the register; a dept-admin their departments' assets; a custodian what they hold; externals
nothing. **Money** (purchase cost, salvage, maintenance cost, recurring expense, depreciation) is
masked in the views unless `app_can_manage_asset(department)` — the grant, or the department's
administrator. Note this is deliberately NOT `app_can_see()`: that rule scopes a grant holder to
their own departments, and an asset register needs one person who sees all of it.

## Screens (cards)

`assets-list` `/asset-register/` — cards grouped by department (`?group=location|category`),
filters class / department / location / category / status / due / gone / q; in-use assets solid,
planned and gone ones muted. `asset-view` — tabs Overview, History, Maintenance, Documents,
Depreciation (managers only); the side cards move it (`asset_assign`), set its status and mark it
gone. `asset-add` / `asset-edit` — a new asset is placed on the form; an existing one is moved
only from its page, so every move is a movement row. `asset-categories`, `asset-depreciation`.
An "Assets" card (`AssetLinksCard`) sits on the location, department, application, person and
agent pages.

## Actions

`asset_save`, `asset_assign` (partial: a caller names only what changes), `asset_set_status`,
`asset_verify` (manager or custodian), `asset_dispose` (mod:assets; confirm; agents need approval),
`asset_maintenance_save`, `asset_maintenance_complete`, `asset_category_save`,
`asset_depreciation_post` (mod:assets AND mod:books; confirm; agents need approval). Gate
otherwise: mod:assets, or a dept-admin within their departments — who can only move an asset into
a department they administer. `/asset-register/save.php` is a partial-update target.

## MCP tools (records server, `mcp/business_assets.py`, module `assets`)

`find_assets`, `get_asset`, `asset_summary`.

## Depreciation (db/132)

Straight line, whole cents, from the month of purchase: `(purchase_cost - salvage_value)` over
`useful_life_months`. **Posted by a person for a month, never automatically.** Posting a month
brings every asset up to what it should have accumulated by the end of it — a late start catches
up in one entry, a month posted twice posts nothing, the last month of a life takes the remainder.
One journal entry per currency (`source = 'depreciation'`): debit **6600 Depreciation** with a
line per department, credit **1510 Accumulated depreciation**; one `asset_depreciation` row per
asset. Undo = reverse the entry in Books. `app/features/assets/depreciation.php`.

## Proof

- `mcp/smoke/23-assets.json` — 15 steps, writes `SMOKE <run>` assets (left disposed / retired).
  It does **not** post depreciation: a posted entry is permanent.
- `php bin/test_asset_depreciation.php` — the whole posting chain inside one transaction, rolled
  back (the `bin/test_ai_usage_posting.php` precedent). It consumes two asset tags each run —
  a sequence does not roll back — so tags have gaps; that is harmless.

## Open Questions

- Disposal posts nothing to the books (no gain/loss entry, no write-off of the remaining book
  value). A person books that by hand today.
- Purchase cost is not posted to 1500 Fixed assets by this module — it arrives through Expenses
  or a manual entry, as before.
