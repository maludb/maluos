# Build spec: Sales & invoicing slice

2026-09-18 · build plan phase 2, slice 1 · planning-class spec for a worker build

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`; code under
`html/contacts/`, `app/features/contacts/`, `app/views/contacts/`). Everything that spec fixes
— the gate, view-reads, the endpoint sequence, the render helpers, the shared components —
applies here unchanged. This document names only the substitutions.

Module grant: `sales` · Manifest section: **Sales & invoicing**
Schema tables (never modify): `tax_rates`, `catalog_items`, `quotes`, `quote_lines`,
`invoices`, `invoice_lines`, `payments`, `payment_allocations`, `credit_notes`
(`db/037_sales_invoicing.sql`).
Read views: `mcp_quotes`, `mcp_quote_lines`, `mcp_invoices`, `mcp_invoice_lines`,
`mcp_payments`, `mcp_payment_allocations`, `mcp_credit_notes`, `mcp_tax_rates`,
`mcp_catalog_items`, plus `mcp_organizations` / `mcp_contacts` / `mcp_deals` for pickers.
Questions this slice must answer: S1–S14, S19, S20, DB1, DB3.

> **Online collection is a separate slice.** Payment links, provider webhooks, refunds,
> disputes, payouts and reconciliation (`db/038`, screens `online-payments`, `refund-add`,
> `payments-settings`, actions `payment_link_*`, `refund_create`, `payment_provider_disable`)
> wait for `docs/build-specs/sales-online-payments.md`. **Unblocked 2026-09-18: the provider
> is Stripe.** This slice is unchanged by that — it still writes no provider code and still
> leaves `invoices.online_payment_enabled` writable on the form and unused; the online slice is
> what reads it.

## Gate and visibility

- Module gate `mod:sales` — `require_module('sales')` in **every** endpoint, GET and POST.
- `invoice_void`, `invoice_write_off`, `payment_delete`, `credit_note_issue`,
  `catalog_item_*`, `tax_rate_*` are `admin` → `require_business_admin()`.
- Reads through `mcp_*` views only. Writes to base tables after the gate.
- Department stamping: `owner_member_id` defaults to the creating member; `department_id` is
  chosen from the member's departments (super-admin: any), exactly as Contacts does it.

## Money rules (this slice sets the precedent for every money module)

1. **Stored totals, computed in one place.** `quotes`/`invoices` carry `subtotal`, `tax_total`,
   `total`; invoices also carry `amount_paid`, `amount_credited`, `balance_due`. They are
   written by the app whenever lines, payments or credits change, by **one** function per
   document (`recalculate_invoice()`, `recalculate_quote()`) called inside the same
   transaction as the change. No screen computes a total of its own.
2. **A line's money is line-level.** `line_subtotal = round(quantity × unit_price, 2)`,
   `line_tax = round(line_subtotal × rate / 100, 2)`, `line_total = line_subtotal + line_tax`.
   Tax is rounded per line, never on the document total.
3. **One currency per document.** The document's currency comes from the organization's
   `currency`, else the business base currency, and is fixed once a line exists. Never convert.
4. **Numbers are taken on issue, not at creation** — `next_document_number('quote'|'invoice'|
   'credit_note')`, called inside the transaction that issues the document. **Revised
   2026-09-18 by `db/066`.** This spec first said "number on send", then corrected itself to
   "number at creation" because the installed schema made `number` `NOT NULL`, and recorded the
   consequence as an escalation: a deleted draft burned a number and left a hole in the issued
   sequence. That escalation is now **answered** — gapless numbering was chosen, `db/066` makes
   `invoices.number` and `credit_notes.number` nullable, a draft carries NULL and the screens
   show "Draft", and the number is assigned by `send_invoice()` / `issue_credit_note()` with
   `COALESCE(number, next_document_number(...))` in the same transaction as the status change.
   Because `document_sequences` is a TABLE updated transactionally rather than a Postgres
   SEQUENCE, a rolled-back send returns the number — which is precisely why gapless works here.
   A `CHECK (status = 'draft' OR number IS NOT NULL)` keeps an issued document from escaping
   without one. **Quotes keep creation-time numbering on purpose**: a quote is not a tax
   document, no jurisdiction requires its sequence to be gapless, and an abandoned quote is a
   normal outcome rather than a hole to explain.
5. **Paid is derived, never typed.** `amount_paid` = sum of `payment_allocations`;
   `amount_credited` = sum of issued `credit_notes`; `balance_due = total − amount_paid −
   amount_credited`. Status follows: `balance_due <= 0` → `paid`; `0 < amount_paid` →
   `partially_paid`; else the document keeps `sent`/`viewed`.
6. **Money actions log their amount.** Every `log_activity()` for an action in this slice puts
   `amount` and `currency` in `after` — the approval thresholds and the audit views read them.

## Status vocabulary (locked by the schema)

- Quote: `draft` secondary · `sent` info · `accepted` success · `declined` danger ·
  `expired` warning · `converted` dark.
- Invoice: `draft` secondary · `sent` info · `viewed` info · `partially_paid` warning ·
  `paid` success · `void` dark · `written_off` danger. **Overdue is not a status** — it is
  `balance_due > 0 AND due_date < today`, rendered as a `danger` badge beside the status.
- Credit note: `draft` secondary · `issued` success · `void` dark.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `quotes-list` | `/quotes/` | browse quotes | `status`, `organization` |
| `quote-add` | `/quotes/new` | write a quote | `organization`, `deal` |
| `quote-view` | `/quotes/{id}` | one quote | — |
| `quote-edit` | `/quotes/{id}/edit` | edit a draft quote | — |
| `invoices-list` | `/invoices/` | browse invoices | `status`, `overdue`, `organization`, `project`, `period` |
| `invoice-add` | `/invoices/new` | write an invoice | `organization`, `project`, `from_quote` |
| `invoice-view` | `/invoices/{id}` | one invoice with payments and credits | — |
| `invoice-edit` | `/invoices/{id}/edit` | edit a draft invoice | — |
| `payments-list` | `/payments/` | payments received | `period`, `organization`, `source`, `unallocated` |
| `payment-add` | `/payments/new` | record a payment | `invoice`, `organization`, `amount` |
| `payment-view` | `/payments/{id}` | one payment and its allocations | — |
| `credit-note-add` | `/invoices/{id}/credit` | credit part of an invoice | — |
| `receivables` | `/sales/receivables` | who owes money, how overdue | `as_of` |
| `statement-view` | `/sales/statements/{organization_id}` | a customer statement | `period` |
| `unbilled-work` | `/sales/unbilled` | billable work not invoiced | `organization` |
| `revenue-report` | `/sales/report` | invoiced / collected / tax by period | `metric`, `period`, `group_by` |
| `catalog-settings` | `/settings/catalog` | products and services | — |
| `tax-rates-settings` | `/settings/tax-rates` | tax rates | — |

`unbilled-work` shows an empty state until Time, Scheduling and Expenses land ("nothing
billable yet — hours and expenses arrive with phase 3"), and `invoice_add_unbilled` is built
but returns that same message. It is in this slice so the invoice screen has its place for it.

## List screens

**`invoices-list`** — columns: Number (link) · Customer · Issued · Due (with an overdue badge)
· Status · Total · Paid · Balance · Actions (Edit for drafts, otherwise View). Search matches
`number` and the organization name. Filters: `status`, `overdue=1`, `organization`, `project`,
`period` (over `issue_date`). Sort allowlist `number`, `issue_date`, `due_date`, `balance_due`
(default `issue_date DESC`). Page size 25. **Footer row: totals per currency for the current
filter** — invoiced, paid, outstanding.

**`quotes-list`** — Number · Customer · Issued · Valid until (expired badge when past and still
`sent`) · Status · Total · Actions. Same shape otherwise.

**`payments-list`** — Received · Customer · Amount · Method · Source (`manual` / `online`) ·
Allocated (amount, and an `unallocated` warning badge when `amount_allocated < amount`) ·
Actions. Filter `unallocated=1` is the one that matters: it is how money gets matched.

## Detail screens

**`invoice-view`** — header: number, status badge (+ overdue), customer, issue and due dates,
total, paid, balance. Panels: **Lines** (inline editable while `draft`, read-only after) ·
**Payments** (allocations, with Record a payment) · **Credit notes** · **Activity** (this
record's history, `/activity?entity_type=invoice&entity_id={id}`) · **Notes** (shared comments
component) · **Tags**. Actions in the page header, by status: draft → Send, Edit, Delete;
sent/viewed/partially_paid → Send reminder, Record payment, Credit, Void, Write off; paid →
Credit, Void.

**`quote-view`** — same shape; actions: draft → Send, Edit, Delete; sent → Accept, Decline;
accepted → **Convert to invoice** (the button the money loop turns on).

**`payment-view`** — the payment, its allocations, and an allocate form listing that customer's
open invoices oldest first.

## Reports

- **`receivables`** — aging buckets (current, 1–30, 31–60, 61–90, 90+) per currency, rows per
  customer with their open invoices, `as_of` defaulting to today. Each bucket links to
  `invoices-list` filtered.
- **`statement-view`** — one customer: opening balance, then invoices, payments and credits in
  date order with a running balance, for the period; a Send statement action.
- **`revenue-report`** — `metric` ∈ invoiced | collected | tax; `group_by` ∈ month | customer |
  tax_rate; a table per currency. No chart in this slice.

## Forms

**Quote / invoice form** (`quote-add|edit`, `invoice-add|edit`), ids `{quote|invoice}-form-field-{name}`:
`organization_id` (✔, searchable select), `contact_id` (options limited to that organization —
Pattern A fragment, exactly like the deal form's contact select), `deal_id`, `project_id`
(hidden until Projects lands), `issue_date` (✔ default today), `due_date` (invoice ✔ — default
`issue_date + organization.payment_terms_days ?? business default`) / `valid_until` (quote,
default `issue_date + 30`), `currency` (from the organization, read-only once a line exists),
`notes`, `terms`, `online_payment_enabled` (invoice only, checkbox, stored and otherwise unused
in this slice).

**Lines editor** — the exemplar's inline child-row pattern (`hx-include="closest tr"`, region
re-render, never a `<form>` in a `<tr>`): columns Description (✔), Catalog item (select —
picking one fills description, unit price and tax rate), Quantity (✔ > 0, ≤ 9999), Unit price
(✔ ≥ 0), Tax rate (select from `mcp_tax_rates`, default the `is_default` rate), Line total
(computed, read-only), Remove. A blank "add a line" row sits at the bottom, as the pipeline
stage editor does. **Every line write re-renders the whole lines region and the totals panel**,
because both change together.

**Payment form** (`payment-add`): `amount` (✔ > 0), `received_on` (✔ default today), `method`
(✔ cash/check/bank_transfer/card/online/other), `organization_id`, `invoice_id` (optional — when
given, the payment is allocated to it on save, capped at that invoice's `balance_due`),
`reference`, `notes`. `source` is always `manual` here; `online` rows arrive from the provider
in the other slice.

**Credit note form** (`credit-note-add`): `amount` (✔ > 0, ≤ invoice `balance_due`), `reason`.
Created as `draft`; `credit_note_issue` (admin, confirm, money approval) is what applies it.

## Files (exactly these — no additions)

```
html/quotes/index.php · form.php · view.php · save.php · line-save.php · line-remove.php
              · send.php · accept.php · decline.php · convert.php · delete.php · contacts-fragment.php
