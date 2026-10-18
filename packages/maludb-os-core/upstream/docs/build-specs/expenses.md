# Build spec: Expenses slice

2026-09-18 · build plan phase 2, slice 2 · planning-class spec for a worker build

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`; code under
`html/contacts/`, `app/features/contacts/`, `app/views/contacts/`), with the money conventions
the **Sales & invoicing** slice already set (`docs/build-specs/sales-invoicing.md`; code under
`app/features/sales/`). Everything those specs fix — the gate, view-reads, the endpoint
sequence, the render helpers, the shared components, the money rules — applies here unchanged.
This document names only the substitutions.

Module grant: `expenses` · Manifest section: **Expenses**
Schema tables (never modify): `expense_categories`, `recurring_expenses`, `expenses`,
`accountant_exports` (`db/039_expenses.sql`).
Read views: `mcp_expenses`, `mcp_expense_categories`, `mcp_recurring_expenses`,
`mcp_accountant_exports`, plus `mcp_organizations` for the vendor and customer pickers.
Questions this slice must answer: **E1–E13** (E14, E15 belong to AI ops — see Out of scope).

> **Receipts are deferred to the Documents slice (phase 4).** Decided 2026-09-18: there is no
> file storage on this server — no storage root, no upload helper, and `documents` /
> `document_versions` have no writer yet. Building one here would make this slice the owner of
> the platform's file storage, which is the Documents slice's job. So: build
> `expense_attach_receipt` as an endpoint that answers
> `"receipts arrive with the Documents module in phase 4"` through `emit_action_status(false, …)`
> and writes nothing — exactly as the sales slice left `invoice_add_unbilled` — and build the
> `missing_receipt` filter and the `has_receipt` column for real, reading `mcp_expenses`. Today
> every expense is missing its receipt and the filter says so honestly; when Documents lands,
> the filter starts narrowing without a line of this slice changing. Do **not** add an upload,
> a storage path, or a `documents` insert.

## Gate and visibility

The expenses module has a deliberate departure from "`require_module()` in every endpoint", and
it is the most important thing in this spec to get right.

**Every member may record and see their own expenses. Seeing anyone else's needs the grant.**
That is what `mcp_expenses` already enforces in SQL:

```sql
WHERE e.submitted_by = app_current_member_id()
   OR app_can_see('expenses', NULL, e.department_id, 'expense', e.id, NULL)
