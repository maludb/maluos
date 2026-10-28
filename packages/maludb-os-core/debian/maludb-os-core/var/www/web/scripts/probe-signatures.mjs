// The request page's forms, clicked on a DRAFT: add a signer, send (confirm accepted), remind, void.
// Every signer address is example.invalid. Usage: scripts/verify.sh <member> --probe scripts/probe-signatures.mjs <draft-request-id>
import { chromium } from "playwright";
const [sid, id] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 375, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
page.on("dialog", (d) => d.accept());
await page.goto(`http://127.0.0.1:3000/signatures/${id}`, { waitUntil: "networkidle" });
const submit = async (selector, until) => {
  await page.locator(selector).evaluate((b) => b.closest("form").requestSubmit(b));
  if (until) await page.waitForFunction(until, null, { timeout: 60000 }).catch(() => {});   // a send mails each signer first
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(800);
};
const badge = async () => (await page.locator("#signature-facts-card .badge").first().textContent()).trim();
const before = await page.locator("#signature-signers-card .border.rounded").count();
await page.fill('#signature-signer-add-form input[name="name"]', "SMOKE Probe Added");
await page.fill('#signature-signer-add-form input[name="email"]', `probe-added-${Date.now()}@example.invalid`);
await submit("#signature-signer-add-btn");
console.log(`add signer -> ${before} → ${await page.locator("#signature-signers-card .border.rounded").count()} signers; status "${await badge()}"`);
await submit("#signature-send-btn", () => !document.querySelector("#signature-send-btn"));
console.log(`send -> status "${await badge()}"; add-signer form gone: ${await page.locator("#signature-signer-add-form").count() === 0}; trail rows: ${await page.locator("#signature-trail-table tbody tr").count()}`);
const rows = await page.locator("#signature-trail-table tbody tr").count();
await submit("#signature-remind-btn", () => document.querySelectorAll("#signature-trail-table tbody tr").length > 3);
console.log(`remind -> trail rows: ${await page.locator("#signature-trail-table tbody tr").count()}`);
await submit("#signature-void-btn");
console.log(`void with no reason -> status "${await badge()}" (the browser's required check holds it)`);
await page.fill("#signature-void-field", "SMOKE probe: voided by the click probe");
await submit("#signature-void-btn");
console.log(`void -> status "${await badge()}"; void card gone: ${await page.locator("#signature-void-card").count() === 0}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
await browser.close();
