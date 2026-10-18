# Build spec: Bookkeeping & the ledger slice

2026-09-18 · build plan phase 2, slice 3 · planning-class spec for a worker build
**This slice closes M3.**

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`), with the money
conventions the **Sales & invoicing** slice set (`docs/build-specs/sales-invoicing.md`) and the
review lessons the **Expenses** slice recorded (`docs/build-specs/expenses.md` — read its
"Review findings" section before starting; three of its five defects are mistakes this spec
could repeat). This document names only the substitutions.

Module grant: `books` · Manifest section: **Bookkeeping & the ledger**
Schema tables (never modify): `gl_accounts`, `fiscal_periods`, `journal_entries`,
`journal_lines`, `gl_posting_rules`, `bank_accounts`, `bank_transactions`,
`bank_reconciliations`, `ai_usage_postings` (`db/056_general_ledger.sql`).
Read views: `mcp_gl_accounts`, `mcp_fiscal_periods`, `mcp_journal_entries`, `mcp_journal_lines`,
`mcp_gl_posting_rules`, `mcp_bank_accounts`, `mcp_bank_transactions`,
`mcp_bank_reconciliations`, `mcp_ai_usage_postings`, plus `mcp_invoices`, `mcp_payments`,
`mcp_credit_notes`, `mcp_expenses` for the posting run.
Questions this slice must answer: **GL1–GL13** (GL14 needs the prompt ledger — see Out of scope).

## What the database already guarantees (do not re-implement in PHP)

`db/056` carries the accounting rules in triggers. A worker that duplicates these in PHP has
written a second, weaker copy that will disagree:

- `journal_lines` has `CHECK ((debit > 0) <> (credit > 0))` — exactly one side per line.
- `gl_check_posting()` refuses to post an entry with no lines, one that does not balance, or
  one whose period is not `open`; it **writes `total_debit` / `total_credit` itself** on post
  and stamps `posted_at`. It also refuses `posted → draft` outright: *a posted entry is
  reversed, never un-posted.*
- `gl_lines_immutable()` refuses any insert, update or delete of a line on a posted entry.
- `fiscal_periods` has an `EXCLUDE USING gist` on overlapping date ranges: two periods cannot
  overlap, and the database says so.

The app's job is to present these rules, not to restate them. Catch the `PDOException`, read
its message, and show it as a field error — the exemplar's `citext`-unique handling in the
expense-categories screen is the pattern.

## Seeded and already installed (do not re-seed, do not migrate)

- **21 accounts** in `gl_accounts`, `is_system = true`, renameable but not deletable —
  1000 Cash on hand, 1010 Business checking (`is_bank`), 1200 Accounts receivable,
  1400 Inventory, 1500 Fixed assets, 2000 Accounts payable, 2100 Sales tax payable,
  2200 Payroll liabilities, 3000 Owner equity, 3900 Retained earnings, 4000 Sales revenue,
  4100 Service revenue, 5000 Cost of goods sold, 6000 Salaries and wages,
  6050 AI and model usage, 6500 Bank and payment fees, 6900 Other expenses, and the rest.
- **8 posting rules** in `gl_posting_rules`, one per source with a NULL `match_key` (the
  default): invoice → DR 1200 / CR 4100 · payment → DR 1010 / CR 1200 ·
  credit_note → DR 4100 / CR 1200 · expense → DR 6900 / CR 2000 · ai_usage → DR 6050 / CR 2000 ·
  payroll → DR 6000 / CR 2200 · inventory → DR 5000 / CR 1400 · bank_fee → DR 6500 / CR 1010.
- **No fiscal periods, no bank accounts and no journal entries exist yet.** The slice creates
  the first period through its own screen; it does **not** seed one.

## Gate and visibility

- Module gate `mod:books` — **`require_module_grant('books')`** in **every** endpoint, GET and
  POST. Unlike Expenses there is no own-records departure: there is no such thing as "my"
  journal entry. The books are the business's.
  *(Corrected in review 2026-09-18: this spec first said `require_module('books')`, which admits
  any business admin to the screens while `app_can_see_books()` shows them nothing. See review
  finding 1.)*
- **A comma in the manifest's Who column means OR, not AND.** `mod:books, super` =
  "a books-grant holder **or** a super-admin", so `journal_entry_post`,
  `journal_entry_reverse`, `bank_account_save`, `reconciliation_complete`, `fiscal_period_save`
  and `books_post_documents` take the module gate alone — a super-admin already passes it.
  Requiring both would lock the bookkeeper out of posting, which is the module's core action.
  *(Corrected in review 2026-09-18: this spec first said "and", and the build faithfully
  shipped super-admin-only gates on all six.)*
- `fiscal_period_close` and `fiscal_period_reopen` are `super` **alone** in the manifest —
  `require_super_admin()`, and nothing else may do it. Closing a period is the strongest
  control in the module.
- Reads through `mcp_*` views only. Writes to base tables after the gate.
- **Department stamping:** `journal_entries.department_id` and `journal_lines.department_id`
  are set from the source document's department when posting, and chosen on the form for a
  manual entry. Apply the Expenses slice's finding 2: **the default belongs in the write path,
  not only in the form**, because `journal_entry_save` is a voice action.

## How documents reach the books — the posting run

**Decided 2026-09-18: a deferred posting run, not synchronous posting.** The Sales and
Expenses slices deliberately never wrote to `journal_*` and this slice does not change that.
Nothing in `html/invoices/`, `html/payments/` or `html/expenses/` is edited by this slice.

Instead `post_documents()` finds what is unposted and books it. "Unposted" is a left join, not
a flag on the document: a document has an entry when a `journal_entries` row exists with that
`source`, `source_entity_type` and `source_entity_id` — which is exactly what
`journal_entries_source_idx` indexes. Nothing is added to the document tables.

What posts, and when it becomes eligible:

| Source | Eligible when | Entry | Amount |
| --- | --- | --- | --- |
| `invoice` | `status` not in (`draft`, `void`) | DR receivable / CR revenue per rule | `subtotal` to revenue, `tax_total` to 2100 Sales tax payable as a second credit line, `total` to 1200 |
| `payment` | always (a payment exists only when received) | DR bank / CR receivable | `amount` |
| `credit_note` | `status = 'issued'` | DR revenue / CR receivable | `amount` |
| `expense` | `status` in (`approved`, `reimbursed`) **or** `payment_status = 'paid'` | DR expense / CR payable | **gross `amount`** — see the tax rule below |

- **Rules are read, never hard-coded** (GL9): the accounts come from `gl_posting_rules` matched
  on `source` plus `match_key`, falling back to the NULL-key default. An expense whose
  category has a rule (`match_key = category_id::text`) uses it; otherwise the default.
  **A source with no matching rule is skipped and reported, never guessed.**
- **Expenses post gross** (decided 2026-09-18). The full tax-inclusive `amount` goes to the
  expense account and no input-tax line is written. This is correct where purchase tax is not
  reclaimable — US sales tax is a cost to the buyer — and `tax_amount` stays on the expense
  record for reporting. A VAT/GST business needs an input-tax asset account, which the seeded
  chart does not have, so that is a migration and a later decision, not an improvisation here.
  **Note the asymmetry and do not "fix" it:** invoice tax IS split out (to 2100), because
  output tax is money held for the tax authority; purchase tax is not.
- **One entry per document**, `source_entity_type` / `source_entity_id` set, `entry_date` =
  the document's own date (`issue_date`, `received_on`, `expense_date`), `currency` = the
  document's, `memo` naming the document, `department_id` inherited from it.
- **The period must exist and be open.** A document whose date falls in no period, or in a
  closed one, is **skipped and listed** with the reason. It is never posted into the wrong
  period and never silently dropped.
- **Entries are created posted**, in one transaction per document: insert the entry as `draft`,
  insert its lines, then update to `posted` so `gl_check_posting()` runs and writes the totals.
  A failure rolls that document back and the run continues with the next.
- The run is **idempotent by construction** — the left join means a second run finds nothing —
  and takes a transaction-level advisory lock so two invocations cannot double-post, the same
  guard `bin/run_recurring_expenses.php` and `mcp/activity_ingest.py` use.
- It is reachable two ways: `bin/post_documents.php` on a daily cron (add the line to
  `docs/deploy/crontab.example`), and the `books_post_documents` action from `books-home` for a
  period on demand. Both call the same function.
- **Every screen that shows a figure says how current it is.** `books-home` and
  `financial-statements` carry a "posted through {date}" line and the count of documents
  waiting. A statement that silently omits unposted documents is the ledger version of the
  Expenses slice's finding 3, and it is the defect this slice is most likely to ship.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `books-home` | `/books/` | period status, unposted documents, bank gaps | — |
| `chart-of-accounts` | `/books/accounts` | the chart | `type`, `include_archived` |
| `account-add` | `/books/accounts/new` | add an account | — |
| `account-edit` | `/books/accounts/{id}/edit` | rename or re-parent | — |
| `account-view` | `/books/accounts/{id}` | one account's balance and lines | `period` |
| `journal-list` | `/books/journal` | journal entries | `period`, `status`, `source` |
| `journal-entry-add` | `/books/journal/new` | write a manual entry | `date`, `source_entity` |
| `journal-entry-view` | `/books/journal/{id}` | one entry, its lines, its source | — |
| `journal-entry-edit` | `/books/journal/{id}/edit` | correct a draft | — |
| `financial-statements` | `/books/statements` | P&L, balance sheet, trial balance | `statement`, `period`, `compare_to` |
| `fiscal-periods` | `/books/periods` | periods and their state | — |
| `posting-rules` | `/books/posting-rules` | which documents post where | — |
| `bank-accounts` | `/books/banks` | bank and card accounts | — |
| `bank-account-add` | `/books/banks/new` | add a bank account | — |
| `bank-account-view` | `/books/banks/{id}` | one account's transactions | `status`, `period` |
| `bank-import` | `/books/banks/{id}/import` | import a statement file | — |
| `bank-reconcile` | `/books/banks/{id}/reconcile` | reconcile against a statement | `period` |

The installed rewrite rules serve these generically; the `{id}` rules match `[0-9]+` only, so
`/books/accounts`, `/books/journal`, `/books/periods`, `/books/banks` and `/books/statements`
fall through to their own files. No new Apache configuration.

**Corrected in review 2026-09-18:** `bank-import` and `bank-reconcile` were first specified as
`/books/banks/{id}/import` and `/books/banks/{id}/reconcile`, which **no installed rule serves**
— nothing handles a three-segment path with the id in the middle. They are
`/books/banks/import?bank_account={id}` and `/books/banks/reconcile?bank_account={id}`, served
by the existing extensionless-page rule, deep-linkable, and precedented by
`/payments/new?invoice={id}` in the Sales exemplar. The manifest now says the same.

## The journal entry form (the one screen with real structure)

`journal-entry-add|edit`, ids `journal-form-field-{name}`: `entry_date` (✔, default today —
the period is derived from it and shown live, "falls in 2026-09 (open)"), `memo`,
`department_id`, then the **lines editor**: the exemplar's inline child-row pattern
(`hx-include="closest tr"`, region re-render, never a `<form>` in a `<tr>`).

Line columns: Account (✔, searchable select over non-archived `mcp_gl_accounts`, showing
`code — name`) · Description · Debit · Credit · Department · Customer (`organization_id`) ·
Remove. **Debit and credit are mutually exclusive per line** — entering one clears the other in
the re-render, because the database's CHECK will refuse anything else.

Above the Save button, a **running balance strip**: total debits, total credits, and the
difference, recalculated on every line write, with the difference in `danger` until it is zero
and `success` at zero. Post is **disabled while the entry does not balance**, and the endpoint
refuses it anyway — the button is a courtesy, the gate is the trigger.

A blank "add a line" row sits at the bottom, as the invoice lines editor does. Every line write
re-renders the whole lines region **and** the balance strip, because both change together.

## Reports (the M3 screens)

`financial-statements` takes `statement` ∈ `pl` | `balance_sheet` | `trial_balance`, a `period`,
and an optional `compare_to` period. All three read `mcp_journal_lines` joined to
`mcp_gl_accounts` and **count only `posted` entries** — a draft entry is not in the books.

- **Trial balance** — every account with a non-zero balance, debit and credit columns, and a
  **totals row that must be equal**. When it is not, the screen says so loudly rather than
  rendering a quiet wrong number: that is the check M3 exists to demonstrate.
- **P&L** — income and expense accounts for the period, grouped by account type then code,
  with a net profit line. `compare_to` adds a prior-period column and a variance column.
- **Balance sheet** — assets, liabilities and equity **as of** the period end (cumulative from
  the beginning, not just the period), with the accounting equation shown and checked:
  assets = liabilities + equity. Retained earnings for prior periods is the sum of income minus
  expense accounts for all dates before the period start; do not expect a closing entry to have
  been written, because this slice does not write one (see Out of scope).

Each statement renders per currency and **never adds two currencies together**.

## Bank import and reconciliation

- **`bank_import_statement` parses, it does not store.** The uploaded CSV/OFX is read from
  `$_FILES` in memory, parsed into `bank_transactions` rows, and the file is never written to
  disk. This is deliberately unlike the Expenses slice's receipts: a receipt must be kept and
  re-read later, which needs the storage layer the Documents slice owns; a statement is a
  transport for rows and is disposable once parsed. Do **not** add a storage root.
- CSV only in this slice (OFX is a parser's worth of work and not on the M3 path); the form
  offers a `date_format` choice and shows a preview of the first five parsed rows before
  committing the batch.
- `import_batch` gets a generated id so a bad import can be deleted whole.
- Duplicate protection is the schema's: `bank_transactions_external_idx` is unique on
  (`bank_account_id`, `external_ref`). A row whose `external_ref` already exists is **skipped
  and counted**, not inserted and not treated as an error — re-importing an overlapping
  statement is normal.
- **Matching** (`bank_transaction_match`) links a transaction to a payment, an expense or a
  journal entry, setting the matching `matched_*_id`, `matched_at` and `matched_by`. The screen
  suggests candidates: same account, amount equal (to the cent), date within ±5 days, still
  unmatched. Suggestion is not automatic matching — a human or an agent confirms.
- **Reconciliation**: `reconciliation_start` records the statement balance for a period;
  `cleared_balance` is the sum of matched transactions in range; `difference` is the gap.
  `reconciliation_complete` is **refused while `difference <> 0`** (the manifest says so) and is
  the other half of what M3 demonstrates.

## Files (exactly these — no additions)

```
html/books/index.php
html/books/accounts/index.php · form.php · view.php · save.php · archive.php
html/books/journal/index.php · form.php · view.php · save.php · line-save.php · line-remove.php
             · post.php · reverse.php · void.php