```

and it is what question **E10** ("What did I submit, and what's its status?", audience `U`) and
the manifest's `expense_create` gate (`all (own), mod:expenses`) both require. A plain user with
no expenses grant must be able to reach `/expenses/`, submit a lunch for reimbursement, and
watch its status — and must see nothing else.

So, endpoint by endpoint:

| Endpoints | Gate |
| --- | --- |
| `index.php`, `form.php`, `view.php`, `save.php`, `submit.php`, `receipt.php`, `delete.php` | `require_login()` only. The view is the visibility rule; a member who names an id they cannot see gets the exemplar's 404, never a 403. |
| `bills.php`, `report.php`, `recurring/*`, `exports/*` | `require_module('expenses')` — these are the *business's* money, not the member's own. |
| `approve.php`, `reject.php` | `require_business_admin()` **and** `require_admin_for_department($pdo, $expense['department_id'])`. A dept-admin approves inside the departments they administer and nowhere else. |
| `paid.php` | `require_module('expenses')`. Marking a bill paid is treasury, not submission. |
| `/settings/expense-categories/*` | `require_business_admin()`. |

- **Reads through `mcp_*` views only.** A list or detail screen that SELECTs `expenses`
  directly is wrong even when the rows come out right.
- **Writes to base tables**, after the gate **and** a re-read of the target row through
  `mcp_expenses` (RLS is permissive for `app_rw`; the app is the gate). The re-read is how an
  ordinary user is stopped from updating an expense that is not theirs.
- **Department stamping:** `expenses.department_id` and `recurring_expenses.department_id` are
  chosen from the member's departments (super-admin: any) using the shared
  `app/views/shared/department-select.php`, defaulting to the member's first department, NULL
  when they have none. A NULL-department expense is visible to its submitter and to grant
  holders, and to no dept-admin by virtue of their admin flag — that is the intended rule from
  `CLAUDE.md`, not an oversight.
- `submitted_by` is always the acting member at creation and is never editable.

## The two lifecycles (read this before writing the form)

`expenses` carries **two independent status columns**, and conflating them is the defect this
slice is most likely to ship.

| Column | Question it answers | Values |
| --- | --- | --- |
| `status` | *Has this expense been accepted by the business?* The submission/reimbursement lifecycle. | `draft` → `submitted` → `approved` \| `rejected` → `reimbursed` |
| `payment_status` | *Has the money left?* The treasury lifecycle. | `unpaid` → `scheduled` → `paid` |

They move on different actions and neither implies the other. Two shapes cover almost everything:

- **A spend that already happened** ("I paid for lunch"): `status='submitted'`,
  `payment_status='paid'`, `paid_on` set, no `due_date`. These are the schema defaults, so the
  common case is one form submit with nothing extra ticked.
- **A bill** ("the hosting invoice is due on the 30th"): `due_date` set,
  `payment_status='unpaid'`. `expense_mark_paid` is what settles it. This is what `bills-due`
  lists — `payment_status <> 'paid' AND due_date IS NOT NULL` — and there is no separate bills
  table: **a bill is an expense with a due date and unpaid money** (`db/039` header says so).

Neither of these is the **agent approval** machinery. `check_approval()` and
`approval_requests` pause an *agent* before it acts; `expense_submit`/`approve`/`reject` are a
*human* workflow over the `status` column. An endpoint can do both: an agent creating a 400 USD
expense is paused by `check_approval()` and writes nothing, while a person creating the same
expense writes a row with `status='submitted'` that a dept-admin then approves. Keep them apart
in the code and in the wording on screen.

## Money rules (inherited from Sales & invoicing — restated because they bind here)

1. **One currency per expense, never converted.** `currency` comes from the vendor
   organization's `currency` when it has one, else `base_currency($pdo)`. Fixed at creation.
2. **`tax_amount` is part of `amount`, not added to it.** The schema says
   `CHECK (tax_amount <= amount)`: `amount` is the gross, tax-inclusive figure, and
   `tax_amount` is how much of it was tax. The form must label this plainly ("Amount
   (including tax)" / "of which tax"), because every accounting habit pulls the other way.
   Net is `amount - tax_amount` and is derived on screen, never stored.
3. **Numbers come from the sequence, at creation:** `next_document_number('expense')` →
   `EXP-00001`, called once inside the insert's transaction. A deleted draft burns a number.
   Unlike invoices this raises no legal question — an expense number is an internal reference —
   so it needs no escalation and should not be re-raised.
4. **Money actions log their amount.** Every `log_activity()` in this slice puts `amount` and
   `currency` in `after`. The approval thresholds and the audit views read them, and E12
   ("what money-out actions did agents take or request?") is answered from exactly that.
5. **Totals are summed in SQL, over the view, per currency.** No screen totals a column in PHP,
   and no report ever adds two currencies together.

## Status vocabulary (locked)

- `status`: `draft` secondary · `submitted` info · `approved` success · `rejected` danger ·
  `reimbursed` dark.
- `payment_status`: `unpaid` warning · `scheduled` info · `paid` success.
- **Overdue is not a status** — it is `payment_status <> 'paid' AND due_date < current_date`,
  rendered as a `danger` badge beside the payment status, exactly as the invoice list does it.
- A missing receipt renders as a `warning` badge reading "no receipt" — the same badge the
  `missing_receipt` filter selects on.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `expenses-list` | `/expenses/` | browse expenses | `period`, `category`, `vendor`, `status`, `missing_receipt`, `mine` |
| `expense-add` | `/expenses/new` | record an expense or bill | `amount`, `vendor`, `category`, `project` |
| `expense-view` | `/expenses/{id}` | one expense with its receipt | — |
| `expense-edit` | `/expenses/{id}/edit` | edit an expense | — |
| `bills-due` | `/expenses/bills` | bills due soon | `within_days` |
| `recurring-expenses` | `/expenses/recurring` | recurring costs | — |
| `recurring-expense-add` | `/expenses/recurring/new` | add a recurring cost | — |
| `recurring-expense-edit` | `/expenses/recurring/{id}/edit` | edit a recurring cost | — |
| `spend-report` | `/expenses/report` | spend by category, vendor or month | `period`, `group_by` |
| `accountant-exports` | `/expenses/exports` | create or download an accountant export | — |
| `expense-categories-settings` | `/settings/expense-categories` | manage expense categories | — |

The installed rewrite rules (`docs/deploy/apache-canonical-urls.conf`) serve all of these
generically: the `{id}` rules match `[0-9]+` only, so `/expenses/bills`, `/expenses/report`,
`/expenses/recurring` and `/expenses/exports` fall through to their own files, and
`/expenses/recurring/new` and `/expenses/recurring/{id}/edit` reach
`html/expenses/recurring/form.php`. No new Apache configuration.

## List screens

**`expenses-list`** — columns in order: Number (link to `expense-view`) · Date (`expense_date`)
· Description · Vendor (`vendor_name`, masked to "—" when null) · Category (`category_name`) ·
Amount (`money()`, right-aligned) · Status badge · Payment badge (+ overdue, + "no receipt") ·
Submitted by (`submitted_by_name`, with the agent glyph when `submitted_by_kind = 'agent'`) ·
Actions (Edit while `draft`/`submitted` and the member may, otherwise View).

- Search matches `number`, `description` (via `search_tsv`) and `vendor_name`.
- Filters: `period` (over `expense_date`, via `expense_period_bounds()`), `category`, `vendor`,
  `status`, `missing_receipt=1` (`has_receipt = false`), `mine=1` (`submitted_by` = caller).
- Sort allowlist: `expense_date`, `amount`, `number`, `vendor_name` — default
  `expense_date DESC`. Page size 25.
- **Footer row: totals per currency for the current filter** — total, of which tax, and unpaid.
- Empty state: "No expenses match this filter." For a member with no expenses grant and no
  submissions of their own: "You haven't recorded any expenses yet." — never a bare zero.
- A member without the `expenses` grant gets the `mine` filter applied and locked, and the
  filter bar hides `vendor`, `category` and `status` controls they cannot use across the
  business. They see their own rows because the view gives them, not because PHP filtered.

**`bills-due`** — the unpaid side, sorted by `due_date ASC`: Due (with an overdue badge) ·
Number · Vendor · Description · Amount · Payment badge · Actions (Mark paid). `within_days`
defaults to 14, offered as 7 / 14 / 30 / 90 / all. Grouped by currency with a per-currency
total. Empty state: "Nothing due in the next {n} days."

**`recurring-expenses`** — Description · Vendor · Category · Amount · Frequency · Next due ·
Ends · Active toggle · Actions (Edit, Delete). **A monthly-equivalent column** answers E6
directly: weekly × 52/12, monthly × 1, quarterly ÷ 3, yearly ÷ 12, rounded to 2dp, totalled per
currency in the footer as "≈ {total}/month". State the arithmetic in a footnote on the screen.

## Detail screen

**`expense-view`** — header facts: number, description, `money(amount, currency)`, status badge,
payment badge (+ overdue), vendor, category, expense date, due date, submitted by and when,
approved by and when. Then panels in order:

1. **Details** — net / tax / gross breakdown, payment method, `paid_on`, billable flag, customer
   (`organization_id`) when set, and the recurring parent when `recurring_expense_id` is set
   (linking to `recurring-expense-edit`).
2. **Receipt** — the deferred state: "No receipt. Receipts arrive with the Documents module in
   phase 4." with the Attach receipt button present and answering that same message.
3. **Activity** — this record's history, `/activity?entity_type=expense&entity_id={id}` (E11).
4. **Notes** — the shared `record_comments` component (`app/views/shared/comments.php`),
   `entity_type = 'expense'`.
5. **Tags** — the shared `taggings` component (`app/views/shared/tags.php`),
   `entity_type = 'expense'`.

`data-screen="expense-view"`, `data-entity="expense"`, `data-record-id="{id}"` on the page root,
so the command bar resolves "add a note here" against this record exactly as it does on a deal.

Header actions by state: `draft` → Submit, Edit, Delete · `submitted` → Approve, Reject, Edit
(own), Delete (own) · `approved` → Mark paid (when unpaid), Mark reimbursed · `rejected` →
Edit and resubmit · any unpaid with a due date → Mark paid.

## Forms

**Expense form** (`expense-add`, `expense-edit`), field ids `expense-form-field-{name}`:

| Field | Input | Required | Validation |
| --- | --- | --- | --- |
| `description` | text | ✔ | 1–500 chars |
| `amount` | number, step 0.01 | ✔ | > 0, ≤ 99999999999.99 |
| `tax_amount` | number, step 0.01 | | ≥ 0 and ≤ `amount` — the error names the rule: "Tax is part of the amount, so it cannot exceed it." |
| `currency` | select | ✔ | 3 letters; defaults from the vendor organization, else `base_currency()`; read-only on edit |
| `expense_date` | date | ✔ | not more than 1 day in the future |
| `category_id` | select | | from `mcp_expense_categories` where not archived; picking one that is `is_billable_default` ticks `billable` (Pattern A fragment, like the catalog-item select on an invoice line) |
| `vendor_organization_id` | searchable select | | `mcp_organizations`, not archived, organizations carrying `'vendor'` in `relationship_types` listed first, then the rest. **Never writes to `organizations`** — E3 groups by `vendor_organization_id`, not by the tag. |
| `vendor_contact_id` | select | | options limited to that organization — the deal form's contact-select fragment, reused |
| `due_date` | date | | ≥ `expense_date`. Setting it sets `payment_status` to `unpaid` unless the member chose otherwise |
| `payment_status` | select | ✔ | unpaid / scheduled / paid — default `paid` |
| `paid_on` | date | | required when `payment_status = 'paid'`; defaults to `expense_date` |
| `payment_method` | select | | cash / check / bank_transfer / card / online / reimbursement / other |
| `billable` | checkbox | | |
| `organization_id` | searchable select | | the customer to rebill; shown only when `billable` is ticked |
| `department_id` | select | | shared department-select |
| `status` | — | | not on the form. `draft` when Save draft is used, `submitted` when Save is used. |

`project_id`, `task_id` and `campaign_id` are **hidden and unwritten** in this slice — Projects
and Content & social are phase 3, and a select over an empty table is a dead control. The
manifest lists `project` and `campaign` as `expense_create` params; leave them accepted and
ignored by the endpoint, and note it in the registry description, exactly as the sales slice
left `online_payment_enabled`.

**Recurring expense form** (`recurring-expense-add|edit`), ids `recurring-form-field-{name}`:
`description` (✔), `amount` (✔ > 0), `currency` (✔), `frequency` (✔ weekly/monthly/quarterly/
yearly), `next_due_on` (✔, date), `ends_on` (≥ `next_due_on`), `vendor_organization_id`,
`category_id`, `department_id`, `active` (checkbox, default on).

**Category form** — inline rows on `expense-categories-settings`, the exemplar's inline
child-row pattern (`hx-include="closest tr"`, region re-render, never a `<form>` in a `<tr>`):
`name` (✔, unique — `citext UNIQUE`, so a duplicate must be caught and reported as a field
error, not a 500), `accounting_code`, `is_billable_default` (checkbox), Archive toggle. An
archived category keeps its expenses and disappears from the pickers.

## Reports

**`spend-report`** (E1, E2, E3, E9) — `group_by` ∈ `category` | `vendor` | `month`, `period`
over `expense_date`, plus a free-text `q` matching description and vendor (E2). A table per
currency: the group, the total, the tax, the count, and the share of the period. When
`group_by = category`, a second column **"vs 3-month average"** shows this period's total
against the mean of the three preceding periods of the same length, as a signed percentage with
a `danger`/`success` tint — that is E9, and it is the only reason the comparison exists. No
chart in this slice.

**`accountant-exports`** (E13) — the list of past export runs (period, format, includes, row
counts, generated by/at, last downloaded) and a Create form: `period_start`, `period_end`,
`format` (**csv only in this slice** — `xlsx` needs a writer library and is not worth one here;
the schema's constraint allows it for later), `includes` (checkboxes over `invoices`,
`payments`, `expenses`; `fees`, `refunds`, `credit_notes` and `payouts` stay unticked and
disabled with the note "arrives with online payments").

Creating an export **counts the rows and stores `row_counts`**; it does not write a file.
`document_id` stays NULL until the Documents slice exists. The CSV is streamed on demand from
`exports/download.php?export={id}`, regenerated from the stored period and `includes`, and the
download stamps `last_downloaded_at`. This is what makes E13 — "what's in the export for a
period, and when was it last pulled?" — answerable today with no file storage at all. One CSV
per section, concatenated with a blank line and a section header row, columns fixed:

- `invoices`: number, issue_date, due_date, customer, currency, subtotal, tax_total, total, status
- `payments`: received_on, customer, currency, amount, method, reference
- `expenses`: number, expense_date, category, accounting_code, vendor, currency, amount,
  tax_amount, payment_status, paid_on

`accounting_code` is in there because that column exists for exactly this reason: it is how the
accountant's chart of accounts finds our categories before the Books slice gives us a real one.

## Recurring expenses become real expenses (the scheduled job)

The action manifest lists "recurring expense instances" under scheduled jobs, so the slice ships
the job: `bin/run_recurring_expenses.php`, run daily from the `www-data` crontab (add the line
to `docs/deploy/crontab.example` in the same commit).

For every `recurring_expenses` row with `active = true`, `next_due_on <= current_date`, and
`ends_on` null or `>= next_due_on`, inside one transaction per row:

1. Insert an expense — `number` from the sequence, `description`, `amount`, `currency`,
   `vendor_organization_id`, `category_id`, `department_id` copied from the parent;
   `expense_date = next_due_on`, `due_date = next_due_on`, `payment_status = 'unpaid'`,
   `status = 'submitted'`, `submitted_by = recurring_expenses.created_by`,
   `recurring_expense_id` set.
2. Advance `next_due_on` by the frequency (+7 days / +1 month / +3 months / +1 year).
3. Deactivate the parent when the new `next_due_on` passes `ends_on`.
4. `log_activity('expense.create', 'expense', $id, ['source' => 'cron', 'actor_member_id' =>
   $recurring['created_by'], 'after' => ['amount' => …, 'currency' => …,
   'recurring_expense_id' => …]])`.

The job **catches up**: a parent three months overdue produces three expenses, one per period,
not one lump. It is idempotent by construction — `next_due_on` only moves forward, and the run
takes a transaction-level advisory lock on the table so two invocations cannot double-post, the
same guard `mcp/activity_ingest.py` uses.

## Files (exactly these — no additions)

```
html/expenses/index.php · form.php · view.php · save.php · submit.php · approve.php
             · reject.php · paid.php · reimburse.php · receipt.php · delete.php · bills.php · report.php
             · vendor-contacts-fragment.php · category-defaults-fragment.php
html/expenses/recurring/index.php · form.php · save.php · pause.php · delete.php
html/expenses/exports/index.php · create.php · download.php
html/settings/expense-categories/index.php · save.php · archive.php

app/features/expenses/queries.php    (expenses, recurring expenses, categories)
app/features/expenses/reports.php    (spend report, bills due, accountant export)
app/features/expenses/render.php     (the shared re-renders)

app/views/expenses/expenses.php · expense.php · expense-form.php · bills.php · report.php
                  · recurring.php · recurring-form.php · exports.php
app/views/expenses/partials/expense-table.php · expense-status.php · expense-totals.php
                  · vendor-options.php · contact-options.php · recurring-table.php
                  · export-table.php
app/views/settings/expense-categories.php
app/views/settings/partials/expense-category-row.php

bin/run_recurring_expenses.php
mcp/business_expenses.py
```

## Query functions (signatures fixed; PDO first, no request/response awareness)

```php
// app/features/expenses/queries.php
const EXPENSE_PAGE_SIZE = 25;
const EXPENSE_SORT_ALLOWED = ['expense_date', 'amount', 'number', 'vendor_name'];

expense_period_bounds(string $period): array          // same shape as sales_period_bounds()
find_expenses(PDO, array $filters, string $sort, int $page): array
find_expense_totals(PDO, array $filters): array       // the list footer, per currency
find_expense(PDO, int $id): ?array
insert_expense(PDO, array $f): array                  // number from the sequence, in-transaction
update_expense(PDO, int $id, array $f): array         // refuses unless draft|submitted|rejected
submit_expense(PDO, int $id): array                   // draft -> submitted
approve_expense(PDO, int $id, int $approverId): array // submitted -> approved; stamps approved_by/at
reject_expense(PDO, int $id, string $reason): array   // submitted -> rejected; reason to the log
mark_expense_paid(PDO, int $id, ?string $paidOn, ?string $method): array
mark_expense_reimbursed(PDO, int $id): array
delete_expense(PDO, int $id): bool                    // draft (own) or admin
find_expense_categories(PDO, bool $includeArchived): array
upsert_expense_category(PDO, ?int $id, array $f): array
archive_expense_category(PDO, int $id, bool $archived): array
find_recurring_expenses(PDO, bool $activeOnly): array
find_recurring_expense(PDO, int $id): ?array
upsert_recurring_expense(PDO, ?int $id, array $f): array
pause_recurring_expense(PDO, int $id, bool $active): array
delete_recurring_expense(PDO, int $id): bool
monthly_equivalent(string $amount, string $frequency): string   // the E6 arithmetic, one place

// app/features/expenses/reports.php
spend_summary(PDO, string $period, string $groupBy, array $filters): array
spend_vs_average(PDO, string $period, int $months): array        // E9
bills_due(PDO, int $withinDays): array
find_accountant_exports(PDO): array
create_accountant_export(PDO, string $from, string $to, string $format, array $includes): array
accountant_export_rows(PDO, int $exportId): array                // regenerates; used by download.php
```

`find_expenses()` takes its filters as `q`, `period`, `category_id`, `vendor_organization_id`,
`status`, `payment_status`, `missing_receipt`, `mine`, `overdue` — names matching the manifest's
screen params, so the registry's params and the query's filters are the same words.

## Action-manifest entries (copied from the manifest — do not invent)

All 15 rows of the manifest's Expenses table, each keeping its endpoint, params, undo, confirm
flag, approval category, log event and gate exactly as written there:

| Action | File | Approval | Log | Who |
| --- | --- | --- | --- | --- |
| `expense_create` | `save.php` | money (over 250) | `expense.create` | all (own), mod:expenses |
| `expense_update` | `save.php` | | `expense.update` | own, mod:expenses |
| `expense_submit` | `submit.php` | | `expense.submit` | own |
| `expense_approve` | `approve.php` | | `expense.approve` | admin |
| `expense_reject` | `reject.php` | | `expense.reject` | admin |
| `expense_mark_paid` | `paid.php` | money | `expense.mark_paid` | mod:expenses |
| `expense_attach_receipt` | `receipt.php` | | `expense.attach_receipt` | own, mod:expenses |
| `expense_delete` | `delete.php` | delete (✔ confirm) | `expense.delete` | own (draft), admin |
| `recurring_expense_create` | `recurring/save.php` | money | `recurring_expense.create` | mod:expenses |
| `recurring_expense_update` | `recurring/save.php` | | `recurring_expense.update` | mod:expenses |
| `recurring_expense_pause` | `recurring/pause.php` | | `recurring_expense.pause` | mod:expenses |
| `recurring_expense_delete` | `recurring/delete.php` | delete (✔ confirm) | `recurring_expense.delete` | admin |
| `accountant_export_create` | `exports/create.php` | | `accountant_export.create` | mod:expenses |
| `expense_category_save` | `/settings/expense-categories/save.php` | | `expense_category.save` | admin |
| `expense_category_archive` | `/settings/expense-categories/archive.php` | | `expense_category.archive` | admin |

The live policies these match (`db/053`, already installed and active) are
`expense.create` over **250 USD**, `expense.mark_paid`, `recurring_expense.create` and the
catch-all `*.delete` — all `applies_to = 'agents'`, so a person is never paused and an agent
always is. `check_approval()` is called **before** the write, with the expense's `amount` and
`currency`, and a match writes the `approval_requests` row, emits `pending_approval`, and
executes nothing.

When the slice is built, **the manifest rows must name the endpoints in full and use the
endpoint's own field names**, then `php bin/build_action_registry.php` regenerates
`mcp/action_registry.json` and these 15 actions become voice-reachable tools.

## Activity log events

One `log_activity()` per successful state change with the manifest's exact event name, plus
`log_screen_view()` on every GET screen. Money events (`expense.create`, `expense.update`,
`expense.mark_paid`, `recurring_expense.create`, `recurring_expense.update`) put `amount` and
`currency` in `after`; `expense.update` and `expense.reject` also carry `before`.
`expense.reject` puts the reason in `after`. The cron job logs with `source => 'cron'` and the
parent's `created_by` as the actor.

## MCP tools this slice must leave working

Implemented in `mcp/business_expenses.py`, registered from `records_server.py` exactly as
`mcp/business_contacts.py` and `mcp/business_sales.py` are:

| Tool | Questions | Views |
| --- | --- | --- |
| `spend_summary` | E1, E2, E3, E9 | `mcp_expenses`, `mcp_expense_categories` |
| `find_expenses` | E2, E5, E10 | `mcp_expenses` |
| `bills_due` | E4 | `mcp_expenses` |
| `recurring_costs` | E6 | `mcp_recurring_expenses` |
| `accountant_export_status` | E13 | `mcp_accountant_exports` |

Parameters exactly as `docs/business-os-mcp-tool-surface.md` fixes them. E11 is answered by the
existing `record_history` and E12 by `approval_history` + `ai_changes` — both already built;
this slice only has to produce data they can read, which the logging above guarantees.

**Also in scope: finish the sales slice's `unbilled_work` for expenses (E8).** The sales slice
shipped `unbilled_work()` (`app/features/sales/reports.php`) and the `unbilled-work` screen as
an empty state waiting for phase 3. Expenses now make one of its three arms real: billable
expenses not yet invoiced — `billable = true AND invoice_line_id IS NULL`, grouped by customer,
the exact shape `expenses_unbilled_idx` was built for. Fill that arm in the sales feature file
and in the `unbilled_work` MCP tool, and leave the hours and jobs arms stubbed with their
existing message. Do **not** extend `invoice_add_unbilled` to pull expenses onto an invoice —
writing `expenses.invoice_line_id` is a sales-side write and belongs to the phase-3 pass that
turns that action on for all three arms at once.

**Correction, found in review 2026-09-18.** Filling a *read* arm silently activates a *write*
path, which this spec did not foresee: `unbilled_work()` used to return `[]` always, so
`html/invoices/add-unbilled.php`'s loop never ran. With expenses in it the loop goes live and
does two wrong things — it never writes `expenses.invoice_line_id`, so the same expense is
billed again on every click, and it copies the tax-**inclusive** `amount` into a line with
`tax_rate_id = null`, so gross is charged as net and the invoice's tax lands on top of tax.
`add-unbilled.php` therefore now filters `kind = 'expense'` out of what it bills and says why.
The phase-3 pass that turns this action on for all three arms owns both fixes; until then the
expenses arm is read-only, which is all E8 asks for.

## Out of scope for this slice

- **Receipts and file storage** (decided above) — `expense_attach_receipt` answers and writes
  nothing; no `documents` insert, no storage root, no upload.
- **Posting to the general ledger.** The Books slice owns `journal_entries` and the posting
  rules that book an expense. Do **not** write to `journal_*` here.
- **AI spend (E14, E15).** `ai_usage_postings`, `ai_usage_post` and the `ai_spend` tool belong
  to AI ops (phase 5), even though the action's gate mentions `mod:expenses`.
- **`cost_breakdown` (E7).** It needs `mcp_time_entries` and `mcp_projects` with data in them;
  it belongs to the Projects slice, which owns the tool.
- **`bank_transaction_to_expense`** (Books) and **`purchase_order_to_bill`** (Inventory) — both
  log `expense.create`, both live in their own slices.
- Expense policies and per-member spending limits, mileage and per-diem rates, multi-currency
  conversion, split expenses across categories, corporate-card feeds, xlsx export, and a vendor
  detail screen (the manifest has none; E3 is answered by `spend-report` grouped by vendor).

## Acceptance (the demo this slice owes)

Seed three categories (Software, Travel, Office) with accounting codes. Then:

1. A plain user **with no expenses grant** records a 42.50 lunch — one form, defaults accepted —
   sees it in their own list, and sees nothing else. `find_expenses(submitted_by_me)` answers
   the same one row for them through MCP (E10).
2. A dept-admin approves it; a second submission is rejected with a reason; both read back
   through `record_history` (E11).
3. A bill: 890.00 hosting, due in 9 days, unpaid, vendor Acme → appears in `bills-due` with the
   right badge → `expense_mark_paid` settles it and it leaves the list (E4).
4. A recurring cost: 49.00/month, `next_due_on` set in the past → `bin/run_recurring_expenses.php`
   materializes the overdue months as unpaid bills, advances `next_due_on`, and a second run
   creates nothing. `recurring_costs` answers the monthly equivalent (E6).
5. `spend-report` grouped by category, then by vendor, then by month, over this quarter, with
   the 3-month comparison column populated (E1, E2, E3, E9).
6. `missing_receipt=1` returns every expense and says why (E5); Attach receipt answers
   "arrives with the Documents module in phase 4" through the action channel as `status: error`,
   not as a 200 with a form.
7. An **agent** creates a 400 USD expense through the actions server: paused as an approval
   request, nothing written; the same agent's 80 USD expense writes normally (the 250 threshold).
   `approval_history` shows the paused one (E12).
8. `accountant_export_create` for last month, then download: the CSV carries the invoice,
   payment and expense sections with accounting codes, and `accountant-exports` shows the row
   counts and the download stamp (E13).
9. Spoken through the command bar: *"log a forty dollar lunch with the Acme team, billable"*
   (the manifest's own example), *"which bills are due this week"*, *"what did we spend on
   software this quarter"* — each reaching the right action or screen.
10. 375px: the expense list scrolls in `.table-responsive`, the form is one column, the report's
    per-currency tables stack, and no header action row overflows.

## Escalations raised while writing this spec

1. **No file storage exists on this server.** Decided rather than guessed (2026-09-18): receipts
   defer to the Documents slice, and the accountant export streams instead of storing. The
   Documents slice therefore inherits an unbuilt storage layer and two waiting consumers —
   `expenses.receipt_document_id` and `accountant_exports.document_id`. Its spec must say so.
2. **`tax_amount` is inclusive, not additive** (`CHECK (tax_amount <= amount)`). It is the
   opposite of the invoice-line convention in the sales slice, where tax is added to the line
   subtotal. Both are correct for their side of the books — you *know* what a bill's gross was,
   you *compute* what an invoice's gross will be — but any later code that moves money between
   the two must convert deliberately. Worth stating in the Books slice's posting rules.

## Review findings (planning-class conformance review, 2026-09-18)

The worker built the slice and raised one escalation rather than improvising; the review found
three further gaps, all of them **this spec's**, not the build's. All five are closed.

1. **`mark_expense_reimbursed` had no endpoint and no manifest row** (the worker's escalation,
   correctly refused rather than invented). Closed: `expense_mark_reimbursed` added to the
   manifest's Expenses table — `/expenses/reimburse.php`, param **expense**, undo back to
   approved, money approval, log `expense.mark_reimbursed`, gate `mod:expenses` (reimbursing an
   employee is treasury, like marking a bill paid) — plus the endpoint and the header button.
   `approved → reimbursed` now closes the submission lifecycle through the action channel.
2. **The department default lived only in the form, not the write path.** `expense_create` is a
   voice action: a caller that sends no `department_id` (the assistant, an agent, any MCP
   client) created a department-less expense that **no dept-admin could ever see or approve**.
   Proven in review — an expense created over HTTP landed with `department_id` NULL and the
   Accounting dept-admin got a 404 trying to approve it. Closed: `save.php` and
   `recurring/save.php` default to the member's first department on create, NULL only when they
   have none. Re-verified: the agent's own expense now lands in Accounting.
3. **The accountant export was silently short of whatever the reader could not see.** It reads
   across modules — invoices and payments through `mcp_invoices` / `mcp_payments` (gated on
   `sales`), expenses through `mcp_expenses` (gated on `expenses`) — so a reader holding only
   one grant got a file missing the rest, with `row_counts` recording the omission as though it
   were a fact about the period. Proven: the same person, same period, produced **0 invoices
   without the sales grant and 2 with it**. Closed: a section the caller cannot read in full is
   refused by name at creation ("Invoices cannot be exported without the sales module grant"),
   because a financial export that changes shape by reader is worse than one that refuses.
4. **`period_end` was excluded from every export.** The queries read `>= :from AND < :to` with
   `:to` bound to `period_end` itself, so an export for 1–30 September silently dropped
   30 September — the last day of every accounting period. Closed: all six comparisons are now
   `<= :to`.
5. **The exports screens admitted a dept-admin who would then see nothing.** PHP's
   `has_module()` admits any business admin to a module screen, but `mcp_accountant_exports` is
   gated on the bare grant (`app_has_module`) with no dept-admin bypass, because
   `accountant_exports` has no department column to scope by. A dept-admin could create an
   export and then get a 404 downloading it. Closed: `require_export_access()` checks the real
   grant, so admission to the screen is not mistaken for admission to the data.

Accepted without change, recorded so the next reader is not surprised:

- **`approve_expense()` takes a third parameter**, `int $approverId`, which this spec's Query
  functions section omitted while still requiring `approved_by` to be stamped. Every query
  function in this codebase receives its actor explicitly and never reads session state, so the
  worker added the parameter rather than break that rule. The spec's signature is the one that
  was wrong.
- **`currency` is a `<select>` over a curated 12-code list** that always includes whatever is
  already on the record, so no existing value can be lost. Server-side validation is unchanged
  ("3 letters"). A currencies master table belongs to a later settings pass.
- **The categories settings screen and the cron job read base tables**, not the `mcp_*` views:
  the settings screen needs archived rows (mirroring `find_catalog_items_admin` in the sales
  exemplar) and a CLI run carries no member session for `app_can_see()` (mirroring every
  existing `bin/cron/*.php`). Both are the established pattern, not a new exception.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none) — the worker's `mark_expense_reimbursed` escalation was answered in review (finding 1).
