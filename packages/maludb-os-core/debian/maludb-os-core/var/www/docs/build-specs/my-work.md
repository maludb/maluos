# Build spec: My Work — "what is waiting on me?"

2026-09-20 · Module 14, the last of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Manifest: one screen, `my-work` at `/my-work`; **no actions** (read-only — nothing is added to the
manifest or the registry). Tool surface: `my_work` (`horizon_days?`, default 7; gate: all).

## One gatherer, in SQL — additive **db/118**
The screen (PHP) and the tool (Python, as `app_records_ro`) must never disagree, and a second
copy of fifteen queries in a second language would. So the gatherer is a function,
`app_my_work(p_horizon_days int, p_limit int)` — `SECURITY INVOKER`, reading **only `mcp_*`
views**, so every row it returns is one the caller could already open. Each section runs in its
own `BEGIN … EXCEPTION` block: a failing section raises a WARNING and is skipped; it cannot
break the page. A section the caller has no way into simply returns no rows. It returns
`(section, waiting, kind, id, title, detail, due_at, state, href, urgency, total)` — at most
`p_limit` rows per section, `total` being the section's full count.

`home_work()` (the dashboard's four short lists, with the columns its cards show) is left exactly
as it is — the dashboard does not change. My Work's PHP gatherer `my_work_sections()` lives
beside it in `app/features/home/work.php` and calls the function.

**Appointments today and tomorrow** are the one thing SQL cannot do — a series must be expanded
by the recurrence library in the series' timezone. Both sides reuse the Calendar's expansion:
PHP `find_schedule_window()`; Python `occurrences_in_window()` (lifted out of the `schedule`
tool so both use it). "Today" is the viewer's own day (their timezone).

## Sections (shown only when they have rows; "see all" goes to the owning module's list)
Waiting on me: approvals to decide · time to approve (weeks of other people's submitted time,
for a holder of the time module or an admin) · appointments I have not answered · my open
tickets (SLA state, breached first) · mail conversations assigned to me whose last word came
from outside · content awaiting my review · leave requests I may decide (people module + the
people rule, as the leave handlers ask) · form submissions on forms assigned to me, unprocessed
· my tasks due within the horizon or overdue (blocked ones flagged) · overdue invoices I own ·
my own rejected time, and past weeks I never submitted.
Coming up / waiting on others (shown, not counted in the header): today's and tomorrow's
appointments · my pending approval requests · purchase orders I own that are sent and not fully
received · signature requests I sent that are still out · my approved leave starting within the
horizon · for an agent: its active duties' next runs, and (tool only) its monthly budget.

Left out, and why: **content "sent back for changes"** — a change request returns the item to
`draft` and keeps its note in the activity trail, so a sent-back draft cannot be told from a
fresh one through the view (OPEN); **eval alerts** — they have no assignee; **reports** —
nothing there waits on a person.

## Rules
Insiders only (`require_insider()`); an External person is sent to `/portal` by the shell. No
bodies, no prompt text, no pay figures, no amounts except an invoice's balance (the owner's own
invoice) — titles, dates, states and links. An agent asks through the tool; the MCP boundary
decides whether it holds `my_work` (tool grants), as for every tool.
