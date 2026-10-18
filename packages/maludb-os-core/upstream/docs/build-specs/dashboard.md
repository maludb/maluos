# Build spec: dashboard slice (Phase 3, slice 9)

Exemplar: **exam-catalog** for code structure. **Composition slice** — no new tables; it fills the Phase-2 dashboard tiles + tables with real data from slices 2–8. Member-facing; organizers see the same plus a small health teaser linking to Community Health.

Schema tables (read): `exam_attempts`, `study_plans`, `plan_items`, `study_sessions`, `notifications`, `replies`, `plan_comments`, `community_events`, `exams`.

## Screen (`dashboard`, `/`)
Replace the Phase-2 placeholder stats in `app/views/dashboard/page.php` with live values; keep the exact tile ids (`dashboard-tile-exam`, `-plan`, `-minutes`, `-replies`).
- **Tiles:**
  - Days to my next exam (`min(exam_date) - today` over my scheduled attempts; "—" if none) → tile-exam.
  - This week's plan items (count of my active-plan items due within the current week) → tile-plan.
  - Study minutes this month (sum my `study_sessions.minutes` this month) → tile-minutes.
  - Replies waiting (my unread `notifications` of kind `issue_reply`/`plan_comment`/`reply_accepted`) → tile-replies.
- **Cert-expiry banner**: if I have a passed cert expiring within `validity`/60 days, show a warning banner with a link to My Exams (renewal).
- **This week's plan items** list (canonical table pattern): my due-soon items with a complete checkbox (reuses `plan_item_complete`, Pattern D refresh).
- **Upcoming on the calendar** table (replace the empty state): my next visible exams + events (union, next 30 days), link to `/calendar/`.
- **Waiting for me** list: recent unread notifications with links to the target record; mark-read action.

## Files
- (edit) `/var/www/html/index.php` — fetch the composed data, pass to the view.
- (edit) `/var/www/app/views/dashboard/page.php` — real tiles + tables (keep ids).
- `/var/www/app/features/dashboard/queries.php`
- `/var/www/app/views/dashboard/partials/week-items.php` · `upcoming.php` · `notifications.php`
- `/var/www/html/notifications/read.php` (mark one / all notifications read; returns the region)
- `/var/www/html/dashboard/complete-item.php` (AS-BUILT deviation): toggles a plan item's
  completion from the week panel and re-renders `#dashboard-week-items`. Reuses the plans
  slice's owner-checked `complete_plan_item`/`find_own_plan`; a dedicated endpoint keeps the
  plans endpoints from having to know the dashboard's markup.

## Query functions
- `dashboard_stats(PDO, int $memberId): array` (the four tile values in one struct)
- `next_exam(PDO, int $memberId): ?array`
- `week_plan_items(PDO, int $memberId): array`
- `upcoming_calendar(PDO, int $memberId, int $days=30): array` (reuse attempts + events calendar queries)
- `unread_notifications(PDO, int $memberId, int $limit=10): array`
- `expiring_certs_for(PDO, int $memberId): array`
- `mark_notification_read(PDO, int $id, int $memberId): bool`

## Action manifest entries
Screen `dashboard` (already registered). Action `notification_mark_read` (already registered) → `/notifications/read.php`. `plan_item_complete` reused from the plans slice.

## Activity events
`screen.view` (dashboard). `notification.read` (optional). Plan-item completion logs via the plans slice's handler.

## Status vocabulary
Reuse each entity's mapping. The cert-expiry banner uses `warning`.

## Out of scope
- Charts/analytics (Community Health owns aggregates; no chart lib in the default bundle). Configurable widgets. Cross-member data (organizer aggregates live in Community Health).

## Open Questions
- (none)
