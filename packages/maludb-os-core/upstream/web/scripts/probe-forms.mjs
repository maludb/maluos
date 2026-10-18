// The form builder, clicked: add a field, move it up, remove it; the redirect field refuses an http:// address.
// Usage: scripts/verify.sh <member> --probe scripts/probe-forms.mjs <form-id>
import { chromium } from "playwright";
const [sid, form] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  const submit = async (selector) => { await page.locator(selector).evaluate((b) => b.closest("form").requestSubmit(b)); await page.waitForLoadState("networkidle"); await page.waitForTimeout(900); };
  await page.goto(`http://127.0.0.1:3000/forms/${form}/fields`, { waitUntil: "networkidle" });
  const before = await page.locator("[id^=form-field-]:not([id*=-up]):not([id*=-down]):not([id*=-remove]).border").count();
  await page.selectOption("#form-field-kind", "select");
  await page.fill("#form-field-label", `SMOKE probe choice ${width}`);
  await page.fill("#form-field-options", "One\nTwo\nThree");
  await submit("#form-field-add-btn");
  const rows = page.locator("#form-fields-card .border.rounded");
  const count = await rows.count();
  const lastId = (await rows.last().getAttribute("id")).replace("form-field-", "");
  await submit(`#form-field-${lastId}-up`);
  const position = await rows.evaluateAll((els, id) => els.findIndex((e) => e.id === `form-field-${id}`) + 1, lastId);
  await submit(`#form-field-${lastId}-remove`);
  console.log(`${width}: fields ${before} -> ${count} after add; moved up to place ${position} of ${count}; after remove: ${await rows.count()}`);
  await page.goto(`http://127.0.0.1:3000/forms/${form}/edit`, { waitUntil: "networkidle" });
  await page.fill("#form-form-field-redirect", "http://evil.example.invalid/");
  await page.locator("#form-form").evaluate((f) => f.requestSubmit());      // the Save button sits behind the header toggle at 375
  await page.waitForSelector("#form-form-errors .alert, #form-form-errors", { timeout: 15000 });
  console.log(`${width}: http:// redirect -> "${(await page.locator("#form-form-errors").innerText()).replace(/\s+/g, " ").slice(0, 110)}"; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
