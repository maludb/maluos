# Build spec: Time — "where did the hours go?"

2026-09-19 · Module 2 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/036 + db/054 (`time_entries`, `time_timers`, `mcp_time_entries`, `mcp_time_timers`),
plus the additive **db/106** below. Manifest "Time": 5 screens, 8 actions. Tools: `time_summary`,
`missing_timesheets`.

## Rules
- **The week starts Monday** (default recorded in the decisions file). A timesheet is one
  member's entries with `entry_date` in `[monday, monday + 7)`.
- **Status walk:** `draft` → (`timesheet_submit`, the member) → `submitted` → (`timesheet_approve`,
  mod:time) → `approved`, or (`timesheet_reject` with a reason) → `rejected` → edit → submit again.
  Approving **locks** the entries (`locked_at`); an invoiced entry (`invoice_line_id`) is locked
  too. `time_update` and `time_delete` refuse a locked entry. A submitted entry can still be
  edited by its owner — that returns it to `draft` (the approver must not approve what changed
  under them).
- **Own, or administered.** Everyone logs and edits their OWN time (manifest: "all (own)").
  Approving and rejecting need `mod:time` AND the member must be one the caller may see through
  `mcp_time_entries` (a dept-admin decides their departments' timesheets, not the company's).
  Nobody approves their own timesheet unless they are the super-admin.
- **The rate is snapshotted when time is logged** (owner's decision 9): the project's
  `hourly_rate` and currency → else `business_settings.default_hourly_rate` in the base
  currency → else `hourly_rate` stays NULL: billable, **no amount**. An entry with no rate shows
  "no rate" on the timesheet and on Unbilled work, and `invoice_add_unbilled` must skip it — it
  is never invoiced at zero. Changing a project's rate later does not reprice logged time.
  `mcp_time_entries` masks `hourly_rate` from anyone who may not administer the member; the
  presenter passes on what the view returns and nothing else.
- **One running timer per member** (`time_timers.member_id` is unique). Stopping writes an entry
  of `ceil(elapsed minutes)`, at least 1, dated today in the member's timezone, then deletes the
  timer.
- `minutes` is the truth; a form may send `hours` (decimal) instead, which is ×60 and rounded.

## db/106 (additive)
- `time_entries.rejection_reason text` — the manifest's `timesheet_reject` has a required reason
  and the table had nowhere to keep it; cleared when the entry is resubmitted. Appended to
  `mcp_time_entries`.
- `business_settings.default_hourly_rate numeric(12,2) CHECK (>= 0)`, NULL by default; appended to
  `mcp_business_settings`; editable on Settings → Business (super, as that screen already is).

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `timesheet` | `/time?week=&member=` | `html/time/index.php` — the week's entries by day, totals (all / billable), the running timer, the week's status, Submit; `member` only for someone who may see that member's time |
| `time-entry-add` / `-edit` | `/time/new?project=&task=&minutes=&date=`, `/time/{id}/edit` | `html/time/form.php` |
| `time-approvals` | `/time/approvals?week=&department=` | `html/time/approvals.php` — submitted weeks per member, mod:time |
| `time-report` | `/time/report?period=&group_by=` | `html/time/report.php` — hours, billable hours, utilization, grouped by project / customer / member / day |

## Actions (handlers in `html/time/`)
`time_log` + `time_update` → `save.php` (`time_entry.create` / `.update`); `time_delete` →
`delete.php`; `timer_start` → `timer-start.php` (`time_timer.start`); `timer_stop` →
`timer-stop.php` (`time_timer.stop` + `time_entry.create`); `timesheet_submit` → `submit.php`
(`time_entry.submit`); `timesheet_approve` → `approve.php`; `timesheet_reject` → `reject.php`.
Links on an entry (project, task, customer, ticket, appointment, campaign) are accepted only if
the caller can see the record; the department is taken from the project, else the member's
primary department.

## Knock-on edits to built code
- `html/settings/business/` + its React form: the default hourly rate field.
- `app/features/sales/reports.php` `unbilled_work()` is already written for this module; the
  Unbilled screen gains the "no rate" flag and `invoice_add_unbilled` skips unpriced hours.
- The project page's budget card reads hours logged (it was waiting on this module).
