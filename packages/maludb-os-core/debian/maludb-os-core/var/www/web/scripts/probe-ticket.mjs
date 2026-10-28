// The ticket page's forms, clicked: an internal note, a bad then a good status, resolve, reopen —
// on the smoke ticket whose requester's address is at example.invalid (no reply is sent here).
// Usage: scripts/verify.sh <member> --probe scripts/probe-ticket.mjs <ticket-id>
import { chromium } from "playwright";
const [sid, ticket] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:3000/tickets/${ticket}`, { waitUntil: "networkidle" });
  const submit = async (selector) => { await page.locator(selector).scrollIntoViewIfNeeded(); await page.locator(selector).evaluate((b) => b.closest("form").requestSubmit(b)); await page.waitForLoadState("networkidle"); await page.waitForTimeout(800); };
  const before = await page.locator("[id^=ticket-message-]").count();
  await page.fill("#ticket-note-field", `SMOKE probe note at ${width}px`);
  await submit("#ticket-note-btn");
  console.log(`${width}: note -> thread ${before} → ${await page.locator("[id^=ticket-message-]").count()} messages; field cleared: ${(await page.inputValue("#ticket-note-field")) === ""}`);
  await page.selectOption("#ticket-status-field", "pending");
  await submit("#ticket-status-btn");
  console.log(`${width}: status -> badge "${(await page.locator("#ticket-view-facts-card .badge").first().textContent()).trim()}"`);
  await page.fill("#ticket-resolve-field", "SMOKE probe: rolled the firmware back.");
  await submit("#ticket-resolve-btn");
  console.log(`${width}: resolve -> badge "${(await page.locator("#ticket-view-facts-card .badge").first().textContent()).trim()}"; reopen offered: ${await page.isVisible("#ticket-reopen-btn")}; reply card still shown: ${await page.isVisible("#ticket-view-reply-card")}`);
  await submit("#ticket-reopen-btn");
  console.log(`${width}: reopen -> badge "${(await page.locator("#ticket-view-facts-card .badge").first().textContent()).trim()}"; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
