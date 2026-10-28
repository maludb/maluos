# Build spec: People — "who works here, what do we pay them, and who is off?"

2026-09-19 · Module 9 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/058 (`employment_profiles`, `compensation_changes`, `pay_runs`, `pay_run_items`,
`pay_run_lines`, `leave_types`, `leave_balances`, `leave_requests` and their `mcp_*` views) +
additive **db/113**. Manifest "People & payroll": 11 screens, 14 actions. Tools: `find_people`,
`employment_profile`, `payroll_summary`, `pay_runs`, `leave`.

## Who sees what — pay is the tightest data in the system
`app_can_see_person()` (db/058) is the rule and is not widened: a person's own record; their
reports' (the `manager_member_id` on the employment record); a holder of the `people` grant for
the people they administer (`app_can_admin_member()`); the super-admin. **Agents see none of it**
(`app_member_kind() = 'human'`) and are never employees — db/113 adds a trigger that refuses an
employment record for an agent. `mcp_leave_requests` alone is wider: an admin sees who in their
departments is off (the dates and type — never pay).
- Screens open to any insider and show what the views show: for most people, themselves.
- **HR writes** (employment, compensation, balances, leave types, pay-run drafting) need the
  super-admin, or the `people` GRANT (`has_module_grant()` — not `has_module()`, which admits
  every dept-admin to a module's screens) **and** `app_can_admin_member()` of that person.
- Approving, paying and voiding a pay run: super-admin only (manifest).
- **Activity rows never carry an amount**: a compensation change logs that it changed, its
  effective date and type; a pay run logs its number, period and head-count. The figures live
  in the tables, behind the views.
- Home contact details (`personal_email`, `address`, `emergency_contact`) are in no view; only
  the edit form, after the HR gate, reads them. `birth_date` and `national_id_last4` have no
  screen yet (OPEN). Bank details (`payment secret`) are a write-only tenant secret.

## Compensation
`compensation_changes` is the history; the employment record carries the rate in force.
`compensation_change_save` writes the change and, when its date has arrived, the record; a
future-dated change is applied by the pay run that covers it (`compensation_as_of()` reads the
newest change on or before the period's end) and by the yearly job. Changing `pay_rate` on the
employment form records a change effective today, so the history has no gaps.

## Leave (owner's decision 12: granted upfront each year)
- A leave type with `accrual_days_per_year` gets a balance row per person per year: the full
  allowance, or **pro-rated from the start date** for someone who starts during the year
  (allowance × days left in the year ÷ days in the year, **rounded DOWN to the half day**).
  Granted when an employment record becomes active, and by `bin/grant_annual_leave.php` on
  1 January (idempotent: `ON CONFLICT DO NOTHING` per person, type and year). Types with no
  allowance (unpaid leave, public holiday) have no balance and are not limited.
- Carry-over is a manual HR adjustment (`leave_balance_adjust`); nothing carries by itself.
- `days` defaults to the business's open weekdays (Helpdesk's `business_hours`) between the two
  dates; `half_day` is 0.5 on one date. A request may not span two calendar years.
- A request beyond the balance, or overlapping another, is **accepted and flagged**; approving
  beyond the balance is **refused** unless HR passes `override` (added to the manifest).
  A type that needs no approval (sick leave) is approved as it is made.
- Approval draws the balance down and puts an `unavailable` block on the person's calendar
  (so `find_free_time` is honest); cancelling an approved request gives both back.
- Deciding: the person's manager, HR for the people they administer, the super-admin — never
  the person themself (the super-admin excepted, who has nobody above them).

## Pay runs (statutory payroll is OUT of scope — no tax is calculated, nothing is filed)
- A draft run takes everyone active the caller may manage (or `members`), in the run's
  currency. Each person's **base earning**: salary = annual `pay_rate` ÷ periods of their
  `pay_schedule` (52 / 26 / 24 / 12); hourly = their APPROVED time entries in the period not
  already on another live run × `pay_rate`, traced in `time_entry_ids`. `daily`, `per_invoice`,
  a missing schedule or rate, or another currency → the person is on the run with **no base
  line and a note saying why** — never paid a guess.
- HR adds lines per person (`earning`, `deduction`, `employer_cost`, `reimbursement`) — this is
  where an accountant's tax figures are keyed in. gross = earnings + reimbursements;
  net = gross − deductions; totals are recomputed on every change.
- draft → approved (super; un-approved by voiding) → paid (super; records when — **no money
  moves, no bank file**) ; void = unpaid only.
- **Posting (owner's decision 16):** the posting run gains `unposted_pay_runs()` beside
  `unposted_stock_movements()`: a PAID run with no journal entry posts on its `pay_date` —
  Dr 6000 Salaries and wages (or a line's own account) for earnings, employer costs and
  reimbursements, Cr 2200 Payroll liabilities for the same total — by the seeded `payroll`
  rule. `post_to_books` on `pay_run_mark_paid` runs that posting at once for the one run.
  Clearing the liability when the bank pays is a bank-side entry, not posted here (OPEN).

## Screens
`/people` · `/people/{id}?tab=employment|pay|leave` · `/people/{id}/edit` ·
`/people/{id}/compensation/new` · `/people/payruns` (+ `/new`, `/{id}`) · `/people/leave`
(+ `/new`, `/calendar`) · `/settings/leave`.

## Actions
As the manifest lists them; handlers in `html/people/`, `html/people/payruns/`,
`html/people/leave/`, `html/settings/leave/`. `lines[]` reaches the agents' door as flat text:
`kind:code:amount[:description]`, comma-separated.
