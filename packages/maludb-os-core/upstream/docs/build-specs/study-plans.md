# Build spec: study-plans + items + comments + copy slice (Phase 3, slice 5)

Exemplar: **exam-catalog** (canonical patterns). Also mirror the **exam-catalog inline child-row editor** for plan items (like domains: `hx-include="closest tr"`, region refresh). Member-facing. Built after resources so items can link a resource.

Schema tables: `study_plans`, `plan_items`, `plan_comments`. Reference: `exam_attempts`, `exams`, `exam_domains`, `resources`, `members`.

Visibility: a plan is readable if `visibility='community' OR member_id=me OR organizer`. Only the **owner** edits the plan, its items, visibility, archive, and copy target; **any member** may comment on a community-visible plan.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `plans-list` | `/plans/` | Browse plans (mine + community) |
| `plan-add`   | `/plans/form.php` | Create plan |
| `plan-edit`  | `/plans/form.php?id={id}` | Edit plan + inline items editor (owner) |
| `plan-view`  | `/plans/view.php?id={id}` | Read plan, items, progress, comments |

## List (`plans-list`)
- Columns: Title (row link to view; status dot) · Exam (`exams.code`) · Owner · Visibility (community/private icon; "mine" tag) · Progress (`items_completed/items_total`, mini bar) · Times copied · Actions (Edit/Copy if applicable)
- Filters: exam, `mine`/`community`/`from_passers` (from_passers = owner has a passed+shared attempt for the exam), status (active/archived). Sort: `recent`, `most_copied`. Page size 25.

## Detail (`plan-view`)
- Header: title, exam, owner, visibility, status. Approach (markdown → render safely; escape then a minimal renderer or show as pre-wrapped text — do NOT allow raw HTML). Progress summary (on-track = overdue-incomplete count == 0). 
- Items list (read): title, domain, due date, completed check, linked resource link.
- Copy button (`plan_copy`) → pick target attempt → copies plan + items shifting due dates to the new exam date. Comments section: list + add form (`plan_comment_add`) for community-visible plans.

## Form (`plan-add`/`plan-edit`)
- Plan fields: title ✔ · attempt_id (select of my attempts, optional) · exam_id (select ✔; auto-set from attempt if chosen) · approach (textarea, markdown) · visibility (select community/private) · status (select active/archived, edit only). Ids `plan-form-field-{name}`.
- **Inline items editor** (edit only, replicate the exam-catalog domains editor exactly): region `#plan-items-region`, add-row + editable rows via `hx-include="closest tr"`, each row: title, domain (select), due_date, resource (select, optional), completed (checkbox → `plan_item_complete`), reorder up/down, delete. Every op re-renders the region.

## Files
- `/var/www/html/plans/index.php` · `form.php` · `view.php` · `save.php` · `visibility.php` · `archive.php` · `copy.php` · `delete.php`
- `/var/www/html/plans/items/save.php` · `complete.php` · `delete.php` (· `reorder.php` if items are ordered)
- `/var/www/html/plans/comment.php`
- `/var/www/app/features/plans/queries.php`
- `/var/www/app/views/plans/page.php` · `partials/table.php` · `row.php` · `form.php` · `view.php` · `items.php` · `item-row.php` · `comments.php`

## Query functions
- `find_plans(PDO, int $memberId, bool $isOrganizer, array $filters, string $sort, int $page): array` (visibility-filtered; with progress counts + times_copied)
- `find_plan(PDO, int $id, int $memberId, bool $isOrganizer): ?array`
- `insert_plan/update_plan/set_plan_visibility/archive_plan/delete_plan(...)`
- `copy_plan(PDO, int $planId, int $memberId, ?int $targetAttemptId): array` (transaction: new plan + shifted items; set `copied_from_plan_id`)
- `find_plan_items(PDO, int $planId)`, `upsert_plan_item(...)`, `complete_plan_item(PDO,int $id,int $planOwnerId,bool $done)`, `delete_plan_item(...)`, `reorder_plan_items(...)`
- `find_plan_comments(PDO, int $planId)`, `insert_plan_comment(PDO,int $planId,int $authorId,string $body)`
- `plan_progress(PDO, int $planId): array` (items_total, completed, overdue, on_track)

## Action manifest entries
Screens `plans-list/add/edit/view`. Actions `plan_create`, `plan_update`, `plan_set_visibility`, `plan_archive`, `plan_copy`, `plan_item_add`, `plan_item_update`, `plan_item_complete`, `plan_item_delete`, `plan_comment_add` — registered.

## Activity events
`plan.create/update/copy/archive/visibility_change` · `plan_item.create/update/complete/reopen/delete` · `plan_comment.create` · `screen.view`.

## Status vocabulary
Plan `status`: active→success, archived→secondary. Visibility: community (info), private (dark).

## Out of scope
- Rich markdown/HTML in approach (render as safe text). Threaded comment replies. Sharing a private plan by link.

## Open Questions
- (none)
