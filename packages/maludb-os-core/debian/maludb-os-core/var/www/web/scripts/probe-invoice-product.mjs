// The product picker on an invoice's new line (Inventory, owner's decision 15): pick a product with the description
// left blank, save, and the line arrives with the product's name, price and SKU; then edit that line's quantity and
// the SKU badge must survive (the line keeps its product through an edit — that is what takes stock out on send).
// Usage: scripts/verify.sh <member> --probe scripts/probe-invoice-product.mjs <draft-invoice-id> <product-id>
import { chromium } from "playwright";
const [sid, invoice, product] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:3000/invoices/${invoice}`, { waitUntil: "networkidle" });
  const rows = () => page.locator("tr[id^=invoice-line-]:not(#invoice-line-new)");
  const before = await rows().count();
  await page.selectOption("#invoice-line-product-new", product);
  await page.fill("#invoice-line-quantity-new", "3");
  await page.locator("#invoice-line-form-save-new").evaluate((f) => f.requestSubmit());
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
  const last = rows().last();
  const lineId = (await last.getAttribute("id")).replace("invoice-line-", "");
  console.log(`${width}: lines ${before} → ${await rows().count()}; new line says "${await page.inputValue(`#invoice-line-description-${lineId}`)}" × ${await page.inputValue(`#invoice-line-quantity-${lineId}`)} @ ${await page.inputValue(`#invoice-line-price-${lineId}`)}; SKU badge "${(await page.locator(`#invoice-line-product-${lineId}`).textContent().catch(() => "MISSING")).trim()}"`);
  await page.fill(`#invoice-line-quantity-${lineId}`, "5");
  await page.locator(`#invoice-line-form-save-${lineId}`).evaluate((f) => f.requestSubmit());
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
  const shown = await page.inputValue(`#invoice-line-quantity-${lineId}`);
  await page.reload({ waitUntil: "networkidle" });
  console.log(`${width}: after editing the quantity → shown ${shown}, after reload ${await page.inputValue(`#invoice-line-quantity-${lineId}`)}; badge still "${(await page.locator(`#invoice-line-product-${lineId}`).textContent().catch(() => "MISSING")).trim()}"; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
