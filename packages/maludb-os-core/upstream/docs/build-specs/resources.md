# Build spec: resources + endorsements slice (Phase 3, slice 4)

Exemplar: **exam-catalog** (canonical patterns apply). Member-facing. Built **before plans** so plan items can link resources. Any member submits a resource; organizers may hide any; a submitter may edit their own. Endorsement is one-per-member (unique).

Schema tables: `resources`, `resource_exams`, `resource_domains`, `resource_endorsements`. Reference: `exams`, `exam_domains`, `members`, `exam_attempts` (for certified-endorser ranking).

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `resources-list` | `/resources/` | Browse/search resources |
| `resource-add`   | `/resources/form.php` | Submit form |
| `resource-view`  | `/resources/view.php?id={id}` | Detail + endorse |
| (edit)           | `/resources/form.php?id={id}` | Edit own submission / organizer |

## List (`resources-list`)
- Columns: Title (row link to view; type dot) · Type (badge) · Covers (exam codes / domain chips) · Endorsements (total; "N certified" sub-count) · Submitted by · Actions (Endorse toggle + Edit if own/organizer)
- Filters: exam, domain (filtered by exam), type. **Sort allowlist**: `endorsed` (total desc), `certified_endorsed` (certified endorsers desc — the M13 ranking), `recent` (created desc). Default `certified_endorsed`. Full-text search box (`q`) over title/description using `search_tsv @@ plainto_tsquery`. Page size 25.
- Hidden resources: shown only to submitter/organizer (badge "Hidden").

## Detail (`resource-view`)
- Title, type, URL (external link, `rel="noopener"`), description, covered exams/domains, submitted-by, endorsement counts. Endorse/Unendorse button (`resource_endorse`, toggle, Pattern C on the endorse region). Organizer: Hide/Unhide (confirm on hide).

## Form (`resource-add`/edit)
- Fields: title ✔ · url ✔ (valid URL) · type (select enum) ✔ · description (textarea) · exams[] (multi-select of active exams) · domains[] (multi-select, grouped/filtered by chosen exams). Ids `resource-form-field-{name}`.
- Multi-selects: plain `<select multiple>` acceptable (no select2 dependency required); persist to `resource_exams`/`resource_domains` join tables (delete-then-insert in a transaction on save).

## Files — AS BUILT
- `/var/www/html/resources/index.php` · `form.php` · `view.php` · `save.php` · `endorse.php` · `hide.php`
- `/var/www/app/features/resources/queries.php`
- `/var/www/app/views/resources/page.php` · `partials/table.php` · `row.php` · `form.php` · `view.php` · `endorse.php`

**Deviations (as built):**
- **Coverage** uses `<select multiple>` for exams and a **domain multi-select with `<optgroup>` per exam** (no dependent fragment) — simpler than dynamic filtering and covers the many-exams case. Saved via `set_resource_coverage` (delete-then-insert) inside the save transaction.
- **Endorse** returns the **list row** when toggled from the list, or the **`#resource-endorse-region`** when toggled from the detail (distinguished by a `detail` param) — one endpoint, two render targets.
- Ranking `certified_endorsement_count` uses an `EXISTS` passer test (not a join) to avoid double-counting members with multiple shared passes. Verified live.

## Query functions
- `find_resources(PDO, string $q='', ?int $examId=null, ?int $domainId=null, ?string $type=null, string $sort='certified_endorsed', int $memberId=0, int $page=1): array` (includes endorsement_count, certified_endorsement_count, my_endorsed bool; visibility: not hidden OR own OR organizer — pass `$isOrganizer`)
- `find_resource(PDO, int $id, int $memberId, bool $isOrganizer): ?array`
- `insert_resource(PDO, int $memberId, string $title, string $url, string $type, ?string $desc): array`
- `update_resource(PDO, int $id, …fields): array`
- `set_resource_coverage(PDO, int $resourceId, int[] $examIds, int[] $domainIds): void` (transactional replace)
- `set_endorsement(PDO, int $resourceId, int $memberId, bool $on): int` (returns new count)
- `hide_resource(PDO, int $id, int $byMemberId, ?string $reason, bool $hide): array`
- Sort → SQL is an **allowlist map**, never interpolate raw sort input.

## Action manifest entries
Screens `resources-list/add/view`. Actions `resource_create`, `resource_update`, `resource_endorse` (toggle), `resource_hide` † (confirm) — registered. Endpoints as in Files.

## Activity events
`resource.create` · `resource.update` · `resource.endorse`/`resource.unendorse` · `resource.hide` · `screen.view`.

## Status / type vocabulary
Type is descriptive (neutral badge). Hidden → `secondary` + "Hidden" badge.

## Out of scope
- Automatic passer-usage ranking beyond `certified_endorsement_count` (the plan-item/session usage signal, O11, is computed in the MCP views for the AMA; the screen ranks by certified endorsements). Link-health checking. Comments on resources (issues cover discussion).

## Open Questions
- (none)