html/invoices/index.php · form.php · view.php · save.php · line-save.php · line-remove.php
              · add-unbilled.php · send.php · remind.php · void.php · write-off.php · delete.php
              · credit.php · credit-save.php · credit-issue.php
html/payments/index.php · form.php · view.php · save.php · allocate.php · unallocate.php · delete.php
html/sales/receivables.php · statement.php · statement-send.php · unbilled.php · report.php
html/settings/catalog/index.php · save.php · archive.php
html/settings/tax-rates/index.php · save.php · archive.php

app/features/sales/queries.php      (quotes, invoices, lines, totals)
app/features/sales/payments.php     (payments, allocations, credit notes)
app/features/sales/reports.php      (receivables, statement, revenue)
app/features/sales/render.php       (the shared re-renders)

app/views/sales/quotes.php · quote.php · quote-form.php
app/views/sales/invoices.php · invoice.php · invoice-form.php
app/views/sales/payments.php · payment.php · payment-form.php · credit-form.php
app/views/sales/receivables.php · statement.php · unbilled.php · report.php
app/views/sales/partials/quote-table.php · invoice-table.php · payment-table.php
                        · lines.php · line-row.php · totals.php · document-actions.php
app/views/settings/catalog.php · tax-rates.php
                        · partials/catalog-row.php · tax-rate-row.php
