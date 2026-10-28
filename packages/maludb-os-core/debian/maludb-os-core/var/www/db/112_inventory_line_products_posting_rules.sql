-- 112: Products & inventory (docs/build-specs/inventory.md). ADDITIVE.
--
-- 1. invoice_lines / quote_lines have carried product_id since db/059; their read views never
--    showed it, so a product picked on a line could not be read back. product_id and the
--    product's SKU are appended as the LAST columns. WHERE clauses, security barriers, every
--    existing column and the grants are unchanged.
-- 2. Two GL accounts the stock postings need, added only if the chart has no such code, and the
--    posting rules per stock-movement kind (owner's decision 16). Nothing existing is altered:
--    the default `inventory` rule (Dr 5000 COGS / Cr 1400 Inventory) stays what a sale uses.
-- 3. An expense category for the bill a purchase order becomes, posting Dr GRNI / Cr payable,
--    so a purchase is not counted once at receipt and again at the bill.
BEGIN;

CREATE OR REPLACE VIEW mcp_invoice_lines WITH (security_barrier = true) AS
SELECT il.id AS invoice_line_id, il.invoice_id, il.sort_order, il.catalog_item_id, il.appointment_id,
       il.description, il.quantity, il.unit_price, il.tax_rate_id, tr.name AS tax_rate_name,
       tr.rate AS tax_rate, il.line_subtotal, il.line_tax, il.line_total,
       il.product_id, (SELECT p.sku FROM products p WHERE p.id = il.product_id) AS product_sku
FROM invoice_lines il
JOIN mcp_invoices i ON i.invoice_id = il.invoice_id
LEFT JOIN tax_rates tr ON tr.id = il.tax_rate_id;

CREATE OR REPLACE VIEW mcp_quote_lines WITH (security_barrier = true) AS
SELECT ql.id AS quote_line_id, ql.quote_id, ql.sort_order, ql.catalog_item_id, ql.description,
       ql.quantity, ql.unit_price, ql.tax_rate_id, ql.line_subtotal, ql.line_tax, ql.line_total,
       ql.product_id, (SELECT p.sku FROM products p WHERE p.id = ql.product_id) AS product_sku
FROM quote_lines ql
JOIN mcp_quotes q ON q.quote_id = ql.quote_id;

INSERT INTO gl_accounts (code, name, account_type, is_system, description)
SELECT v.code, v.name, v.account_type, true, v.description
  FROM (VALUES ('2050', 'Goods received not invoiced', 'liability', 'Stock that has arrived and not been billed yet; the bill from a purchase order clears it.'),
               ('5100', 'Inventory adjustments and write-offs', 'expense', 'Stock written off, lost or found at a count.')) AS v(code, name, account_type, description)
 WHERE NOT EXISTS (SELECT 1 FROM gl_accounts a WHERE a.code = v.code);

INSERT INTO gl_posting_rules (source, match_key, debit_account_id, credit_account_id, note)
SELECT 'inventory', v.match_key,
       (SELECT id FROM gl_accounts WHERE code = v.debit), (SELECT id FROM gl_accounts WHERE code = v.credit), v.note
  FROM (VALUES ('receipt',    '1400', '2050', 'Stock received: into inventory, owed until the bill arrives'),
               ('write_off',  '5100', '1400', 'Stock written off'),
               ('adjustment', '5100', '1400', 'Stock adjusted down (a gain posts the other way round)'),
               ('count',      '5100', '1400', 'Stock count difference (a gain posts the other way round)')) AS v(match_key, debit, credit, note)
 WHERE NOT EXISTS (SELECT 1 FROM gl_posting_rules r WHERE r.source = 'inventory' AND r.match_key = v.match_key)
   AND (SELECT id FROM gl_accounts WHERE code = v.debit) IS NOT NULL
   AND (SELECT id FROM gl_accounts WHERE code = v.credit) IS NOT NULL;

INSERT INTO expense_categories (name, accounting_code)
SELECT 'Stock purchases', '2050'
 WHERE NOT EXISTS (SELECT 1 FROM expense_categories WHERE name = 'Stock purchases');

INSERT INTO gl_posting_rules (source, match_key, debit_account_id, credit_account_id, note)
SELECT 'expense', c.id::text, (SELECT id FROM gl_accounts WHERE code = '2050'), (SELECT id FROM gl_accounts WHERE code = '2000'),
       'The bill for received stock clears goods received not invoiced'
  FROM expense_categories c
 WHERE c.name = 'Stock purchases'
   AND NOT EXISTS (SELECT 1 FROM gl_posting_rules r WHERE r.source = 'expense' AND r.match_key = c.id::text)
   AND (SELECT id FROM gl_accounts WHERE code = '2050') IS NOT NULL
   AND (SELECT id FROM gl_accounts WHERE code = '2000') IS NOT NULL;

COMMIT;
