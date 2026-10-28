# Build spec: Calendar — "what is happening this week, and who is booked?"

2026-09-19 · Module 4 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/033 (`appointment_types`, `bookable_resources`, `appointments`,
`appointment_assignees`, `appointment_resources`, `availability_blocks`) + additive **db/107**.
Manifest "Scheduling": 8 screens, 15 actions. Tools: `schedule`, `find_free_time`,
`schedule_conflicts`, `job_counts`. **Installed:** `rlanvin/php-rrule` (composer).

The URL is `/schedule/` (nav and manifest); the application row said `/calendar/` — the row is
corrected by db/107's companion update in this slice. Internal-only: no external calendar sync
(the schema has no columns for one); people subscribe from their own calendar to the iCal feed.

## Recurrence (owner's decision 11: full RRULE with exceptions)
- A **series** is one `appointments` row with `recurrence_rule` (RFC 5545 RRULE, no `DTSTART` —
  the row's `starts_at` in the row's `timezone` is the start). Its length is
  `ends_at − starts_at`. Expansion is done by `rlanvin/php-rrule` **in the series' timezone**, so
  a 09:00 weekly meeting stays at 09:00 across a daylight-saving change.
- An **exception** is a child row: `recurrence_parent_id` = the series,
  `recurrence_original_start` (db/107) = the occurrence it replaces. Moved or edited "this
  occurrence only" = a child with its own times and fields; cancelled "this occurrence only" = a
  child with `status = 'cancelled'`. A child is never itself recurring.
- An occurrence is addressed as `<series id>@<original start, UTC, YYYYMMDDTHHMMSSZ>`. The
  screens link to `/schedule/{id}?occurrence=…`; actions take `occurrence` beside `appointment`.
  "This occurrence only" materialises the child on first write; "the whole series" edits the
  parent. Ending a series = `UNTIL` on the rule. A rule is accepted only if php-rrule parses it
  and it is bounded or yields ≤ 730 occurrences in a 2-year horizon per window read.
- Windows read for a screen are capped at 62 days; at most 500 occurrences per series per read.

## Rules
- Visibility is `mcp_appointments`': an insider sees an appointment they are assigned to, or that
  `app_can_see('scheduling', owner, department, …)` admits them to. Writing needs `mod:scheduling`
  except `appointment_respond` and `appointment_complete` (an assignee's own) and a person's own
  availability blocks.
- **Conflicts warn, they do not block** (a double-booking is sometimes deliberate): saving,
  rescheduling, assigning or booking a resource reports `conflicts` — other non-cancelled
  appointments the same person or resource is on in that time, and `unavailable` blocks — in the
  action's answer and on the appointment page.
- Times arrive as local wall time (`2026-10-01T09:00`) in the caller's timezone unless they carry
  an offset; `duration_minutes` or `ends_at`; stored as timestamptz, with `timezone` kept.
- `appointment_cancel` takes a reason and notifies nobody outside (appointment notifications to
  customers are not in the manifest — recorded OPEN). `appointment_delete` is admin-only and
  refused for an invoiced appointment.
- **Availability:** `working_hours` and `unavailable` blocks for a person (default self) or a
  resource, one-off or recurring. `find_free_time` = people (optionally of one department) with
  no busy block and no `unavailable` block across a slot of the asked duration inside their
  working hours, if they have any defined.

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `schedule` | `/schedule?view=day|week|month&date=&member=&resource=&type=` | `html/schedule/index.php` — occurrences in the window, expanded |
| `appointment-add` / `-edit` | `/schedule/new?title=&starts_at=&type=&organization=&member=`, `/schedule/{id}/edit?occurrence=` | `…/form.php` |
| `appointment-view` | `/schedule/{id}?occurrence=` | `…/view.php` — crew with responses, resources, customer, conflicts, the series' rule in words |
| `availability` | `/schedule/availability?member=&resource=` | `…/availability.php` |
| `free-time` | `/schedule/free?duration=&from=&to=&department=` | `…/free.php` |
| `appointment-types-settings`, `resources-settings` | `/settings/appointment-types`, `/settings/resources` | `html/settings/{appointment-types,resources}/index.php` |

## Actions
As the manifest lists them, handlers in `html/schedule/` (and the two settings folders); events
as named there. `appointment_update` is a partial update (registered in `app/partial_update.php`).

## iCal feed
`html/feed/calendar.php` (public by token, on the Apache allow-list) served cert-study exams and
events, which are retired. It now serves the member's appointments: one `VEVENT` per
non-recurring appointment, and per series a `VEVENT` with `RRULE` plus `EXDATE` for cancelled
occurrences and a `RECURRENCE-ID` `VEVENT` for each moved one, with `TZID`-free UTC times for
single events and the series' timezone for recurring ones.
