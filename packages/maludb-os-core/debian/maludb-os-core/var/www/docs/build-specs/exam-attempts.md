# Build spec: exam-attempts + calendar slice (Phase 3, slice 2)

Exemplar to replicate: **exam-catalog** — reread its "Canonical patterns" section; all of it applies (HX-Target dual endpoint, write→refreshed-list-into-#page-content, `form.php`/`form.php?id=` URLs, escaping, CSRF, activity logging). This slice is **member-facing** (every member manages their own attempts), plus a **calendar** read screen.

Schema tables (never modify): `exam_attempts`. Reference only: `exams`, `exam_domains`, `community_settings` (retake policy), `members`.

Authorization: any logged-in member. A member may read/write **only their own** attempts — every query function that mutates takes `$memberId` and filters `WHERE member_id = :m`; controllers pass `current_member_id()`. Never trust an id from the request alone.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `attempts-list` | `/attempts/` | My exams (attempts) — list |
| `attempt-add`   | `/attempts/form.php` | Create-attempt form (empty) |
| `attempt-edit`  | `/attempts/form.php?id={id}` | Same form, pre-filled (owner only) |
| `calendar`      | `/calendar/` | Month grid of visible exams; **agenda list at ≤ md** |

(Canonical URLs `/attempts/new`, `/attempts/{id}/edit` apply once mod_rewrite is on.)

## List screen (`attempts-list`)
- Columns: Exam (`exams.code` — row link to edit, status dot by `status`) · Kind (`kind`) · Date (`exam_date` medium; append " (tentative)" if `date_is_tentative`; "—" if null) · Status (badge) · Countdown (`exam_date - today` days when future & scheduled) · Result (only your own: passed/not_passed/—) · Visibility (calendar_visible, result_shared icons) · Actions (Edit)
- Search matches: none (small per-member list) — instead a filter select by `status`. Sort allowlist: `exam_date`, `status`, `created_at` (default `exam_date` NULLS LAST). Page size 25.
- Row link target: `attempt-edit`.
- Empty state: "No exams yet. Add the one you're planning to take."

## Form (`attempt-add`/`attempt-edit`)
- Fields, in order:
  | Field | input | required | validation | id |
  |---|---|---|---|---|
  | exam_id | select (options: active exams, `code — name`) | ✔ | must be an active exam | `attempt-form-field-exam` |
  | kind | select (`exam`/`renewal`) | ✔ | enum | `attempt-form-field-kind` |
  | status | select (`considering`/`scheduled`/`taken`/`withdrawn`) | ✔ | enum; `passed`/`not_passed` are set via `attempt_record_result`, not here | `attempt-form-field-status` |
  | exam_date | date | required when status ∈ {scheduled,taken} | ≥ today for new scheduled | `attempt-form-field-date` |
  | start_time | time | — | — | `attempt-form-field-time` |
  | timezone | select (IANA list; default member's tz) | — | valid IANA | `attempt-form-field-tz` |
  | delivery | select (`online`/`test_center`/blank) | — | enum | `attempt-form-field-delivery` |
  | date_is_tentative | checkbox | — | bool | `attempt-form-field-tentative` |
  | calendar_visible | checkbox (default on) | — | bool | `attempt-form-field-calvis` |
- Selects are plain `<select class="form-control">` (no select2 needed). Enforce the `attempt_date_required` CHECK in PHP before insert (clearer error than a DB 23514).
- **Result + sharing are NOT on this form.** They're separate actions on the edit page header / list row: `attempt_record_result` (buttons "I passed" / "I didn't pass"), `attempt_share_result` (toggle), `attempt_start_renewal` (from a passed attempt). Recording a pass sets `certified_on = today`, `certified_until = today + exam.validity_months`.

## Calendar screen (`calendar`) — diverges from the CRUD exemplar
- **Server-rendered month grid**, no JS calendar library. `GET /calendar/?month=YYYY-MM`. Prev/next are `hx-get` links swapping `#calendar-region` (Pattern B, target via `HX-Target: calendar-region`), `hx-push-url="/calendar/?month=YYYY-MM"`.
- Each day cell lists that member's visible attempts for the month: exams where `member_id = me OR calendar_visible = true`, `exam_date` in range, status ∈ scheduled/taken/passed/not_passed. Show `exam.code` + owner display name; own attempts styled distinctly.
- **Mobile (≤ md): render an agenda list** (grouped by day) instead of the grid — same data, `.d-md-none` agenda / `.d-none.d-md-block` grid. No horizontal scroll.
- Filters: exam (select), and a layer note "Events appear here after slice 3." (Events are added to this same screen in slice 3.)
- Read-only screen — no writes; logs `screen.view` only.

## Files (as-built convention)
- `/var/www/html/attempts/index.php` · `form.php` · `save.php` · `status.php` · `result.php` · `share.php` · `visibility.php` · `renew.php` · `delete.php`
- `/var/www/html/calendar/index.php`  *(replaces the Phase-2 stub)*
- `/var/www/app/features/attempts/queries.php`
- `/var/www/app/views/attempts/page.php` · `partials/table.php` · `row.php` · `form.php`
- `/var/www/app/views/calendar/page.php` · `partials/grid.php` · `agenda.php`

## Query functions (PDO first; owner-scoped)
- `find_attempts(PDO, int $memberId, string $statusFilter='', string $sort='exam_date', int $page=1): array` (joins exam code/name)
- `find_attempt(PDO, int $id, int $memberId): ?array` (owner-scoped; null if not theirs)
- `insert_attempt(PDO, int $memberId, int $examId, string $kind, string $status, ?string $date, ?string $time, ?string $tz, ?string $delivery, bool $tentative, bool $calVisible): array`
- `update_attempt(PDO, int $id, int $memberId, …same fields): array`
- `set_attempt_status(PDO, int $id, int $memberId, string $status): array`
- `record_attempt_result(PDO, int $id, int $memberId, string $result, int $validityMonths): array` (sets certified_on/until on pass)
- `set_attempt_share(PDO, int $id, int $memberId, bool $shared): array`
- `set_attempt_calendar_visible(PDO, int $id, int $memberId, bool $visible): array`
- `start_renewal(PDO, int $memberId, int $fromAttemptId): array` (new attempt kind=renewal, considering)
- `delete_attempt(PDO, int $id, int $memberId): bool`
- `find_calendar_exams(PDO, int $memberId, string $monthStart, string $monthEnd): array` (visible attempts in range: `member_id=:m OR calendar_visible`)
- `active_exams_options(PDO): array`

## Action manifest entries
Screens `attempts-list`, `attempt-add`, `attempt-edit`, `calendar` (already registered). Actions (already in manifest): `attempt_create`, `attempt_reschedule`, `attempt_set_status`, `attempt_record_result`, `attempt_share_result`, `attempt_set_calendar_visibility`, `attempt_start_renewal`, `attempt_delete`. Endpoints as in Files. `attempt_reschedule` = `save.php` on an existing id changing the date (log `attempt.reschedule`, capture before/after date).

## Activity events
`attempt.create` · `attempt.reschedule` (before/after exam_date) · `attempt.status_change` · `attempt.record_result` · `attempt.share_result` · `attempt.hide_from_calendar` (visibility toggle) · `attempt.delete` · `screen.view` (attempts-list, calendar, attempt-add/edit).

## Status vocabulary
`considering`→secondary · `scheduled`→info · `taken`→warning · `passed`→success · `not_passed`→danger · `withdrawn`→dark.

## Out of scope
- Community events on the calendar (slice 3 adds them to `calendar/`).
- Study buddies list (a Members-screen/AMA concern, not here).
- Editing another member's attempt (never).
- iCal feed (slice 11).

## Open Questions
- (none)
