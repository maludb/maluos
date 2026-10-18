# Build spec: organizer community health slice (Phase 3, slice 10)

Exemplar: **exam-catalog** for code structure. **Organizer-only, read-only** dashboards. No new tables — reads aggregates across the schema. Every controller calls `require_organizer()`.

Schema tables (read): `members`, `exam_attempts`, `study_plans`, `study_sessions`, `study_issues`, `replies`, `community_events`, `event_rsvps`, `resource_endorsements`, `invitations`, `activity_log` (for the activity trend).

## Screen (`org-health`, `/organizer/health/`) — replaces the Phase-2 stub
A single page of panels (cards), each a canonical table or a small stat block. Sub-regions refresh independently (Pattern A fragment endpoints) so a heavy panel doesn't block the page.
- **At-risk members** (O2): scheduled attempt with no plan, or no study logged in `community_settings.at_risk_no_study_days`. Columns: member, exam, days-to-exam, reason. Fragment `/organizer/health/at-risk.php`.
- **Pass rate per exam** (O4): from **shared results only**, anonymous counts (passed/taken, %). Fragment `.../pass-rate.php`.
- **Expiring certifications** (O9): passes expiring in ≤ 60 days. Columns: member, exam, expires, days-left. `.../expiring.php`.
- **Unanswered issues** (O5): open issues with zero replies, oldest first, link to issue-view. `.../unanswered.php`.
- **Activity trend** (O12): week-over-week active members / actions from `activity_log`. Simple table of the last 8 weeks (no chart lib). `.../trend.php`.
- **Pending invitations** teaser (O8): count + link to the Invitations screen.

## Files
- `/var/www/html/organizer/health/index.php` (composes panels; full page + `#page-content` partial)
- `/var/www/html/organizer/health/at-risk.php` · `pass-rate.php` · `expiring.php` · `unanswered.php` · `trend.php` (fragment endpoints, Pattern A)
- `/var/www/app/features/health/queries.php`
- `/var/www/app/views/health/page.php` · `partials/at-risk.php` · `pass-rate.php` · `expiring.php` · `unanswered.php` · `trend.php`

## Query functions (organizer scope; read-only)
- `at_risk_members(PDO): array` (mirrors the `mcp_at_risk_members` view logic)
- `pass_rate(PDO): array` (shared-only, per exam)
- `expiring_certifications(PDO, int $withinDays=60): array`
- `unanswered_issues(PDO, int $page=1): array`
- `activity_trend(PDO, int $weeks=8): array` (distinct actors + action counts per week from `activity_log`)
- `pending_invitation_count(PDO): int`
These parallel the organizer-only MCP tools; keep the SQL logic consistent with the `mcp_*` views so the screen and the AMA agree.

## Action manifest entries
Screen `org-health` (registered). No write actions. Fragment endpoints are GET-only.

## Activity events
`screen.view` (org-health). Reads only; no mutations to log beyond the view.

## Status vocabulary
At-risk → danger/warning by severity (no plan = danger, stale study = warning). Pass-rate cells neutral. Expiring ≤ 30 days → danger, ≤ 60 → warning.

## Out of scope
- Any member-identifying view of **unshared** results (only anonymous aggregate counts, per §3.2). Drill-down into private study logs beyond the at-risk signal. CSV export. Charts (no chart lib in default bundle; tables only).

## Open Questions
- (none)