html/books/statements.php
html/books/periods/index.php · save.php · close.php · reopen.php
html/books/posting-rules/index.php · save.php
html/books/banks/index.php · form.php · view.php · save.php · import.php · import-preview.php
             · match.php · unmatch.php · ignore.php · to-expense.php
             · reconcile.php · reconcile-start.php · reconcile-complete.php
html/books/post-documents.php

app/features/books/queries.php     (accounts, periods, entries, lines, posting rules)
app/features/books/posting.php     (the posting run and its rule resolution)
app/features/books/statements.php  (P&L, balance sheet, trial balance, account activity)
app/features/books/banks.php       (bank accounts, transactions, matching, reconciliation)
app/features/books/render.php      (the shared re-renders)

app/views/books/home.php · accounts.php · account-form.php · account.php
                · journal.php · journal-entry.php · journal-form.php · statements.php
                · periods.php · posting-rules.php
                · banks.php · bank-form.php · bank.php · import.php · reconcile.php
app/views/books/partials/account-row.php · entry-table.php · entry-lines.php · entry-line-row.php
                · balance-strip.php · period-row.php · posting-rule-row.php
                · bank-transaction-table.php · match-candidates.php · statement-table.php

bin/post_documents.php
mcp/business_books.py
```

## Query functions (signatures fixed)

```php
// app/features/books/queries.php
const BOOKS_PAGE_SIZE = 25;
find_gl_accounts(PDO, ?string $type, bool $includeArchived): array
find_gl_account(PDO, int $id): ?array
upsert_gl_account(PDO, ?int $id, array $f): array
archive_gl_account(PDO, int $id, bool $archived): array   // refuses a system account with a balance
find_fiscal_periods(PDO): array
find_fiscal_period(PDO, int $id): ?array
period_for_date(PDO, string $date): ?array                // the posting run's gate
upsert_fiscal_period(PDO, ?int $id, array $f): array
close_fiscal_period(PDO, int $id, ?string $note, int $by): array
reopen_fiscal_period(PDO, int $id, string $reason, int $by): array
find_journal_entries(PDO, array $filters, int $page): array
find_journal_entry(PDO, int $id): ?array
find_journal_lines(PDO, int $entryId): array
entry_balance(PDO, int $entryId): array                   // debits, credits, difference
insert_journal_entry(PDO, array $f): array                // draft
update_journal_entry(PDO, int $id, array $f): array       // draft only
upsert_journal_line(PDO, int $entryId, ?int $lineId, array $f): array
remove_journal_line(PDO, int $lineId): bool
post_journal_entry(PDO, int $id, int $by): array          // lets the trigger do the checking
reverse_journal_entry(PDO, int $id, string $date, string $reason, int $by): array
void_journal_entry(PDO, int $id, string $reason): array   // draft only
find_posting_rules(PDO, ?string $source): array
upsert_posting_rule(PDO, ?int $id, array $f): array

