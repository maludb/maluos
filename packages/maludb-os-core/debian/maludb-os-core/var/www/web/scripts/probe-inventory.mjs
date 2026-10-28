// The forms the agents' door does not exercise (they post parallel arrays): raise a purchase order with a product
// line and a described line, send it (the smoke supplier has no email — nothing is mailed), receive part of it on
// the receive page, then record a count. Usage: scripts/verify.sh <member> --probe scripts/probe-inventory.mjs <supplier-org-id> <product-id>
import { chromium } from "playwright";
const [sid, supplier, product] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 375, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
page.on("dialog", (d) => d.accept());
const settle = async () => { await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200); };

await page.goto("http://127.0.0.1:3000/inventory/orders/new", { waitUntil: "networkidle" });
await page.selectOption("#purchase-order-form-field-vendor", supplier);
await page.selectOption("#po-line-product-0", product);
await page.fill("#po-line-quantity-0", "8");
const cost = await page.inputValue("#po-line-cost-0");
await page.click("#purchase-order-form-add-line");
await page.fill("#po-line-description-1", "SMOKE probe pallet charge");
await page.fill("#po-line-quantity-1", "1");
await page.fill("#po-line-cost-1", "12.5");
await page.locator("#purchase-order-form").evaluate((f) => f.requestSubmit());
await page.waitForURL(/\/inventory\/orders\/\d+$/, { timeout: 20000 }); await settle();
const orderUrl = page.url();
console.log(`raised -> ${orderUrl.split("/").pop()} "${(await page.locator("h5, .page-header-title").first().textContent()).trim()}"; product cost prefilled ${cost}; lines ${await page.locator("#purchase-order-lines-table tbody tr").count()}; total ${(await page.locator("#purchase-order-lines-table tfoot tr").last().textContent()).trim()}`);
await page.locator("#purchase-order-send-form").evaluate((f) => f.requestSubmit()); await settle();
console.log(`sent -> status "${(await page.locator("#purchase-order-facts-card .badge").first().textContent()).trim()}"; receive offered: ${await page.locator("#purchase-order-receive-btn").count()}`);
await page.goto(`${orderUrl}/receive`, { waitUntil: "networkidle" });
const boxes = page.locator("[id^=purchase-order-receive-qty-]");
console.log(`receive page -> ${await boxes.count()} boxes, first starts at ${await boxes.first().inputValue()}`);
await boxes.first().fill("5");
await page.locator("#purchase-order-receive-form").evaluate((f) => f.requestSubmit());
await page.waitForURL(/\/inventory\/orders\/\d+$/, { timeout: 20000 }); await settle();
console.log(`received -> status "${(await page.locator("#purchase-order-facts-card .badge").first().textContent()).trim()}"; bill offered: ${await page.locator("#purchase-order-bill-btn").count()}`);

await page.goto("http://127.0.0.1:3000/inventory/count", { waitUntil: "networkidle" });
const box = page.locator(`#stock-count-qty-${product}`);
const books = (await box.locator("xpath=ancestor::tr/td[2]").textContent()).trim();
await box.fill(String(Number(books) - 1));
await page.locator("#stock-count-form").evaluate((f) => f.requestSubmit());
await page.waitForURL(/\/inventory\/stock/, { timeout: 20000 }); await settle();
console.log(`count -> books said ${books}, counted ${Number(books) - 1}; landed on ${page.url().replace("http://127.0.0.1:3000", "")}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
await browser.close();
