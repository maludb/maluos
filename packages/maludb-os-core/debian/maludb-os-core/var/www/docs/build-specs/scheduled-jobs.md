# Build spec: scheduled jobs + calendar feed slice (Phase 3, slice 11)

Exemplar: none (no screens). CLI cron scripts + one public feed endpoint. Reuses `send_email` (MaluMail) and `log_activity` with `source='cron'`. All scripts are `PHP_SAPI==='cli'` guarded and idempotent (never double-send: mark a notification row before/at send and skip if one already exists for that (member, kind, entity, period)).

Schema tables: `notifications`, `calendar_feed_tokens`, `mcp_access_tokens` (read), plus reads across `exam_attempts`, `community_events`, `event_rsvps`, `invitations`, `members`.

## Cron scripts (`/var/www/bin/cron/`)
Each: bootstrap (CLI), connect as app_rw with a system context (set `app.member_id`=NULL, `app.role`='organizer' is wrong for a job — instead the app tier is trusted; run queries directly, they're not RLS-restricted for app_rw). Log a `cron.run` activity row with counts.

| Script | Cadence | What it does |
|---|---|---|
| `exam_reminders.php` | daily | For attempts with `status='scheduled'` and `exam_date = today+7` (and `= today+1`): insert a `notifications` row (kind `exam_reminder`) for the owner if `notify_exam` and not already sent for that attempt+window; email best-effort. |
| `event_reminders.php` | hourly | For `scheduled` events starting in ~24h: notify each `going`/`maybe` RSVP (kind `event_reminder`) once. |
| `cert_expiry_reminders.php` | daily | For passed attempts with `certified_until` in {30,14,7} days out: notify owner (kind `cert_expiring`) once per threshold if `notify_exam`. |
| `invite_expiry.php` | daily | Mark nothing destructive; optionally notify organizers of invitations expiring in ≤ 2 days (or just log). Expired invites are already filtered by `expires_at` at read time. |
| `notification_email_flush.php` | every 5 min (optional) | Send any `notifications` rows with `email_sent_at IS NULL` whose member opted in; set `email_sent_at`; respect MaluMail 429 backoff. (If each job emails inline, this is a safety net only.) |

Idempotency rule (all reminder jobs): before sending, `INSERT ... ON CONFLICT DO NOTHING` a notification uniquely keyed by (member_id, kind, entity_type, entity_id, and a period tag in `title`), or check-then-insert in a transaction. Never send if a matching row exists.

## Calendar feed (public iCal) — `/var/www/html/feed/calendar.php`
- `GET /feed/calendar.php?token={raw}` — look up `calendar_feed_tokens` by `hash('sha256',$raw)`, not revoked. 404/403 generically on miss. Sets `app.member_id` to the token's member so RLS-equivalent visibility applies; emit `text/calendar` (`.ics`) with VEVENTs for that member's visible exams (own + calendar_visible) and scheduled community events. Update `last_fetched_at`; log `calendar_feed.fetch` (source `cron`/`web`).
- No session; the token IS the auth. Read-only.

## Token management (moves to Settings, Phase 4)
The **UI** for creating/revoking `mcp_access_tokens` and `calendar_feed_tokens` ships with the Settings screen (Phase 4). This slice provides the **feed-serving endpoint** and the cron jobs; it may include CLI helpers `bin/mint_calendar_feed.php` / `bin/mint_mcp_token.php` for testing before the UI exists.

## Files
- `/var/www/bin/cron/exam_reminders.php` · `event_reminders.php` · `cert_expiry_reminders.php` · `invite_expiry.php` · `notification_email_flush.php`
- `/var/www/html/feed/calendar.php`
- `/var/www/app/features/notifications/queries.php` (insert/find/mark helpers, dedupe)
- `/var/www/app/features/feed/ical.php` (builds the VCALENDAR text)
- (deploy) a `docs/deploy/crontab.example` listing the schedules.

## Query functions
- `notify_once(PDO, int $memberId, string $kind, ?string $entityType, ?int $entityId, string $title, ?string $body): ?int` (dedup insert; returns id or null if already existed)
- `due_exam_reminders(PDO, int $daysOut): array`, `due_event_reminders(PDO): array`, `due_cert_reminders(PDO, int[] $daysOut): array`
- `unsent_notifications(PDO, int $limit): array`, `mark_notification_emailed(PDO, int $id): void`
- `feed_member_by_token(PDO, string $rawToken): ?array`, `feed_events_for(PDO, int $memberId): array`

## Action manifest entries
No screens/actions (cron + public feed). The feed URL is surfaced in Settings (Phase 4). Activity events: `notification.sent`, `calendar_feed.fetch`, `cron.run` (per job, with counts).

## Activity events
`notification.sent` (per email) · `calendar_feed.fetch` · `cron.run` (source `cron`, after JSON with counts).

## Out of scope
- Real-time push. SMS. Per-member custom reminder timing (fixed windows in v1). The token-management UI (Phase 4 Settings).

## Open Questions
- (none)
