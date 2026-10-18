# Build spec: study-log slice (Phase 3, slice 6)

Exemplar: **exam-catalog** for code structure/CSRF/logging, but this screen **diverges** from the CRUD list: it's a **quick-add row + recent sessions + weekly totals by domain**. Member-facing. §8.6: a member's study log is visible to **owner + organizers only** — every query is owner-scoped; organizers read via the Community-Health slice, not here.

Schema tables: `study_sessions`. Reference: `exams`, `exam_domains`, `exam_attempts`, `resources`.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `study-log` | `/study-log/` | Quick-add + recent list + weekly-by-domain totals |
| (edit)      | `/study-log/form.php?id={id}` | Edit one session (owner) |

## Screen layout (`study-log`)
- **Quick-add card at the top** (a plain form, not a modal): minutes ✔, exam (select), domain (select, filtered by exam), studied_on (date, default today), confidence (1–5 select), resource (optional), note. Submit `session_log` → prepend the new row to the recent list (Pattern D: fire `sessionsChanged`; the recent-list region and the totals region both listen and refresh).
- **This-month totals by domain** region: table/bars of `sum(minutes)` and `avg(confidence)` grouped by domain for the current member, current month. This answers M4/M10 at a glance. A month selector (`?month=YYYY-MM`) swaps `#study-log-totals`.
- **Recent sessions** region: list (date, exam, domain, minutes, confidence, note) with Edit/Delete per row (Pattern C for delete). Page size 25, paginated.

## Edit form (`/study-log/form.php?id=`)
- Same fields as quick-add, pre-filled; Save/Cancel in page header (like exemplar). Owner-scoped.

## Files
- `/var/www/html/study-log/index.php` · `save.php` · `form.php` · `delete.php` · `totals.php` (fragment endpoint, Pattern A)
- `/var/www/app/features/study_log/queries.php`
- `/var/www/app/views/study_log/page.php` · `partials/quick-add.php` · `list.php` · `row.php` · `form.php` · `totals.php`

## Query functions (owner-scoped)
- `find_sessions(PDO, int $memberId, int $page=1): array` (recent, joins exam/domain)
- `find_session(PDO, int $id, int $memberId): ?array`
- `insert_session(PDO, int $memberId, int $minutes, ?int $examId, ?int $domainId, ?int $resourceId, string $studiedOn, ?int $confidence, ?string $note): array`
- `update_session(PDO, int $id, int $memberId, …): array`
- `delete_session(PDO, int $id, int $memberId): bool`
- `totals_by_domain(PDO, int $memberId, string $month): array` (sum minutes, avg confidence, per domain, joined to exam_domains for names + weight)

## Action manifest entries
Screen `study-log`. Actions `session_log`, `session_update`, `session_delete` (confirm) — registered. Endpoints as in Files.

## Activity events
`session.log` · `session.update` · `session.delete` · `screen.view`.

## Status vocabulary
No status. Confidence renders as a 1–5 pill (1–2 danger, 3 warning, 4–5 success) — this mapping is display-only.

## Out of scope
- Cross-member visibility (organizers use Community Health). Charts beyond simple bars (no chart lib in the default bundle). Timers/stopwatch entry.

## Open Questions
- (none)