// app/features/books/posting.php
unposted_documents(PDO, ?string $from, ?string $to): array   // the left join, per source
resolve_posting_rule(PDO, string $source, ?string $matchKey): ?array
post_documents(PDO, ?string $from, ?string $to, int $by): array
    // returns ['posted' => n, 'skipped' => [['source','id','reason'], ...], 'entries' => [...]]
posted_through(PDO): ?string                                // the newest posted entry_date

// app/features/books/statements.php
trial_balance(PDO, string $period): array
profit_and_loss(PDO, string $period, ?string $compareTo): array
balance_sheet(PDO, string $asOf): array
account_activity(PDO, int $accountId, string $period, ?int $organizationId): array

// app/features/books/banks.php
find_bank_accounts(PDO): array
find_bank_account(PDO, int $id): ?array
upsert_bank_account(PDO, ?int $id, array $f): array
parse_statement_csv(string $contents, string $dateFormat): array   // pure; no file written
import_bank_transactions(PDO, int $bankAccountId, array $rows, string $batch): array
find_bank_transactions(PDO, int $bankAccountId, array $filters, int $page): array
match_candidates(PDO, int $transactionId): array
match_bank_transaction(PDO, int $id, string $matchTo, int $targetId, int $by): array
unmatch_bank_transaction(PDO, int $id): bool
ignore_bank_transaction(PDO, int $id, ?string $reason): array
start_reconciliation(PDO, int $bankAccountId, string $from, string $to, string $statementBalance): array
complete_reconciliation(PDO, int $id, ?string $note, int $by): array   // refuses if difference <> 0
```

## Action-manifest entries

The manifest's 18 Bookkeeping rows, unchanged, **plus one this slice adds** because the
deferred posting run needs a door:

| Action | File | Params | Undo | Confirm | Approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `books_post_documents` | `/books/post-documents.php` | period_start, period_end | reverse the entries | ✔ | money | `journal_entry.post_batch` | mod:books, super |

Add that row to `docs/business-os-action-manifest.md` in the same commit, then
`php bin/build_action_registry.php`. Every other row keeps its endpoint, params, undo, confirm
flag, approval category, log event and gate exactly as written there, spelled in full with the
endpoint's own field names — the pattern the Sales and Expenses slices set.

## Activity log events

One `log_activity()` per successful state change with the manifest's exact event name, plus
`log_screen_view()` on every GET screen. Money events (`journal_entry.post`,
`journal_entry.reverse`, `journal_entry.post_batch`) carry `amount` and `currency` in `after`.
`fiscal_period.close` / `.reopen` carry the period name and the reason — GL10 and GL13 are
answered from exactly these rows, and `books_audit` reads them. The posting run logs with
`source => 'cron'` when run from cron and the acting member when run from the screen.

## MCP tools this slice must leave working

Implemented in `mcp/business_books.py`, registered from `records_server.py` exactly as
`business_contacts.py`, `business_sales.py` and `business_expenses.py` are:

| Tool | Questions | Views |
| --- | --- | --- |
| `financial_statement` | GL1, GL2, GL3 | `mcp_journal_lines`, `mcp_gl_accounts`, `mcp_fiscal_periods` |
| `account_activity` | GL4, GL11 | `mcp_journal_lines`, `mcp_gl_accounts` |
| `find_journal_entries` | GL5, GL6, GL12 | `mcp_journal_entries`, `mcp_journal_lines` |
| `bank_status` | GL7, GL8 | `mcp_bank_transactions`, `mcp_bank_accounts`, `mcp_bank_reconciliations` |
| `posting_rules` | GL9 | `mcp_gl_posting_rules`, `mcp_gl_accounts` |
| `books_audit` | GL10, GL13 | `mcp_fiscal_periods`, `mcp_journal_entries` |

Parameters exactly as `docs/business-os-mcp-tool-surface.md` fixes them. `books_audit`'s
`check` parameter takes `periods` / `edits` / `ai_usage`; **implement `periods` and `edits`
only** and have `ai_usage` answer "the prompt ledger arrives with AI ops in phase 5" — GL14
cannot be answered before the ledger it reconciles against exists.

## Out of scope for this slice

- **Year-end closing entries.** No `source = 'closing'` entry is written; the balance sheet
  computes retained earnings from prior-period income and expense instead. Closing the year is
  its own decision (which account, what date, reversible or not) and belongs with a later pass.
- **GL14 and `ai_usage_postings`.** The prompt ledger is phase 5; `ai_usage_post` lives in
  AI ops. Leave `mcp_ai_usage_postings` unread.
- **Payroll and inventory posting.** Their rules are seeded and their sources are in the
  `journal_entries.source` CHECK, but `pay_runs` and `stock_movements` have no slice yet. The
  posting run handles `invoice`, `payment`, `credit_note` and `expense` only, and says so on
  `books-home` rather than implying the books are complete.
- **Multi-currency consolidation.** Each statement renders per currency; no conversion, no
  FX gain/loss account, no revaluation.
- **OFX/QFX import, bank feeds** (`bank_accounts.feed_provider` / `feed_secret_id` stay
  unwritten — a live feed needs the applications registry and a real secret store), budget vs
  actual, departmental P&L as a separate screen (the `department_id` filter covers it), and any
  edit to the Sales or Expenses slices.

## Acceptance (the demo this slice owes — this is M3)

With the data already in the database (3 issued invoices, 3 payments, ~13 expenses):

1. Create fiscal periods for the months in play; `books-home` shows them open and reports the
   unposted document count.
2. Run `books_post_documents` for the period. Every eligible document books: invoices split
   subtotal/tax, payments hit the bank account, expenses post gross. The skipped list names any
   document whose date falls outside a period, with the reason.
3. **The trial balance balances** — debits equal credits, shown on screen.
4. The P&L for the period shows service revenue and the expense accounts; the balance sheet as
   of period end satisfies assets = liabilities + equity.
5. `find_journal_entries` with `source_entity_type=invoice` answers "what did INV-00003 post?"
   through MCP (GL6), and the entry view links back to the invoice.
6. Run the posting run a second time: **nothing posts** (idempotent).
7. A manual journal entry: two lines that do not balance → Post refused by the trigger, the
   message shown as a field error; fix the line, post, then **reverse** it and see both entries
   with the reversal link.
8. Close the period → posting into it is refused, by the database, with the reason on screen.
   Reopen it as super-admin with a reason; `books_audit` shows both in the trail (GL10).
9. A bank account, a small CSV statement imported (duplicates skipped and counted), one
   transaction matched to a payment, a reconciliation started with a statement balance and
   **refused until the difference is zero**, then completed (GL7, GL8).
10. 375px: the journal lines editor scrolls in `.table-responsive`, the balance strip stays
    readable, statements stack per currency, and no header action row overflows.

## Review findings (planning-class conformance review, 2026-09-18)

The worker built the slice, found and fixed four of its own bugs before handing back, and
raised two escalations rather than improvising. The review found three more. All are closed.

**Raised by the worker, resolved here:**

1. **`app_can_see_books()` has no dept-admin bypass, unlike the PHP gate** — proven: a
   dept-admin with no `books` grant reached every screen (200 OK) and saw nothing, because
   `app_can_see_books()` is literally `app_has_module('books')`. The worker proposed a migration
   adding a dept-admin branch. **Rejected** — that would let an HR dept-admin read the whole
   general ledger, and the books have no department to scope by. **The gate was tightened
   instead**: a new `require_module_grant()` in `app/business.php` admits only a grant holder or
   a super-admin, and every books endpoint uses it. Admission to the screen is not admission to
   the data. *(Note for the doc vocabulary: `mod:x` means "super-admin, or a dept-admin within
   their departments, or a grant holder"; for a business-wide module the middle clause is empty,
   so it collapses to "super-admin or grant holder" — which is what this enforces.)*
2. **`/books/banks/{id}/import` and `/books/banks/{id}/reconcile` are served by no installed
   rewrite rule** — nothing handles a three-segment path with the id in the middle, so this
   spec's "No new Apache configuration" claim was false. **Accepted the worker's substitution**:
   `?bank_account={id}`, precedented by `/payments/new?invoice={id}` in the Sales exemplar. The
   manifest and this spec now both say so; no Apache change.

**Found in review:**

3. **A comma in the manifest's Who column means OR, not AND — and this spec said "and".** The
   build faithfully put `require_super_admin()` on `journal_entry_post`,
   `journal_entry_reverse`, `bank_account_save`, `reconciliation_complete`, `fiscal_period_save`
   and `books_post_documents`, which **locks the bookkeeper out of posting**, the module's whole
   point. Corrected: those take the module gate alone (a super-admin already passes it);
   `fiscal_period_close` and `fiscal_period_reopen` stay super-admin-only, which is what the
   manifest actually says.
4. **The posting run saw only what its operator could see — the third appearance of one defect
   class.** `unposted_documents()` read `mcp_invoices` / `mcp_payments` / `mcp_credit_notes` /
   `mcp_expenses`, which are gated on the *sales* and *expenses* grants. Proven: as a
   books-grant holder without `sales`, books-home reported **"0 documents waiting — the books
   are current"** while a 3,600.00 invoice sat unposted and invisible. The count was the mild
   half; the serious half is that `books_post_documents` run by that person would have posted a
   **subset** of the business's documents and reported success, leaving the books quietly
   incomplete. Fixed: the posting run reads the source **base tables**, deliberately and with
   the reasoning in the docblock — posting is a system function, not a personal view of the
   business, and anyone who can read the general ledger can already see these amounts through
   the journal. (Compare Expenses finding 3, the accountant export that was silently short of
   whatever its reader could not see, and finding 1 above. Three modules, one root cause: an
   application reading across modules through grant-scoped views.)
5. **`financial_statement` failed on every call with a named period** — `'str' object has no
   attribute 'toordinal'`. Period bounds come back through `json.loads()` as strings and asyncpg
   binds `date` parameters strictly; then, once converted, the response serializer tripped on
   the same objects. The empty database the tool was built against could not reach either path.
   Fixed at the source (`_period_dates()`) plus `default=str` on the affected responses. GL1,
   GL2 and GL3 now answer.

**Fixed by the worker before hand-back, recorded because each is a trap for the next slice:**
19 of 36 endpoints never called `books_require_files()` (every write action 500'd); a template
variable named `data` collided with `view(string $template, array $data)`'s own parameter so
`extract()` silently refused it and the statements screen always rendered "No posted activity";
the balance sheet computed liability and equity balances on the wrong sign and omitted the
current period's earnings from equity; and `bin/post_documents.php` ran with no session, so
every RLS-gated read returned nothing and the daily job would have posted zero documents
forever.

**Accepted without change:** `payments` and `credit_notes` carry no `department_id`, so entries
from those sources have a NULL department — there is nothing to inherit. `journal_entries.entry_no`
is assigned at post time, not draft creation, mirroring `db/066`'s gapless reasoning: a failed
post burns no number.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none) — both worker escalations were answered in review (findings 1 and 2).
