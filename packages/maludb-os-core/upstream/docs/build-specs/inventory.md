# Build spec: Products & inventory — "what do we have, what did it cost, and what is on order?"

2026-09-19 · Module 8 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/059 (`products`, `stock_locations`, `stock_levels`, `stock_movements`,
`purchase_orders`, `purchase_order_lines`; `invoice_lines.product_id`, `quote_lines.product_id`;
six `mcp_*` views) + additive **db/112**. Manifest "Products & inventory": 15 screens, 12 actions.
Tools: `find_products`, `stock_levels`, `stock_movements`, `product_sales`, `purchase_orders`.
Out of scope by decision: bins, lots, serials, BOMs, manufacturing, FX conversion.

## db/112 (additive)
- `product_id` and `product_sku` appended as the LAST columns of `mcp_invoice_lines` and
  `mcp_quote_lines` (security barrier and grants kept) — the line tables have had the column
  since db/059; the views never showed it.
- GL accounts, only if the chart lacks the code: **2050 Goods received not invoiced**
  (liability), **5100 Inventory adjustments and write-offs** (expense).
- Posting rules for source `inventory`, keyed by movement kind: `receipt` Dr 1400 Inventory /
  Cr 2050 GRNI; `write_off`, `adjustment`, `count` Dr 5100 / Cr 1400 (a gain posts the other way
  round); the existing default rule (Dr 5000 COGS / Cr 1400) is what a `sale` uses, and a
  `return` posts it reversed. An expense category **Stock purchases** with its own expense rule
  Dr 2050 / Cr 2000 Accounts payable — so the bill made from a purchase order clears GRNI instead
  of counting the purchase twice.

## Weighted average cost (owner's decision 13) — `app/features/inventory/stock.php`
One function writes every movement (`stock_move()`), under a row lock on the product's level at
that location, so the purchase orders, the adjust screens and the invoice hook share one copy.
- The average is kept **per product per location** (`stock_levels.average_cost`, as db/059 has
  it); `products.cost_price` is kept equal to the quantity-weighted average across locations
  after every costed receipt — it is "the product's average cost" the decision names.
- **Coming in with a cost** (receipt, transfer in, an adjustment or count gain given a
  `unit_cost`): new average = (on hand × average + received × cost) ÷ (on hand + received).
  **Into zero or negative on-hand the received cost simply becomes the average** — a negative
  balance has no cost worth averaging.
- Coming in with no cost given (a found item, a count gain): it arrives at the current average
  (else the product's cost price); the average does not move.
- **Going out** (sale, transfer out, write-off, loss): at the current average; the movement
  records the unit cost it left at; the average does not move.
- A stock count sets the quantity to what was counted: the difference is one `count` movement.

## Stock out on invoices (decision 14) — the smallest hook
`html/invoices/send.php` calls `stock_issue_for_invoice()` after the invoice is marked sent;
`void.php` and `credit-issue.php` call `stock_return_for_invoice()`. Only lines with a
`product_id` of a stock-tracked product count. **Idempotent by arithmetic, not by a flag:** what
the invoice needs per product minus what its movements (`reference_type = 'invoice'`) have
already issued net — so a re-send issues nothing. Stock leaves the default stock location.
A void puts back everything issued, at the cost it left at. A credit note is an amount, not
lines: **when issued credit notes cover the whole invoice the stock comes back; a partial
credit returns nothing by itself** (the goods may not have come back) — recorded OPEN.
**Not enough stock never blocks the sale:** the level goes negative, the action's answer says
so, and the product and stock screens flag it — recorded OPEN. Drafts and quotes reserve nothing.

## Product picker (decision 15)
The add-a-line row of the invoice and quote pages gains "or pick a product" beside the catalogue
select; `line_fields_from_request()` reads `product_id`, fills blank description / price / tax
from the product, and the two line upserts and the quote→invoice copy write it. The catalogue
stays for services. A line shows its SKU.

## Purchase orders
`draft` → `sent` (number allocated on save; send emails the supplier through MaluMail —
template `emails/purchase-order` — if the supplier has an address, and says so if not; confirm;
an agent's send waits for approval) → `partial` / `received` by receipts → optionally a bill
(`purchase_order_to_bill` makes an approved-able expense in **Stock purchases** for what was
received; needs `mod:expenses` too; once only). Cancel: admin, not after anything was received.
Receiving takes `line:quantity` pairs (blank = everything outstanding), never more than is
outstanding, and moves stock in at the line's unit cost.

## Through the agents' door
Repeated parameters are flat text: `lines[]` = `product:quantity:unit_cost` (product by id or
SKU; a first part that is neither is a free-text description), `counts[]` =
`product:counted_quantity`, `received[]` = `line:quantity`. The forms post parallel arrays
(`line_product[]` …) to the same parser. `product`, `stock_location`, `vendor`, `supplier` and
`purchase_order` accept an id, or a SKU / exact name / PO number — resolved in PHP through the
`mcp_*` views. `stock_write_off` needs admin, confirms, and an agent's waits (`money`).

## Ledger (decision 16)
The posting run gains source `inventory`: every costed stock movement with no journal entry
(`receipt`, `sale`, `return`, `write_off`, `adjustment`, `count`; transfers move no value) posts
|quantity| × unit cost on its date, accounts from the rule for its kind — a product's own
inventory / COGS account wins where set — and stamps `stock_movements.journal_entry_id`.
Idempotent (left join on `journal_entries` by `stock_movement`), period-aware, a movement with
no cost is skipped with that reason.

## Who may do what
Products, locations and levels are readable by any insider (cost and value only with
`mod:inventory` or super — the views mask them); movements and purchase orders need the grant
(`mcp_stock_movements`, `app_can_see('inventory', …)`). Every write is `mod:inventory`;
write-off, PO send and PO cancel also need admin; PO → bill also `mod:expenses`.

## Screens
As the manifest lists them: `/inventory` (+ `new`, `{id}`, `{id}/edit`), `/inventory/stock`,
`/inventory/movements`, `/inventory/adjust` (adjust · transfer · write off on one page),
`/inventory/count`, `/inventory/orders` (+ `new`, `{id}`, `{id}/edit`, `{id}/receive`),
`/settings/stock-locations` (the add form beside the list; `/new` redirects there).
