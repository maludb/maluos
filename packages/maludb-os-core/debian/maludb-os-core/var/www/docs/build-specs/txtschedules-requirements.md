# txtSchedules — requirements (a restaurant staff scheduling application for the Business OS)

*2026-09-28. The owner's decisions are taken (§9); nothing is built. **txtSchedules** — catalog key `txtschedules`
(kernel keys are lowercase), `txtschedules.<domain>`. Sources: the owner's brief ("a staff scheduling system with
a focus on restaurants where the staff can use a mobile web app to see their shifts and post offers of shift changes
and trade shifts"); the market's three leaders, read 2026-09-28 —
[7shifts](https://www.7shifts.com/restaurant-employee-scheduling-software),
[HotSchedules (Fourth)](https://lp.fourth.com/hotschedules),
[Deputy for QSR](https://www.deputy.com/industry/qsr); and the Business OS contract, the `maludb-os-integration`
plugin 0.4.2 (`os-integration`: memory, MCP, sign-on, agents, roles and rights, scopes, registration).*

**In one sentence:** managers at each restaurant build and publish a week's schedule from their staff's
availability and the restaurant's rules; staff see their shifts on their phones and give away, pick up and trade
shifts among themselves, within rules the manager sets; everyone is signed in by the OS, and the OS's agents can
answer "who is on Friday night?" and draft next week's schedule for a manager to publish.

## 1. What the market does, and what version 1 takes

| Capability | 7shifts | HotSchedules | Deputy | Version 1 |
|---|---|---|---|---|
| Schedule builder, drag and drop, availability shown while building | yes | yes | yes | **Yes** (§3.3) |
| Templates from a published week; copy last week; auto-fill from past schedules | yes | — | — | **Yes** (§3.3) |
| Availability and time-off requests from the phone, approved by a manager; PTO and sick balances | yes | — | yes | **Yes — and it replaces HR's leave for its staff** (§3.2, D5) |
| Staff offer, drop, pick up, swap shifts ("Shift Pool") with the manager in control | yes | yes | yes | **Yes — the heart of the brief** (§3.5) |
| Last-minute coverage: who is free for a sick, late or no-show shift | yes | — | yes | **Yes** (§3.5, FR-S9) |
| Compliance alerts while scheduling: breaks, overtime, rest between shifts, minors, fair workweek, certifications | yes | yes | yes | **Yes, as warnings a manager overrides with a reason** (§3.6) — fair workweek deferred (D8) |
| Digital sign-off for a missed break or a shift change | — | — | yes | **Later, with fair workweek** (FR-C6, D8) |
| Labor budget and cost while scheduling (wage × hours) | yes | yes | yes | **Yes** (§3.7), pay visible to managers only |
| Forecast staffing from sales / traffic (POS, "7+ years of sales", holidays, events) | yes | yes (AI) | yes (AI) | **A simple manual forecast in v1** (§3.7a); Reservations' covers next (D9) |
| Announcements and team messaging | yes | yes | yes | **Announcements yes; chat no** (§3.8) |
| Notifications to phones | yes | yes | yes | **Email in v1; SMS through the kernel's SMS service (D6); push later** (§3.9) |
| Multi-location view | yes | yes | yes | **Yes** — each restaurant a kernel site (§4.2) |
| Time clock, timesheets, payroll export | yes (7punches) | yes | yes | **No** (§8) |
| POS integrations (Toast, Square, …), tip pooling, surveys | yes | surveys | — | **No** (§8) |

The three agree on the core, and the owner's brief sits on it: **the schedule on the phone, and staff trading
shifts themselves with the manager in control.** Forecasting, the time clock and POS are what each sells on top;
they are left for later so version 1 is small, complete and good on a phone.

## 2. Who uses it — the application's roles

Published to the kernel through `app_roles` (§4.4); granted by the super-admin **per restaurant**; a person may hold
different roles at different restaurants.

| Role | Capability | Who | Rights (the application's words) |
|---|---|---|---|
| `staff` "Staff" | write | Everyone who works shifts | `schedule.view_own` see their own shifts and the published team schedule · `availability.edit` their own availability and time-off requests · `market.trade` offer, drop, pick up and swap their shifts |
| `shift_lead` "Shift lead" | write | Supervisors on the floor | staff's rights + `coverage.fill` fill a gap in the current day from the available list · `market.approve_day` approve trades for today and tomorrow |
| `manager` "Manager" | write | Restaurant and kitchen managers | shift lead's rights + `schedule.build` build, edit and publish schedules · `requests.approve` approve availability, time off and trades · `labor.view` see wages and labor cost · `announce.post` post announcements |
| `admin` "txtSchedules admin" (is_admin) | admin | The owner, the GM | manager's rights + `settings.manage` positions, rules, budgets, templates · `pay.edit` wage rates |

A super-admin holds `admin` at every restaurant (the kernel's rule). **Nobody holds anything by default** — the
kernel grants it (§4.3).

## 3. Functional requirements

### 3.1 People, positions, skills
- **FR-P1** Staff are the kernel's members, mirrored (§4.3); txtSchedules never creates a person and never changes the
  directory. A member appears at a restaurant when the kernel grants them a role there.
- **FR-P0** Each staff member has one **main restaurant** (set by a manager or admin; the first restaurant granted by
  default). Managers may schedule them anywhere they are granted; **they pick up shifts only at their main restaurant**
  (D4).
- **FR-P2** Positions per restaurant (Server, Host, Bartender, Line cook, Dishwasher, …), each with a colour; a staff
  member has one or more positions at each restaurant, one primary.
- **FR-P3** Per staff member: wage rate per position (`pay.edit` to change, `labor.view` to see), maximum hours per
  week, date of birth only as "is a minor" plus the minor's rules (§3.6), and certifications with an expiry date
  (food handler, alcohol service).
- **FR-P4** A staff member sees only their own profile; a manager sees the profiles at the restaurants they manage.

### 3.2 Availability and time off
- **FR-A1** Staff set recurring weekly availability (available / unavailable / preferred, by time range per
  weekday), from the phone; a change takes effect from a date and, when the restaurant requires it, waits for a
  manager's approval.
- **FR-A2** Staff request time off (a date range, whole days or hours, a reason category); a manager approves or
  declines with a note; the request and its answer notify the staff member.
- **FR-A3** Approved time off and unavailability are shown while building and block auto-fill; scheduling over them
  is a warning a manager overrides with a reason (§3.6).
- **FR-A5** **txtSchedules is the time-off system where it is used (D5):** time-off types per restaurant (vacation / PTO,
  sick, unpaid, other), optional balances per person per type set and adjusted by an admin (with the reason logged),
  a request drawing the balance down on approval and restoring it on cancellation; staff see their balances on the
  phone. A business using txtSchedules does its staff's time off here instead of in HR's leave desk; how HR is told
  (for pay and records) is a later kernel crossing (§7).
- **FR-A4** Blackout dates per restaurant (no time off on Valentine's Day, Mother's Day, New Year's Eve) —
  requests for them are refused with the reason.

### 3.3 Building and publishing the schedule (managers)
- **FR-B1** A week view per restaurant: rows by staff or by position, days across, shifts as blocks; drag to move,
  stretch to lengthen, click to edit; the same actions as buttons on a phone. A day view by hour for the floor.
- **FR-B2** A shift: restaurant, position, date, start, end, planned unpaid break, assignee or **open** (unassigned,
  to be picked up), note. Overnight shifts allowed (end after midnight in the restaurant's time zone).
- **FR-B3** Templates: save a week as a template; start a week from a template or from last week; auto-fill a week's
  open shifts from availability, position, past pattern and hours balance — **a draft the manager reviews**.
- **FR-B4** Drafts are invisible to staff. **Publish** makes a week (or a date range) visible and notifies each
  affected staff member of their shifts; later edits to a published shift notify the people it affects and are
  recorded as changes (§3.6).
- **FR-B5** While building, the manager sees each person's hours for the week, the week's labor hours and cost against
  the budget (§3.7), and every rule warning (§3.6).
- **FR-B6** Copy, delete and bulk-edit shifts; undo the last change.

### 3.4 Staff on their phones (the mobile web app)
- **FR-M1** Home: my next shift (when, where, position, who else is on), my week, open requests, announcements.
- **FR-M2** My schedule by week and as a list; the published team schedule for my restaurant, by day, with positions.
- **FR-M3** Add my shifts to my phone's calendar: a private, revocable iCalendar feed URL per person (read-only,
  token in the URL, no names of others).
- **FR-M4** Everything a staff member does is on the phone: availability, time off, offer, drop, pick up, swap,
  accept, read announcements. Nothing requires a desktop.
- **FR-M5** Works at 375 px, loads fast on a phone connection, and can be installed to the home screen (a web app
  manifest); push notifications are later (D6).

### 3.5 The shift marketplace — offers, pickups and trades (the brief)
- **FR-S1** **Offer (drop)**: a staff member puts one of their published shifts up for grabs, with an optional note; it
  stays theirs until someone takes it and — when required — a manager approves.
- **FR-S2** **Pick up**: staff eligible for the shift (§FR-S5) see offered and open shifts at their **main restaurant** and
  claim one; the first eligible claim wins, or the manager chooses among claimants (a restaurant setting).
- **FR-S3** **Swap (trade)**: a staff member proposes their shift for a specific colleague's shift; the colleague
  accepts or declines; then the manager approves when required.
- **FR-S4** **Direct give**: offer a shift to one named colleague, who accepts or declines.
- **FR-S5** **Eligibility**, checked for every claim and swap, with the reason shown when refused: holds the position,
  the shift is at their main restaurant (FR-P0), is available and not on time off, no overlap, and no hard rule broken (§3.6); soft
  rules (overtime, rest) are warnings passed to the approver.
- **FR-S6** **Trades are settings in txtSchedules (D2)**, per restaurant, by the restaurant's admin: which exchanges are
  allowed at all (offer, pick up, swap, give — each on or off), which need a manager (always / only when a warning
  fires / never, per kind), how late before the shift an exchange may happen (e.g. not within 2 hours), whether shift
  leads approve same-day ones, first-claim-wins or manager-chooses, and how long an offer stays open. A new
  restaurant starts with all four allowed, a manager approving only when a warning fires.
- **FR-S7** Every step notifies the people concerned (offered, claimed, accepted, approved, declined, expired); an
  offer nobody takes expires at the shift's start and the shift stays with its owner.
- **FR-S8** The history of every exchange is kept (who offered, who took, who approved, when) and shown on the shift.
- **FR-S9** **Coverage**: for a gap (sick, no-show, new open shift), the manager or shift lead sees who is eligible and
  free, sorted by hours this week, and offers the shift to one or several at once; the first to accept gets it.

### 3.6 Rules and warnings (compliance as help, not enforcement)
- **FR-C1** Per restaurant (and per jurisdiction preset), rules the builder and the marketplace check: minimum rest
  between shifts ("clopening"), maximum hours per day and week and overtime thresholds, planned meal/rest breaks by
  shift length, minors' hours and times (school days, latest end), expired or missing certification for the
  position. **Fair workweek (advance notice, predictability pay) is deferred (D8).**
- **FR-C2** A rule is **hard** (refused — e.g. a minor after the legal hour) or **soft** (a warning); the restaurant
  admin sets which.
- **FR-C3** Warnings appear on the shift as it is built or traded; publishing with warnings asks the manager to
  confirm, with a reason recorded.
- **FR-C4** Presets are starting points the business adjusts; **txtSchedules does not claim legal compliance** — the
  screen says so.
- **FR-C5** A compliance report per week: every override and every change to a published shift.
- **FR-C6** *(Deferred with fair workweek, D8:)* a change to a published shift inside a notice window asking the
  affected staff member's digital sign-off.

### 3.7 Labor budget and cost
- **FR-L1** A weekly labor budget per restaurant (hours and/or currency), optionally per position group
  (front / kitchen).
- **FR-L2** Scheduled cost = hours × the staff member's wage for that position; shown to `labor.view` only; overtime
  cost counted at the restaurant's multiplier.
- **FR-L3** Budget vs scheduled, by day and week, while building (FR-B5) and in a report.

### 3.7a Forecast (D9 — the owner left the source to judgement)
- **FR-F1** Version 1: a manager enters, per restaurant, day and day-part (lunch, dinner), the expected covers — or
  copies last week's — and sets staffing ratios per position (e.g. one server per 25 covers, a host per 60). The
  builder then shows, per day-part, the positions' **recommended headcount beside the scheduled one**. No POS, no AI.
- **FR-F2** Next: the expected covers filled from Reservations' booked covers for the same restaurant and service,
  when the kernel carries an application-to-application read (§7). Reservations is the first source because it is
  ours, on the same sites, and its covers are the demand a restaurant already knows; POS sales come after it.

### 3.8 Announcements
- **FR-N1** Managers post announcements to a restaurant, a position, or named people, optionally pinned until a date;
  staff see them on their home screen; read receipts for the poster.
- **FR-N2** No chat between staff (D7).

### 3.9 Notifications
- **FR-O1** Each person chooses their channels (email, SMS) and what they are told about (published schedule, changes,
  exchanges, approvals, announcements, reminders before a shift).
- **FR-O2** Email through MaluMail with the application's own sender. **SMS through a new kernel SMS service (D6)**:
  txtSchedules asks the kernel to send a text to a member; the kernel sends it on the tenant's number and ledgers it —
  no application holds a Twilio key. Until that service exists, email only. A notification carries no more than
  the shift's facts and a link — never another person's pay or contact details.
- **FR-O3** A reminder before each shift (a setting: e.g. 2 hours).

### 3.10 Reports
- **FR-R1** Hours by person, position and restaurant for a period; scheduled vs budget; open shifts not filled;
  exchanges (count, time to approve, who picks up most); overtime; compliance (FR-C5). Each as a screen and a CSV.

## 4. The Business OS contract, applied (non-negotiable)

### 4.1 Its own application, its own everything
- **OS-1** Own repository at `/srv/apps/txtschedules`, own PostgreSQL 17 database (`<tenant>_txtschedules`) with the three
  roles (read-write, records read-only, activity read-only), own Apache vhost `txtschedules.<domain>` plus a loopback port,
  own MCP servers — installed by the kernel's `bin/app_install.php` from `maludb-os.json`, `db/`, `deploy/` templates.
  **Never** a table shared with the kernel or another application.
- **OS-2** Apache/PHP/HTMX on the `htmx-php-builder` patterns and the nxl design system, 375 px first (§3.4).

### 4.2 Split by restaurant
- **OS-3** `scopes.kind = location`: each restaurant is a kernel **site**, the same sites Reservations uses — a
  restaurant added once serves both. Every scheduled row carries its scope; every query, `mcp_*` view and MCP tool
  filters by the scopes the caller holds. A removed site closes its restaurant here and keeps its history.
- **OS-4** A person granted at two restaurants sees both schedules and switches between them; they pick up shifts
  only at their main restaurant (FR-P0).

### 4.3 People come from the kernel
- **OS-5** No password, no login form, no account of its own: the kernel's hand-off (`/sso`, `/sso/logout`), the
  directory mirror with the kernel's ids, refreshed every minute from the change feed; a deactivated or revoked person
  is shut out on their next request. `directory.writes = false`.
- **OS-6** Staff use it on the web and as a mobile web app (installable to the home screen) — the same application,
  no native app (D3). They reach it by **the kernel's grant to everyone residing at a site** — hiring someone into a restaurant
  in the kernel (HR, through the directory API) gives them Staff there with no per-person step (D3).
- **OS-7** Typing `txtschedules.<domain>` on a phone with no session goes to `app.<domain>` to sign in and straight back
  (`?app=txtschedules`, kernel commit bc23820).

### 4.4 Roles and rights
- **OS-8** Publishes §2 through `app_roles` (`os.app-roles/1`) on its records MCP, admitting the kernel's 60-second
  token to that tool alone; enforces rights from its own catalogue (`schedule_has_right(right, scope)`), per scope.

### 4.5 Memory
- **OS-9** Every change through one `log_activity()` as `entity.verb` (`shift.publish`, `shift.offer`,
  `exchange.approve`, `timeoff.request`, `rule.override`, …) carrying the scope and what the questions need (before
  and after, the warning overridden and why); shipped to the tenant's one MaluDB as `activity` episodes tagged
  `txtschedules`. Pay values are never in an episode — only that a rate changed.

### 4.6 Agents
- **OS-10** A records MCP server with one tool per recurring question — who is on (a restaurant, a date, a
  position), my shifts, open and offered shifts, coverage candidates for a shift, hours this week, labor vs budget,
  pending requests, compliance warnings — plus one guarded search; an activity MCP server over the trail. Wages
  answer only for a caller holding `labor.view`.
- **OS-11** An action manifest for every button, and the kernel's action registry from it; the run token honoured
  everywhere, grants failing closed, scopes enforced for agents as for people.
- **OS-12** Approval categories: an agent's **publish** (it notifies staff: `external_send`), **changing a published
  shift**, **approving an exchange** and **changing pay** pause for a person in the kernel's approvals.
- **OS-13** Shipped agents: the **expert** (answers questions, the command bar through the kernel's chat endpoint) and
  a **scheduling assistant** that drafts a week (FR-B3) and proposes coverage (FR-S9) — drafts only, a manager
  publishes. **No model key and no model call in the application.**
- **OS-14** Skills shipped in `skills/`: the scheduling rules explained, the marketplace rules, and runbooks for the
  common manager tasks.

### 4.7 Declares itself
- **OS-15** `maludb-os.json` (catalog key, `business_area` Operations, scopes, sso, directory, assistant, agents,
  approvals, endpoints, env, services), `/api/v1/health`, `db/`, `deploy/` templates, writable `storage/`; the kernel
  installer's `plan` run at the end of every phase, not only at the end (lesson of 2026-09-28).

## 5. Non-functional
- **NF-1** Phone first: every staff screen designed at 375 px before desktop; the builder usable on a tablet.
- **NF-2** Times are always the restaurant's time zone (the site's), shown with it when a person works at two.
- **NF-3** Privacy: a staff member sees names, positions and shift times of their team — never pay, date of birth,
  phone or email of others; the iCal feed carries only their own shifts.
- **NF-4** Every exchange and change is auditable (FR-S8, OS-9); nothing is deleted that was ever published — a
  cancelled shift stays as cancelled.
- **NF-5** Concurrency: two staff claiming the same shift — exactly one wins, the other told why.
- **NF-6** Performance: a phone's home screen answers in under 1 s; the week builder for 60 staff under 2 s.

## 6. Screens (first list)
Staff (phone): Home · My schedule · Team schedule · Shift (with offer / swap / give) · Marketplace (offered and
open shifts I can take) · My requests · Availability · Time off · Announcements · Notification settings.
Managers: Week builder · Day view · Templates · Approvals inbox (time off, availability, exchanges) · Coverage ·
Staff and positions · Rules · Budget · Announcements · Reports. Admin: Settings per restaurant.

## 7. Integration with other applications (through the kernel only)
- **HR** owns employment. **Time off moves to txtSchedules for the staff it schedules (D5)**: HR's leave desk is not
  used for them. Telling HR what was taken (for pay and records) needs a kernel crossing between two applications —
  owed to the kernel, after version 1.
- **Reservations** holds covers per restaurant per service — the natural first forecast (§8). Same: an
  application-to-application read through the kernel is owed (FR-F2).

## 8. Not in version 1
Time clock and timesheets; payroll export; POS integrations and sales-based forecasting; AI demand forecasting;
tip pooling; staff chat; surveys; push notifications (the web app is installable; push later); **fair workweek
(advance notice, predictability pay, digital sign-off — D8)**. Statutory payroll and
legal compliance guarantees stay out (the kernel's standing decision).

## 9. The owner's decisions (2026-09-28)
| # | Decision |
|---|---|
| D1 | **Name: txtSchedules** — catalog key `txtschedules`, `txtschedules.subello.com` (the proxy entry named the same). |
| D2 | **Trades are settings in the application**, per restaurant (FR-S6). |
| D3 | **Staff use it on the web or as a mobile web app** — one application, installable to the phone's home screen; access by the kernel's grant to everyone residing at a site (OS-6). |
| D4 | **Staff pick up shifts only at their main restaurant** (FR-P0, FR-S2). |
| D5 | **Time off lives in txtSchedules and replaces HR's leave** for the staff it schedules (FR-A5, §7). |
| D6 | **SMS through a new kernel service** — no application holds a Twilio key; email until it exists (FR-O2). **Kernel work.** |
| D7 | **No staff chat**; announcements only. |
| D8 | **Fair workweek deferred** (FR-C1, FR-C6). |
| D9 | **Forecast (the owner's "use your judgement")**: a manual covers forecast with staffing ratios in version 1; Reservations' booked covers next, through a kernel crossing (§3.7a). |

Owed to the kernel by these decisions: an **SMS service** for applications (D6), and an **application-to-application
read** (D5 telling HR what time off was taken; D9 Reservations' covers). Neither blocks version 1.

## 10. How it is built (the new-application process)
Phase 0 design and schema (from this document and the decisions in §9) → Phase 1 the checkpoint: the MCP tool surface,
the action manifest and one spec per slice, **approved by the owner before any feature code** → Phase 2 sign-on, the
mirror and the shell, installed beside the kernel → Phase 3 vertical slices (the first — the shift and the
marketplace — is the exemplar), each proven live at 375 and 1280 px → Phase 4 the MCP servers, the registry, the
agents and skills → the installer's `apply` and the end-to-end proof.
