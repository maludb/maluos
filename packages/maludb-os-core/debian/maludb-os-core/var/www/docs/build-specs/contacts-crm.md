# Build spec: Contacts & CRM slice (BUSINESS OS EXEMPLAR)

2026-09-17 · build plan 1.7 / 1.9 · written and built by the planning-class model

This is the first Business OS slice. It becomes the canonical reference every later slice
replicates: *"build exactly like the Contacts/CRM slice, applying this spec."* Later specs use
`docs/build-specs/business-os-slice-template.md` and name only their substitutions.

Module grant: `contacts` · Manifest section: **Contacts & CRM** (`docs/business-os-action-manifest.md`)
Schema tables (never modify): `organizations`, `contacts`, `pipelines`, `deal_stages`, `deals`,
`interactions` (`db/031_contacts_crm.sql`), plus the cross-cutting `tags`, `taggings`,
`record_comments` (`db/030_business_foundation.sql`).
Read views: `mcp_organizations`, `mcp_contacts`, `mcp_deals`, `mcp_pipelines`, `mcp_interactions`,
`mcp_tags`, `mcp_taggings`, `mcp_record_comments`, `mcp_team_directory`, `mcp_departments`.
Questions this slice answers: C1–C16, DB4 (record) and the CRM activity questions.

## Gate and visibility

- **Module gate:** `mod:contacts` — `require_module('contacts')` at the top of every endpoint,
  GET and POST. `organization_merge`, `contact_merge`, `*_delete` and `contact_enable_portal` are
  `admin` — `require_business_admin()`.
- **Reads go through the `mcp_*` views only.** `db/063_app_read_views.sql` grants `SELECT` on
  every `mcp_*` view to `app_rw`, so a screen shows a person exactly the rows an agent would show
  them, decided once in `app_can_see()`. **A list or detail screen never selects a base table.**
- **Writes go to base tables**, after `require_module()` **and** `can_see_record()` on the target
  row (RLS for `app_rw` is permissive by design — the app is the gate).
- **Department stamping:** `department_id` on an organization, contact or deal is chosen on the
  form from the member's departments (super-admin: any). Blank means "no department", which is
  visible to any holder of the module grant — the form says so.
- **Owner:** defaults to the creating member; changeable by an admin or the current owner.

## Screens

| Screen id | Canonical URL | When the user wants… | Params |
| --- | --- | --- | --- |
| `contacts-list` | `/contacts/` | to browse or search people and companies | `q`, `kind`, `type`, `tag`, `owner`, `page`, `sort` |
| `organization-add` | `/contacts/organizations/new` | to add a company | `name`, `type` |
| `organization-view` | `/contacts/organizations/{id}` | a company's full picture | `tab` |
| `organization-edit` | `/contacts/organizations/{id}/edit` | to edit a company | — |
| `contact-add` | `/contacts/people/new` | to add a person | `name`, `organization`, `email` |
| `contact-view` | `/contacts/people/{id}` | a person's details and conversations | — |
| `contact-edit` | `/contacts/people/{id}/edit` | to edit a person | — |
| `contacts-hygiene` | `/contacts/hygiene` | contacts with no owner and probable duplicates | `check` |
| `deals-board` | `/deals/` | the pipeline board | `pipeline`, `owner`, `closing`, `quiet` |
| `deal-add` | `/deals/new` | to add a deal | `organization`, `title`, `value` |
| `deal-view` | `/deals/{id}` | one deal with its interactions and history | — |
| `deal-edit` | `/deals/{id}/edit` | to edit a deal | — |
| `interaction-add` | `/interactions/new` | to log a call, email, meeting or note | `kind`, `organization`, `contact`, `deal` |
| `pipelines-settings` | `/settings/pipelines` | to edit pipelines and stages | — |

Canonical URLs are served directly: the shell conversion (1.8) enables `mod_rewrite` with three
generic rules (`{module}/new` → `form.php`, `{module}/{id}` → `view.php?id=`, `{module}/{id}/edit`
→ `form.php?id=`), each guarded by `RewriteCond -f`. **Never `hx-push-url="true"`** — always the
canonical URL above.