```

## Query functions (signatures fixed)

```php
// app/features/sales/queries.php
const SALES_PAGE_SIZE = 25;
find_quotes(PDO, array $filters, string $sort, int $page): array
find_quote(PDO, int $id): ?array
find_quote_lines(PDO, int $quoteId): array
insert_quote(PDO, array $f): array            // draft, no number yet
update_quote(PDO, int $id, array $f): array   // refuses unless status = 'draft'
send_quote(PDO, int $id): array               // assigns the number, status sent, sent_at
accept_quote(PDO, int $id): array
decline_quote(PDO, int $id, ?string $reason): array
convert_quote(PDO, int $id): array            // creates the draft invoice, copies lines, links both
delete_quote(PDO, int $id): bool              // draft only
upsert_quote_line(PDO, int $quoteId, ?int $lineId, array $f): array
remove_quote_line(PDO, int $lineId): bool
recalculate_quote(PDO, int $quoteId): array   // the ONE place a quote's totals are written

find_invoices(PDO, array $filters, string $sort, int $page): array
find_invoice_totals(PDO, array $filters): array        // the list footer, per currency
find_invoice(PDO, int $id): ?array
find_invoice_by_number(PDO, string $number): ?array
find_invoice_lines(PDO, int $invoiceId): array
insert_invoice(PDO, array $f): array
update_invoice(PDO, int $id, array $f): array          // draft only
send_invoice(PDO, int $id): array                      // number + status + sent_at
mark_invoice_viewed(PDO, int $id): array
void_invoice(PDO, int $id, string $reason): array
write_off_invoice(PDO, int $id, ?string $reason): array
delete_invoice(PDO, int $id): bool                     // draft only
upsert_invoice_line(PDO, int $invoiceId, ?int $lineId, array $f): array
remove_invoice_line(PDO, int $lineId): bool
recalculate_invoice(PDO, int $invoiceId): array        // totals, paid, credited, balance, status

