# Build spec: community-events + RSVPs slice (Phase 3, slice 3)

Exemplar: **exam-catalog** (all canonical patterns apply). Member-facing. §8.1: **any member may create** an event; organizers may edit/cancel **any** event; a host may edit/cancel **their own**. §8.3: no recurrence — a **duplicate** action copies to a new date.

Schema tables: `community_events`, `event_rsvps`. Reference: `exams`, `exam_domains`, `members`.

Authorization helper (add to queries or a small guard): `can_manage_event($event, $memberId, $isOrganizer)` = `event.host_id === memberId || $isOrganizer`. Use in `form.php`, `save.php`, `cancel.php`, `duplicate.php`.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `events-list` | `/events/` | Upcoming events list |
| `event-add`   | `/events/form.php` | Create form |
| `event-edit`  | `/events/form.php?id={id}` | Edit (host/organizer only) |
| `event-view`  | `/events/view.php?id={id}` | Detail + RSVP + attendee list |

## List (`events-list`)
- Columns: Title (row link to view; kind dot) · Kind (badge) · When (`starts_at` in viewer tz — medium date + time) · Exam (`exams.code` or —) · Going (count) · Host · Actions (RSVP quick buttons + Edit if manageable)
- Filters: time (`upcoming`/`past`, default upcoming), exam, kind. Sort: `starts_at` (default asc for upcoming). Page size 25.
- Times render in the **viewer's timezone** (events are `timestamptz`); format server-side using the member's tz.

## Detail (`event-view`)
- Header: title, kind badge, cancelled banner if `status='cancelled'` (+ reason). When/where (meeting_url link if online, else location). Host. Exam/domain tags. Capacity + going count.
- RSVP control: three buttons (going/maybe/not_going) → `rsvp_set`; current response highlighted; updates in place (Pattern C/D refresh the RSVP region + counts).
- Attendee list: members who RSVP'd going/maybe (names via `event_rsvps` join `members`).
- Manage buttons (host/organizer): Edit, Duplicate, Cancel (hx-confirm).

## Form (`event-add`/`event-edit`)
- Fields: kind (select) ✔ · title ✔ · description (textarea) · starts_at (datetime-local) ✔ · ends_at (datetime-local, ≥ starts_at) · is_online (checkbox, default on) · meeting_url (url; required when online) · location (text; required when in person) · exam_id (select, optional) · domain_id (select, optional, filtered by exam) · capacity (number, optional). Ids `event-form-field-{name}`.
- Store `starts_at`/`ends_at` as `timestamptz`: interpret the datetime-local input in the member's tz, convert to UTC for storage.

## Files — AS BUILT
- `/var/www/html/events/index.php` · `form.php` · `view.php` · `save.php` · `rsvp.php` · `cancel.php` · `duplicate.php` · **`domains.php`** (fragment: exam→domain options)
- `/var/www/app/features/events/queries.php`
- `/var/www/app/views/events/page.php` · `partials/table.php` · `row.php` · `form.php` · `view.php` · `rsvp.php` · **`domain-options.php`**

**Deviations (canonical for later slices):**
- **Timezone helpers** added to `app/http.php`: `format_ts($utc,$tz,$fmt)` renders a timestamptz in the viewer's tz; `local_to_utc($localInput,$tz)` converts a datetime-local input to UTC for storage. `db.php` now runs `SET TIME ZONE 'UTC'` per connection so timestamptz always returns UTC. **Any slice with timestamptz uses these.**
- **RSVP lives on the detail page**, not the list row (list row shows going-count + View/Edit) — keeps the row simple and the RSVP region self-refreshing (`#event-rsvp-region`).
- **Duplicate** is an inline datetime + button on the detail (host/organizer only), posting `starts_at` (local) → `duplicate.php` → lands on the new event's edit form.
- **Cancel** uses `hx-confirm` (no reason prompt in v1); notifies going/maybe attendees with an in-app `event_cancelled` notification (email flush is slice 11).
- **Exam→domain** dependent select uses a Pattern-A fragment endpoint (`domains.php` → `domain-options.php`). Slices 4/5/7 with the same exam→domain dependency replicate this.

## Query functions
- `find_events(PDO, string $when='upcoming', ?int $examId=null, ?string $kind=null, int $page=1): array` (with going_count)
- `find_event(PDO, int $id): ?array` (with host name, exam code, counts)
- `insert_event(PDO, int $hostId, …fields): array`
- `update_event(PDO, int $id, …fields): array`
- `cancel_event(PDO, int $id, ?string $reason): array`
- `duplicate_event(PDO, int $id, int $hostId, string $newStartsAt): array` (copies fields, sets `duplicated_from_event_id`)
- `delete_event(PDO, int $id): bool` (optional; cancel is preferred)
- `set_rsvp(PDO, int $eventId, int $memberId, string $response): array` (upsert on unique (event_id,member_id))
- `find_rsvps(PDO, int $eventId): array` (names + responses)
- `event_exam_options(PDO)`, `event_domain_options(PDO, int $examId)`

## Action manifest entries
Screens `events-list/add/edit/view`. Actions `event_create`, `event_update`, `event_duplicate`, `event_cancel` (confirm), `rsvp_set` — all registered. Endpoints as in Files.

## Activity events
`event.create` · `event.update` · `event.cancel` · `rsvp.set` (before/after response) · `screen.view`.

## Status / kind vocabulary
Event `status`: `scheduled`→success, `cancelled`→secondary. Kind is descriptive (badge, neutral `bg-soft-info`).

## Calendar integration (this slice)
Extend `calendar/` (built in slice 2) to also render **scheduled events** in the month grid/agenda (a second layer with a toggle: exams / events). Add `find_calendar_events(PDO, monthStart, monthEnd)` to the events queries and compose both layers in `calendar/index.php`. Times in viewer tz.

## Out of scope
- Real recurrence (duplicate only). Email reminders (slice 11). Waitlists when over capacity (capacity is advisory in v1).

## Open Questions
- (none)
