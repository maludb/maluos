// Leave, clicked end to end by two people. Usage:
//   scripts/verify.sh 6 --probe scripts/probe-people.mjs request     Sam asks for a day off through the form
//   scripts/verify.sh 1 --probe scripts/probe-people.mjs approve     the owner approves it on the list; then Sam's balance is read
//   scripts/verify.sh 1 --probe scripts/probe-people.mjs cancel      …and cancels it again, so the probe leaves the balance as it found it
import { chromium } from "playwright";
const [sid, mode] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: mode === "request" ? 375 : 1280, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
page.on("dialog", (d) => d.accept());
const base = "http://127.0.0.1:3000";
const balance = async () => { await page.goto(`${base}/people/6?tab=leave`, { waitUntil: "networkidle" }); return (await page.locator("#leave-balance-1 .fs-3").textContent()).replace(/\s+/g, " ").trim(); };

if (mode === "request") {
  await page.goto(`${base}/people/leave/new`, { waitUntil: "networkidle" });
  console.log(`375: form says: "${(await page.locator("#leave-form-balance").textContent()).trim()}"`);
  await page.selectOption("#leave-form-field-type", "1");
  await page.fill("#leave-form-field-start", "2026-11-16");
  await page.locator("#leave-form-save").evaluate((b) => document.getElementById("leave-form").requestSubmit());
  await page.waitForURL(/\/people\/leave$/, { timeout: 20000 });
  await page.waitForLoadState("networkidle");
  const row = page.locator("#leave-requests-table tbody tr", { hasText: "2026-11-16" }).first();
  console.log(`375: landed on ${new URL(page.url()).pathname}; row: "${(await row.textContent()).replace(/\s+/g, " ").trim().slice(0, 90)}"; approve offered to Sam: ${await row.locator("[id^=leave-approve-]").count()}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}`);
} else {
  console.log(`1280: Sam's paid time off before: ${await balance()}`);
  await page.goto(`${base}/people/leave?status=${mode === "approve" ? "requested" : "approved"}`, { waitUntil: "networkidle" });
  const row = page.locator("#leave-requests-table tbody tr", { hasText: "2026-11-16" }).first();
  const button = row.locator(mode === "approve" ? "[id^=leave-approve-]" : "[id^=leave-cancel-]");
  await button.evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
  console.log(`1280: ${mode}d; Sam's paid time off after: ${await balance()}`);
  if (mode === "approve") {
    await page.goto(`${base}/people/leave/calendar?from=2026-11-16&weeks=1`, { waitUntil: "networkidle" });
    console.log(`1280: who is off, week of 2026-11-16: "${(await page.locator("#leave-week-2026-11-16 .card-body").textContent()).replace(/\s+/g, " ").trim().slice(0, 110)}"`);
  }
}
console.log(`page errors: ${errors.length}`);
await browser.close();