// app/features/sales/payments.php
find_payments(PDO, array $filters, int $page): array
find_payment(PDO, int $id): ?array
find_payment_allocations(PDO, int $paymentId): array
find_open_invoices_for(PDO, int $organizationId): array
insert_payment(PDO, array $f): array
allocate_payment(PDO, int $paymentId, int $invoiceId, string $amount): array   // recalculates the invoice
unallocate_payment(PDO, int $paymentId, int $invoiceId): bool
delete_payment(PDO, int $id): bool                     // manual only; recalculates every invoice it touched
find_credit_notes(PDO, int $invoiceId): array
insert_credit_note(PDO, int $invoiceId, string $amount, ?string $reason): array
issue_credit_note(PDO, int $id): array                 // status issued; recalculates the invoice

// app/features/sales/reports.php
receivables_aging(PDO, ?string $asOf, ?int $organizationId): array
customer_statement(PDO, int $organizationId, string $period): array
revenue_summary(PDO, string $metric, string $period, string $groupBy): array
unbilled_work(PDO, ?int $organizationId): array        // empty until phase 3 modules exist

// catalog + tax rates live with the settings screens
find_catalog_items(PDO, bool $includeArchived): array
upsert_catalog_item(PDO, ?int $id, array $f): array
archive_catalog_item(PDO, int $id, bool $archived): array
find_tax_rates(PDO, bool $includeArchived): array
upsert_tax_rate(PDO, ?int $id, array $f): array
archive_tax_rate(PDO, int $id, bool $archived): array
```

## Sending (`quote_send`, `invoice_send`, `invoice_send_reminder`, `statement_send`)

Outbound mail goes through the app's existing `send_email()` helper (MaluMail — see the
`htmx-php-builder:malumail-send` skill; `MALUMAIL_API_KEY`, `MAIL_FROM` and `MAIL_FROM_NAME`
are already configured and already carrying the fork's invitations). Each send: renders the document to HTML, sends to `to_email` (default the
contact's, else the organization's), writes `sent_at` / `last_reminder_at` / `reminder_count`,
logs the manifest event, and **confirms first** (manifest decision 4 — a send cannot be undone).
A failed send is reported to the user and leaves the document's status unchanged. Agents are
paused on every send by the standing policies, so `check_approval()` comes before the send, not
after.

## Action-manifest entries

Copied from the manifest's Sales & invoicing table — 30 actions. Every one keeps its endpoint,
params, undo, confirm flag, approval category, log event and gate exactly as written there.
When the slice is built, **the params must name the endpoint's real fields** and the endpoints
must be spelled in full, then `php bin/build_action_registry.php` regenerates the registry and
these actions become voice-reachable tools.

## MCP tools this slice must leave working

`find_invoices`, `get_invoice`, `receivables_aging`, `revenue_summary`, `customer_statement`,
`quotes_pipeline` — implemented in `mcp/business_sales.py`, registered from
`records_server.py` exactly as `mcp/business_contacts.py` is. `online_payments`,
`refunds_and_disputes` and `payment_reconciliation` belong to the online-payments slice.

Acceptance includes asking each of these through the records server against data the screens
created.

## Out of scope for this slice

- Everything in `db/038` (online collection) — its own spec, see the note at the top.
- Posting to the general ledger: the Books slice owns `journal_entries`, and its spec adds the
  posting rules that book an invoice, a payment and a credit note. Do **not** write to
  `journal_*` here.
- Recurring invoices, dunning schedules, multi-currency conversion, PDF generation (the send
  is HTML mail in this slice), partial-line tax overrides, and discounts.

## Acceptance (the demo this slice owes)

A quote for Acme → send → accept → **convert to invoice** → send → record a partial payment →
record the rest → the invoice reads `paid`, receivables drops to zero, the statement shows the
running balance, and `revenue_summary` and `find_invoices` answer through MCP. Then: void a
different invoice, write one off, and issue a credit note, each with its approval and log row.

## Escalations raised while building

1. ~~**Document numbering is not gapless.**~~ **Answered 2026-09-18: made gapless.** The
   decision was taken before the Bookkeeping slice, because the ledger makes document numbering
   audit-visible and an auditor reads a hole in the sequence as a deleted invoice. `db/066`
   makes `invoices.number` / `credit_notes.number` nullable and moves assignment to send/issue;
   see money rule 4. Verified: a draft created and deleted consumed nothing, the sequence
   advanced only on send, and the issued set ran INV-00001..INV-00003 with no hole.
2. **`balance_due` is a generated column** (`total - amount_paid - amount_credited`, STORED).
   The recalculation writes the inputs and lets the database derive it — worth knowing before
   any later slice tries to set it.

## Open Questions (must be EMPTY before a worker starts)

- (none) — the sending address was the one open question and the environment answers it:
  `MAIL_FROM` / `MAIL_FROM_NAME` in `config/.env` are already configured and already sending
  the fork's invitations and notifications, so documents go out from the same verified address
  through `send_email()`. A per-business override belongs to the business-settings screen, not
  to this slice.
