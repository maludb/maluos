// The content item page, clicked through its whole walk as an admin: send for review → approve →
// put on the calendar → take it off → mark published (an example.invalid link) → record numbers.
// Nothing here posts anywhere. Then, as given, a second member's view of an item they REVIEW.
// Usage: scripts/verify.sh <member> --probe scripts/probe-content.mjs <item-id> [walk|review]
import { chromium } from "playwright";
const [sid, item, mode = "walk"] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: mode === "walk" ? 1280 : 375, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
page.on("dialog", (d) => d.accept());
await page.goto(`http://127.0.0.1:3000/content/${item}`, { waitUntil: "networkidle" });
const submit = async (selector) => { await page.locator(selector).evaluate((b) => b.closest("form").requestSubmit(b)); await page.waitForLoadState("networkidle"); await page.waitForTimeout(900); };
const status = async () => (await page.locator("#content-view-facts-card .badge").first().textContent()).trim();
if (mode === "review") {
  console.log(`review: status "${await status()}"; approve offered: ${await page.locator("#content-approve-btn").count()}; ask-for-changes offered: ${await page.locator("#content-changes-btn").count()}; words editable: ${await page.locator("[id$=-save]").count()}; edit offered: ${await page.locator("#content-view-edit-btn").count()}; overflow at 375: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}`);
} else {
  const vid = (await page.locator("[id^=content-variant-]").first().getAttribute("id")).replace("content-variant-", "");
  console.log(`start: "${await status()}"; schedule offered before approval: ${await page.locator(`#content-variant-${vid}-schedule`).count()}`);
  await submit("#content-submit-btn");
  console.log(`send for review -> "${await status()}"`);
  await submit("#content-approve-btn");
  console.log(`approve -> "${await status()}"; schedule offered: ${await page.locator(`#content-variant-${vid}-schedule`).count()}`);
  const soon = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 11) + "09:30";
  await page.fill(`#content-variant-${vid}-slot`, soon);
  await submit(`#content-variant-${vid}-schedule`);
  console.log(`schedule -> "${await status()}"; words still editable: ${await page.locator(`#content-variant-${vid}-save`).count()}`);
  await submit(`#content-variant-${vid}-unschedule`);
  console.log(`unschedule -> "${await status()}"`);
  await page.fill(`#content-variant-${vid}-url`, "not a link");
  await page.locator(`#content-variant-${vid}-url`).evaluate((el) => el.setAttribute("type", "text"));
  await submit(`#content-variant-${vid}-published`);
  console.log(`bad link -> "${((await page.locator(`#content-variant-${vid}-plan .alert`).first().textContent().catch(() => "")) ?? "").trim().slice(0, 90)}"; still "${await status()}"`);
  await page.fill(`#content-variant-${vid}-url`, `https://example.invalid/posts/probe-${item}`);
  await submit(`#content-variant-${vid}-published`);
  console.log(`mark published -> "${await status()}"; plan forms gone: ${(await page.locator(`#content-variant-${vid}-plan`).count()) === 0}`);
  await page.fill(`#content-variant-${vid}-metrics-form input[name=impressions]`, "310");
  await page.fill(`#content-variant-${vid}-metrics-form input[name=clicks]`, "14");
  await submit(`#content-variant-${vid}-metrics-save`);
  console.log(`numbers -> "${(await page.locator(`#content-variant-${vid}-metrics`).textContent()).replace(/\s+/g, " ").trim().slice(0, 90)}"`);
}
console.log(`page errors: ${errors.length}`);
await browser.close();
