# Build spec: issues + replies slice (Phase 3, slice 7)

Exemplar: **exam-catalog** (canonical patterns). Member-facing with **Postgres full-text search** (M5). Any member posts issues/replies; author edits own; author accepts a reply on their issue; organizers hide any.

Schema tables: `study_issues`, `replies` (both have `search_tsv` maintained by triggers — do NOT set it in PHP). Reference: `exams`, `exam_domains`, `resources`, `members`.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `issues-list` | `/issues/` | Browse/search issues |
| `issue-add`   | `/issues/form.php` | Post an issue |
| `issue-edit`  | `/issues/form.php?id={id}` | Edit own issue |
| `issue-view`  | `/issues/view.php?id={id}` | Read issue + replies, reply, accept |

## List (`issues-list`)
- Columns: Title (row link to view; status dot) · Exam · Domain · Replies (count) · Status (open/resolved badge; "Answered" if accepted_reply set) · Author · Age (`created_at` relative) · Actions (Edit if own)
- Filters: exam, domain (filtered), status (open/resolved), **unanswered** (reply_count=0). Full-text `q` box over issues: `search_tsv @@ plainto_tsquery('english', :q)`, rank with `ts_rank`. Sort: `recent`, `most_replies`, `relevance` (when q present). Page size 25.
- Visibility: not hidden OR author OR organizer.

## Detail (`issue-view`)
- Issue body (markdown → safe text render, no raw HTML). Exam/domain tags, status.
- Replies list (chronological): body, author, age, linked resource; the accepted reply is pinned/badged. Author of the issue sees an **Accept** button per reply (`reply_accept`); accepting clears any prior accepted reply and sets `status` cue "Answered".
- Reply form (`reply_create`): body ✔, optional resource select. Pattern D refresh of the replies region + reply count.
- Resolve toggle (`issue_resolve`) for the author. Organizer: Hide issue / Hide reply (confirm).

## Form (`issue-add`/edit)
- Fields: title ✔ · exam_id (select, optional) · domain_id (select, filtered) · body (textarea, markdown) ✔. Ids `issue-form-field-{name}`.

## Files
- `/var/www/html/issues/index.php` · `form.php` · `view.php` · `save.php` · `resolve.php` · `hide.php`
- `/var/www/html/issues/reply.php` · `accept.php` · `reply-hide.php`
- `/var/www/app/features/issues/queries.php`
- `/var/www/app/views/issues/page.php` · `partials/table.php` · `row.php` · `form.php` · `view.php` · `replies.php` · `reply-row.php`

## Query functions
- `find_issues(PDO, string $q='', ?int $examId=null, ?int $domainId=null, ?string $status=null, bool $unanswered=false, string $sort='recent', int $memberId=0, bool $isOrganizer=false, int $page=1): array` (reply_count; visibility; ts_rank when q)
- `find_issue(PDO, int $id, int $memberId, bool $isOrganizer): ?array`
- `insert_issue/update_issue/resolve_issue/hide_issue(...)`
- `find_replies(PDO, int $issueId, int $memberId, bool $isOrganizer): array`
- `insert_reply(PDO, int $issueId, int $authorId, string $body, ?int $resourceId): array`
- `accept_reply(PDO, int $issueId, int $replyId, int $issueAuthorId): array` (owner-checked)
- `hide_reply(PDO, int $id, int $byMemberId, ?string $reason, bool $hide): array`
- Search input is a value (parameterized into `plainto_tsquery`), never concatenated.

## Action manifest entries
Screens `issues-list/add/edit/view`. Actions `issue_create`, `issue_update`, `issue_resolve`, `reply_create`, `reply_accept`, `issue_hide` †, `reply_hide` † — registered.

## Activity events
`issue.create/update/resolve/reopen/hide` · `reply.create/accept/hide` · `screen.view`.

## Notifications (wire the reply/accept notifications now)
On `reply.create`, insert a `notifications` row (kind `issue_reply`) for the issue author (unless self-reply). On `reply.accept`, notify the reply author (kind `reply_accepted`). Email delivery is best-effort via `send_email` when MaluMail is configured; the in-app Notification row is always written. (This satisfies M8's "did anyone reply?".)

## Status vocabulary
Issue `status`: open→info, resolved→success. Hidden→secondary + "Hidden" badge.

## Out of scope
- Threaded/nested replies. Voting. Rich markdown/HTML. Email digest (slice 11).

## Open Questions
- (none)
