-- 059_inventory_products.sql
-- Products and stock: a product master that quotes and invoices draw on, stock locations
-- (warehouses, vans, shelves -- physical places, NOT the estate's compute locations),
-- levels, movements, and purchase orders to replenish them.
-- Questions: IV1-IV12. Module grant: 'inventory'.

BEGIN;

CREATE TABLE products (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku                     text NOT NULL UNIQUE,
    name                    text NOT NULL,
    description             text,
    kind                    text NOT NULL DEFAULT 'stock'
                                CHECK (kind IN ('stock', 'service', 'bundle', 'digital')),
    catalog_item_id         bigint REFERENCES catalog_items(id) ON DELETE SET NULL,
    unit                    text NOT NULL DEFAULT 'each',
    cost_price              numeric(14,2) CHECK (cost_price >= 0),
    unit_price              numeric(14,2) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    currency                char(3) NOT NULL DEFAULT 'USD',
    tax_rate_id             bigint REFERENCES tax_rates(id) ON DELETE SET NULL,
    track_stock             boolean NOT NULL DEFAULT true,
    reorder_point           numeric(14,3) CHECK (reorder_point >= 0),
    reorder_quantity        numeric(14,3) CHECK (reorder_quantity > 0),
    barcode                 text,
    supplier_organization_id bigint REFERENCES organizations(id) ON DELETE SET NULL,
    income_account_id       bigint REFERENCES gl_accounts(id) ON DELETE SET NULL,
    cogs_account_id         bigint REFERENCES gl_accounts(id) ON DELETE SET NULL,
    inventory_account_id    bigint REFERENCES gl_accounts(id) ON DELETE SET NULL,
    archived_at             timestamptz,
    created_by              bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (kind <> 'stock' OR track_stock)
);
CREATE INDEX products_name_trgm    ON products USING gin (name gin_trgm_ops);
CREATE INDEX products_supplier_idx ON products (supplier_organization_id);
CREATE INDEX products_catalog_idx  ON products (catalog_item_id);
CREATE INDEX products_kind_idx     ON products (kind) WHERE archived_at IS NULL;
CREATE INDEX products_created_by_idx ON products (created_by);
CREATE INDEX products_income_acct_idx ON products (income_account_id);
CREATE INDEX products_cogs_acct_idx  ON products (cogs_account_id);
CREATE INDEX products_inv_acct_idx  ON products (inventory_account_id);

-- Where stock physically sits. A stock location may sit at an estate location (the office
-- has a supply cupboard) but is its own thing: vans and rented units are not compute.
CREATE TABLE stock_locations (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               text NOT NULL UNIQUE,
    kind               text NOT NULL DEFAULT 'warehouse'
                           CHECK (kind IN ('warehouse', 'shop', 'vehicle', 'supplier', 'other')),
    address            text,
    estate_location_id bigint REFERENCES locations(id) ON DELETE SET NULL,
    department_id      bigint REFERENCES departments(id) ON DELETE SET NULL,
    is_default         boolean NOT NULL DEFAULT false,
    is_active          boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX stock_locations_default_idx ON stock_locations ((true)) WHERE is_default AND is_active;
CREATE INDEX stock_locations_estate_idx ON stock_locations (estate_location_id);
CREATE INDEX stock_locations_dept_idx   ON stock_locations (department_id);

CREATE TABLE stock_levels (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id         bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    stock_location_id  bigint NOT NULL REFERENCES stock_locations(id) ON DELETE CASCADE,
    quantity           numeric(14,3) NOT NULL DEFAULT 0,
    reserved_quantity  numeric(14,3) NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    average_cost       numeric(14,4) CHECK (average_cost >= 0),
    last_counted_at    timestamptz,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (product_id, stock_location_id)
);
CREATE INDEX stock_levels_location_idx ON stock_levels (stock_location_id);
CREATE INDEX stock_levels_low_idx      ON stock_levels (product_id) WHERE quantity <= 0;

CREATE TABLE stock_movements (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id         bigint NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    stock_location_id  bigint NOT NULL REFERENCES stock_locations(id) ON DELETE RESTRICT,
    kind               text NOT NULL CHECK (kind IN ('receipt', 'sale', 'return', 'adjustment',
                                                     'transfer_in', 'transfer_out', 'count',
                                                     'write_off')),
    quantity           numeric(14,3) NOT NULL CHECK (quantity <> 0),   -- signed
    unit_cost          numeric(14,4) CHECK (unit_cost >= 0),
    reference_type     text,                                  -- 'invoice', 'purchase_order', 'expense'
    reference_id       bigint,
    counterpart_id     bigint REFERENCES stock_movements(id) ON DELETE SET NULL,  -- transfer pair
    journal_entry_id   bigint REFERENCES journal_entries(id) ON DELETE SET NULL,
    note               text,
    moved_at           timestamptz NOT NULL DEFAULT now(),
    created_by         bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stock_movements_product_idx ON stock_movements (product_id, moved_at DESC);
CREATE INDEX stock_movements_loc_idx     ON stock_movements (stock_location_id, moved_at DESC);
CREATE INDEX stock_movements_ref_idx     ON stock_movements (reference_type, reference_id);
CREATE INDEX stock_movements_entry_idx   ON stock_movements (journal_entry_id);
CREATE INDEX stock_movements_counter_idx ON stock_movements (counterpart_id);
CREATE INDEX stock_movements_by_idx      ON stock_movements (created_by);

CREATE TABLE purchase_orders (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_number              text UNIQUE,                        -- next_document_number('purchase_order')
    vendor_organization_id bigint REFERENCES organizations(id) ON DELETE SET NULL,
    stock_location_id      bigint REFERENCES stock_locations(id) ON DELETE SET NULL,
    department_id          bigint REFERENCES departments(id) ON DELETE SET NULL,
    status                 text NOT NULL DEFAULT 'draft'
                               CHECK (status IN ('draft', 'sent', 'partial', 'received',
                                                 'cancelled')),
    order_date             date,
    expected_date          date,
    received_at            timestamptz,
    currency               char(3) NOT NULL DEFAULT 'USD',
    subtotal               numeric(16,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    tax_total              numeric(16,2) NOT NULL DEFAULT 0 CHECK (tax_total >= 0),
    total                  numeric(16,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    expense_id             bigint REFERENCES expenses(id) ON DELETE SET NULL,   -- the bill it became
    notes                  text,
    owner_member_id        bigint REFERENCES members(id) ON DELETE SET NULL,
    created_by             bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX purchase_orders_vendor_idx ON purchase_orders (vendor_organization_id);
CREATE INDEX purchase_orders_status_idx ON purchase_orders (status, expected_date);
CREATE INDEX purchase_orders_expense_idx ON purchase_orders (expense_id);
CREATE INDEX purchase_orders_loc_idx    ON purchase_orders (stock_location_id);
CREATE INDEX purchase_orders_dept_idx   ON purchase_orders (department_id);
CREATE INDEX purchase_orders_owner_idx  ON purchase_orders (owner_member_id);
CREATE INDEX purchase_orders_created_by_idx ON purchase_orders (created_by);

CREATE TABLE purchase_order_lines (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_order_id   bigint NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    sort_order          integer NOT NULL DEFAULT 0,
    product_id          bigint REFERENCES products(id) ON DELETE SET NULL,
    description         text NOT NULL,
    quantity            numeric(14,3) NOT NULL CHECK (quantity > 0),
    received_quantity   numeric(14,3) NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
    unit_cost           numeric(14,4) NOT NULL CHECK (unit_cost >= 0),
    tax_rate_id         bigint REFERENCES tax_rates(id) ON DELETE SET NULL,
    line_total          numeric(16,2) NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX purchase_order_lines_po_idx      ON purchase_order_lines (purchase_order_id, sort_order);
CREATE INDEX purchase_order_lines_product_idx ON purchase_order_lines (product_id);
CREATE INDEX purchase_order_lines_tax_idx     ON purchase_order_lines (tax_rate_id);

-- Sales documents can now name a product (IV4, IV7).
ALTER TABLE invoice_lines ADD COLUMN product_id bigint REFERENCES products(id) ON DELETE SET NULL;
ALTER TABLE quote_lines   ADD COLUMN product_id bigint REFERENCES products(id) ON DELETE SET NULL;
CREATE INDEX invoice_lines_product_idx ON invoice_lines (product_id);
CREATE INDEX quote_lines_product_idx   ON quote_lines (product_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['products', 'stock_locations', 'stock_levels', 'stock_movements',
                             'purchase_orders', 'purchase_order_lines'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL TO app_rw USING (true) WITH CHECK (true)',
                       t || '_app_rw', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['products', 'stock_locations', 'stock_levels', 'purchase_orders',
                             'purchase_order_lines'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                       t || '_touch', t);
    END LOOP;
END$$;

-- Visibility: the product list is open to insiders (anyone quoting needs prices); stock,
-- movements and purchase orders need the inventory module. Costs are for the module holders.
CREATE OR REPLACE VIEW mcp_products WITH (security_barrier = true) AS
SELECT p.id AS product_id, p.sku, p.name, p.description, p.kind, p.unit, p.unit_price,
       p.currency, p.tax_rate_id, p.track_stock, p.barcode, p.supplier_organization_id,
       p.reorder_point, p.reorder_quantity, p.archived_at,
       CASE WHEN app_has_module('inventory') OR app_is_super_admin() THEN p.cost_price END AS cost_price,
       (SELECT coalesce(sum(sl.quantity), 0) FROM stock_levels sl
         WHERE sl.product_id = p.id) AS quantity_on_hand
FROM products p
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_stock_locations WITH (security_barrier = true) AS
SELECT s.id AS stock_location_id, s.name, s.kind, s.address, s.estate_location_id,
       l.name AS estate_location_name, s.department_id, s.is_default, s.is_active
FROM stock_locations s LEFT JOIN locations l ON l.id = s.estate_location_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_stock_levels WITH (security_barrier = true) AS
SELECT sl.id AS stock_level_id, sl.product_id, p.sku, p.name AS product_name,
       sl.stock_location_id, s.name AS stock_location_name, sl.quantity, sl.reserved_quantity,
       (sl.quantity - sl.reserved_quantity) AS available_quantity,
       CASE WHEN app_has_module('inventory') OR app_is_super_admin() THEN sl.average_cost END AS average_cost,
       p.reorder_point, (p.reorder_point IS NOT NULL AND sl.quantity <= p.reorder_point) AS below_reorder,
       sl.last_counted_at
FROM stock_levels sl
JOIN products p        ON p.id = sl.product_id
JOIN stock_locations s ON s.id = sl.stock_location_id
WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_stock_movements WITH (security_barrier = true) AS
SELECT m.id AS stock_movement_id, m.product_id, p.sku, p.name AS product_name,
       m.stock_location_id, s.name AS stock_location_name, m.kind, m.quantity, m.unit_cost,
       m.reference_type, m.reference_id, m.journal_entry_id, m.note, m.moved_at, m.created_by
FROM stock_movements m
JOIN products p        ON p.id = m.product_id
JOIN stock_locations s ON s.id = m.stock_location_id
WHERE app_has_module('inventory');

CREATE OR REPLACE VIEW mcp_purchase_orders WITH (security_barrier = true) AS
SELECT po.id AS purchase_order_id, po.po_number, po.vendor_organization_id,
       o.name AS vendor_name, po.stock_location_id, po.department_id, po.status, po.order_date,
       po.expected_date, po.received_at, po.currency, po.subtotal, po.tax_total, po.total,
       po.expense_id, po.notes, po.owner_member_id, po.created_at
FROM purchase_orders po LEFT JOIN organizations o ON o.id = po.vendor_organization_id
WHERE app_can_see('inventory', po.owner_member_id, po.department_id, 'purchase_order', po.id,
                  po.vendor_organization_id);

CREATE OR REPLACE VIEW mcp_purchase_order_lines WITH (security_barrier = true) AS
SELECT pl.id AS purchase_order_line_id, pl.purchase_order_id, pl.sort_order, pl.product_id,
       p.sku, pl.description, pl.quantity, pl.received_quantity, pl.unit_cost, pl.tax_rate_id,
       pl.line_total
FROM purchase_order_lines pl
JOIN purchase_orders po ON po.id = pl.purchase_order_id
LEFT JOIN products p    ON p.id = pl.product_id
WHERE app_can_see('inventory', po.owner_member_id, po.department_id, 'purchase_order', po.id,
                  po.vendor_organization_id);

GRANT SELECT ON mcp_products, mcp_stock_locations, mcp_stock_levels, mcp_stock_movements,
    mcp_purchase_orders, mcp_purchase_order_lines
TO app_records_ro;

INSERT INTO stock_locations (name, kind, is_default)
SELECT 'Main store', 'warehouse', true
WHERE NOT EXISTS (SELECT 1 FROM stock_locations WHERE is_default AND is_active);

COMMIT;