## List screen (`contacts-list`)

One list over both kinds (a `UNION ALL` of `mcp_organizations` and `mcp_contacts`), so "find
Acme" works without knowing whether Acme is a company or a person.

- Columns in order: **Name** (link to the record's view) · **Kind** (badge: Company `info`,
  Person `secondary`) · **Relationship** (`relationship_types[]` as badges) · **At / People**
  (a person's organization name; a company's contact count) · **Owner** (`owner_name`, "—" when
  unowned) · **Updated** (`updated_at`, medium date) · **Actions** (Edit).
- Search (`q`) matches organization `name`/`legal_name`/`email` and contact
  `full_name`/`email`/`phone`/`mobile`, case-insensitive substring (trigram indexes exist).
- Filters: `kind` ∈ `both` (default) | `organization` | `person`; `type` ∈ the four
  `relationship_types`; `owner` = member id, or `none` for unowned; `tag` = tag id.
- Sort allowlist: `name`, `updated_at` (default `updated_at DESC`). Page size 25, server-rendered
  pagination.
- Empty state: "No contacts match “{q}”." / "No contacts yet. Add the first company or person."
- The results region (`#contacts-list-results`) refreshes itself on `organizationChanged`,
  `contactChanged` and `taggingChanged`.

## Detail screens

**`organization-view`** — header: name, relationship badges, owner, department, website, phone,
email, tags. Panels in order: **People** (`mcp_contacts` by organization, primary first) ·
**Deals** (`mcp_deals`, open first, value + stage) · **Interactions** (timeline, latest 20, "Log
interaction" button) · **Comments** (`mcp_record_comments`). Invoices, projects and tickets get
their panels when those slices land — the panel stubs are **not** built now.

**`contact-view`** — header: full name, job title, organization link, contact methods, owner,
tags, primary-contact badge. Panels: **Deals** (where this contact is the primary contact) ·
**Interactions** (timeline, latest 20) · **Comments**.

**`deal-view`** — header: title, organization, primary contact, value + currency, stage badge,
probability (override or the stage's), expected close, owner, age in stage. Panels: **Stage
actions** (move stage select, Mark won, Mark lost) · **Interactions** · **Comments**.

Every detail partial stamps `data-screen`, `data-entity` and `data-record-id` on `#page-content`.

## `deals-board`

Kanban: one column per `deal_stages` row of the selected pipeline (default pipeline first),
ordered by `sort_order`; each column header shows the stage name, deal count and value total
**per currency**. Cards show title, organization, value, expected close date, owner initials, and
a "quiet" warning dot when `stage_entered_at` is older than `business_settings.deal_quiet_days`.
Filters: `pipeline`, `owner`, `closing` (`this_month` | `this_quarter`), `quiet` (`1`).
**Mobile (≤ 767px): the columns stack vertically**, each collapsible, no horizontal scroll.
Moving a deal is a form action (`deal_move_stage`), not drag-and-drop — a select on the card's
menu and on the detail page; Pattern C re-renders the affected columns.

## `contacts-hygiene`

Two tables from `contact_hygiene`'s rules: **No owner** (organizations and contacts with
`owner_member_id IS NULL`) and **Probable duplicates** (trigram similarity ≥ 0.6 on
`organizations.name` / `contacts.full_name`, or an exact email match), each row offering Merge
(admin) and Open. `check` ∈ `no_owner` | `duplicates` | `both` (default).

## Forms

**Organization form** (`organization-add` / `organization-edit`), ids `organization-form-field-{name}`:

| Field | Input | Required | Validation |
| --- | --- | --- | --- |
| name | text | ✔ | 1–200 |
| legal_name | text | — | ≤ 200 |
| relationship_types | checkboxes (customer, vendor, lead, partner) | — | subset of the four |
| email | email | — | valid or empty, ≤ 254 |
| phone | text | — | ≤ 40 |
| website | url | — | valid URL or empty |
| industry | text | — | ≤ 80 |
| address (line1, line2, city, region, postal, country) | text ×6 | — | each ≤ 120 → `address` jsonb |
| tax_id | text | — | ≤ 40 |
| owner_member_id | select (team directory) | — | a member id the caller can see; default self |
| department_id | select (my departments; super-admin: all) | — | one of them, or blank |
| source | text | — | ≤ 60 |
| payment_terms_days | number | — | 0–365, blank = business default |
| currency | select (ISO codes in use + base) | — | 3 letters, blank = base currency |
| notes | textarea | — | ≤ 10000 |

**Contact form** (`contact-add` / `contact-edit`), ids `contact-form-field-{name}`:
`first_name`, `last_name`, `full_name` (✔ 1–200; auto-filled from first+last when left blank),
`organization_id` (select, searchable), `job_title` (≤ 120), `email`, `phone`, `mobile`,
`is_primary_contact` (checkbox — saving it clears any other primary in that organization, which
is what the partial unique index enforces), `relationship_types`, `owner_member_id`,
`department_id`, `source`, address ×6, `notes`.

**Deal form** (`deal-add` / `deal-edit`), ids `deal-form-field-{name}`:
`title` (✔ 1–200), `organization_id`, `primary_contact_id` (options limited to that
organization's contacts), `pipeline_id` (✔ default pipeline), `stage_id` (✔ options from the
chosen pipeline, reloaded by a Pattern A fragment when the pipeline changes), `value` (≥ 0,
default 0), `currency` (✔ default base), `probability_override` (0–100, blank = the stage's),
`expected_close_date` (date), `owner_member_id`, `department_id`, `source`, `description`.

**Interaction form** (`interaction-add`), ids `interaction-form-field-{name}`:
`kind` (✔ call/email/meeting/message/note), `direction` (inbound/outbound; blank for note),
`occurred_at` (✔ datetime-local in the member's timezone → UTC via `local_to_utc()`, default now),
`organization_id`, `contact_id`, `deal_id` (**at least one required** — the table's CHECK),
`subject` (≤ 200), `body` (≤ 20000), `duration_minutes` (0–1440).

**Pipelines settings** (`pipelines-settings`): a pipeline list with inline add/rename/default
toggle, and per pipeline an inline stage editor (name, kind open/won/lost, probability,
sort_order) using the exemplar's inline-child-row pattern (`hx-include="closest tr"`, region
re-render). Admin only.

No modals anywhere; forms are full pages in `#page-content`; save/cancel live in the page header.

## Files (exactly these — no additions) — AS BUILT

```
html/contacts/index.php · hygiene.php
html/contacts/organizations/form.php · view.php · save.php · archive.php · merge.php · delete.php
html/contacts/people/form.php · view.php · save.php · primary.php · archive.php · merge.php · delete.php
html/deals/index.php · form.php · view.php · save.php · stage.php · won.php · lost.php · delete.php
html/deals/stages-fragment.php · contacts-fragment.php          (Pattern A selects)
html/interactions/form.php · save.php · delete.php · timeline.php
html/settings/pipelines/index.php · save.php · stage-save.php
html/tags/add.php · remove.php
html/comments/save.php · delete.php

app/features/contacts/queries.php · render.php
app/features/deals/queries.php · render.php
app/features/records/queries.php        (tags, comments, entity gate — shared by every slice)

app/views/contacts/page.php · hygiene.php
app/views/contacts/partials/table.php · row.php · form-organization.php · form-contact.php
                              · form-interaction.php · organization.php · contact.php
app/views/deals/page.php · view.php
app/views/deals/partials/board.php · card.php · form.php · stage-options.php · contact-options.php
app/views/settings/pipelines.php · partials/stage-row.php
app/views/shared/tags.php · comments.php · comment-list.php · interactions.php
                          · interaction-list.php · owner-select.php · department-select.php

mcp/business_contacts.py                (the slice's eight tools, registered by records_server.py)
```

**Two additions to the planned list, both structural and both replicated by later slices:**

1. **`render.php` per feature.** A write endpoint answers with a whole refreshed screen, and
   three or four endpoints answer with the *same* screen, so the re-render lives in one
   function (`render_organization_page()`, `render_deal_page()`, …) rather than being pasted
   into each handler. The exemplar's dual-endpoint rule is unchanged; this is where its
   success branch lives.
2. **A `*-list.php` fragment behind every self-refreshing region.** The timeline and the
   comment thread are rendered on first paint *and* by their Pattern A endpoint, so the list
   markup is its own partial and both paths emit identical HTML. A slice with a live region
   does the same.

There is no separate `board.php` column partial: a column is six lines inside `board.php`, and
splitting it would have hidden the per-currency totals from the file that computes them.

## Query functions (signatures fixed; PDO first, no request/response awareness)

```php
// app/features/contacts/queries.php
const CONTACTS_PAGE_SIZE = 25;
const CONTACTS_SORT_ALLOWED = ['name', 'updated_at'];
find_contact_records(PDO, string $q, string $kind, string $type, ?int $ownerId, bool $unownedOnly,
                     ?int $tagId, string $sort, int $page): array   // unified list + total_count
find_organization(PDO, int $id): ?array                 // mcp_organizations
find_person(PDO, int $id): ?array                       // mcp_contacts
find_people_for_organization(PDO, int $orgId): array
insert_organization(PDO, array $f): array               // $f keys = the form fields above
update_organization(PDO, int $id, array $f): array
archive_organization(PDO, int $id, bool $archived): array
merge_organization(PDO, int $sourceId, int $targetId): array   // repoint contacts/deals/interactions, set merged_into_id, archive
delete_organization(PDO, int $id): bool                 // refused when invoices exist (FK RESTRICT → friendly message)
insert_person(PDO, array $f): array
update_person(PDO, int $id, array $f): array
set_primary_contact(PDO, int $id): array                // clears the org's previous primary
archive_person(PDO, int $id, bool $archived): array
merge_person(PDO, int $sourceId, int $targetId): array
delete_person(PDO, int $id): bool
find_interactions(PDO, string $scope, int $id, int $limit = 20): array   // scope: organization|contact|deal
find_interaction(PDO, int $id): ?array
insert_interaction(PDO, array $f): array
update_interaction(PDO, int $id, array $f): array
delete_interaction(PDO, int $id): bool
find_unowned_records(PDO): array
find_probable_duplicates(PDO, float $similarity = 0.6): array

// app/features/deals/queries.php
find_pipelines(PDO): array                              // mcp_pipelines, grouped
find_stages_for_pipeline(PDO, int $pipelineId): array
find_deals_board(PDO, int $pipelineId, ?int $ownerId, string $closing, bool $quietOnly, int $quietDays): array
find_deals_for(PDO, string $scope, int $id): array      // scope: organization|contact
find_deal(PDO, int $id): ?array
insert_deal(PDO, array $f): array
update_deal(PDO, int $id, array $f): array
move_deal_stage(PDO, int $id, int $stageId): array      // sets stage_entered_at; closed_at on won/lost
close_deal(PDO, int $id, string $outcome, ?string $reason): array
delete_deal(PDO, int $id): bool
upsert_pipeline(PDO, ?int $id, string $name, bool $isDefault): array
upsert_stage(PDO, int $pipelineId, ?int $id, string $name, string $kind, float $probability, int $sort): array

// app/features/records/queries.php  (shared)
find_tags(PDO): array
add_tagging(PDO, string $entityType, int $entityId, string $tagName): array   // creates the tag if new
remove_tagging(PDO, string $entityType, int $entityId, int $tagId): bool
find_taggings(PDO, string $entityType, int $entityId): array
find_record_comments(PDO, string $entityType, int $entityId): array
insert_record_comment(PDO, string $entityType, int $entityId, string $body): array
delete_record_comment(PDO, int $id): bool
```

## Action-manifest entries (copied from the manifest — unchanged)

`organization_create`, `organization_update`, `organization_archive`, `organization_merge` (✔ admin),
`organization_delete` (✔ admin, agent-approval `delete`), `contact_create`, `contact_update`,
`contact_set_primary`, `contact_archive`, `contact_merge` (✔ admin), `contact_delete` (✔ admin,
`delete`), `deal_create`, `deal_update`, `deal_move_stage`, `deal_mark_won`, `deal_mark_lost`,
`deal_delete` (✔ admin, `delete`), `interaction_log`, `interaction_update` (own),
`interaction_delete` (✔ own, `delete`), `pipeline_save` (admin), `pipeline_stage_save` (admin),
`tag_add`, `tag_remove`, `comment_add`, `comment_delete` (✔ own, `delete`).

Each endpoint: `require_post()` → `verify_csrf()` → gate → approval check → write →
`log_activity()` → `HX-Trigger: {entity}Changed` (`organizationChanged`, `contactChanged`,
`dealChanged`, `interactionChanged`, `taggingChanged`, `commentChanged`).

**`contact_enable_portal` is NOT built in this slice** — see Open Questions. It moves to the
Customer portal & forms slice (phase 4), which owns portal accounts.

## Approval awareness (the pattern every later slice copies)

`approval_required(PDO, string $action, ?float $amount, ?string $currency): ?array` matches the
active `approval_policies` rows against the acting member: `applies_to='agents'` matches any
member whose `member_kind='agent'`, `'agent'` that one agent, `'department'` a member of that
department, `'everyone'` everyone; `action_pattern` matches the log event exactly or as
`prefix.*` / `*.suffix`; an `amount_threshold` matches only at or above it in that currency.
On a match the endpoint calls `create_approval_request(...)`, emits
`emit_action_status(false, ['status' => 'pending_approval', 'approval_request_id' => N])` plus a
message partial, and **writes nothing else**.

**Approver resolution:** `policy.approver_member_id`, else the requester's manager
(`agent_profiles.manager_member_id` for an agent), else the manager of the requester's department,
else the lowest-id active `super_admin`. Requests expire after `expires_after_hours`.

In this slice only the `*.delete` policy can fire, and only for agents; no agent exists yet, so
the path is proved by a fixture test (a member with `member_kind='agent'` attempting
`organization_delete`), not by a live agent.

## Activity log events

`organization.create/update/archive/merge/delete` · `contact.create/update/set_primary/archive/merge/delete`
· `deal.create/update/move_stage/mark_won/mark_lost/delete` · `interaction.create/update/delete`
· `pipeline.save` · `deal_stage.save` · `tag.add/remove` · `record_comment.create/delete`
· `screen.view` on every GET screen with the screen id above.

`before` / `after` carry the changed record; `deal.*` rows carry `value` and `currency` in `after`
so the money-threshold policies and the audit views work.

## MCP tools this slice must leave working

`find_contacts`, `get_organization`, `get_contact`, `get_deal`, `pipeline`, `sales_performance`,
`contact_hygiene`, `lead_sources` — all read the views listed above, which already exist. The
slice's acceptance includes asking each of these through the records server against data created
in the UI (`get_organization` after creating one, `pipeline` after moving a deal).

## Status vocabulary mapping

- Deal stage: `open` → `info` · `won` → `success` · `lost` → `danger`; a quiet deal adds a
  `warning` dot. Archived record → `secondary`. Relationship badges: customer `success`,
  vendor `info`, lead `warning`, partner `dark`.

## Out of scope for this slice

- Invoices, projects, tickets and their panels on `organization-view` (their own slices add them).
- `contact_enable_portal`, portal logins, record shares with externals.
- Drag-and-drop on the board; bulk import/export; deduplicate-on-write.
- Campaign / content attribution UI (`source_campaign_id` is stored, not edited here).
- Any change to the cert-study modules, which keep running untouched.

## Open Questions (escalated — answer before the portal slice, not before this one)

1. **Portal enablement has no contact link.** `contact_enable_portal` needs the accepted
   invitation to set `contacts.portal_member_id`, but `invitations` has no `contact_id` column;
   matching by email is a guess when two contacts share an address. Options: add
   `invitations.contact_id` in a later migration, or make the portal slice own the whole flow.
   Deferred to the Customer portal & forms slice; not built here.
