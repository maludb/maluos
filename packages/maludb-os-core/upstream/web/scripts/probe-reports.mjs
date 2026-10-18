// Reports, clicked: build a report from the form (tool → its parameters → bar chart), land on its page, see the
// chart canvas AND the table, download the CSV through /api/download, put it on a dashboard and see the tile draw.
// Everything it makes is named SMOKE. Usage: scripts/verify.sh <member> --probe scripts/probe-reports.mjs
import { chromium } from "playwright";
const [sid] = process.argv.slice(2);
const stamp = new Date().toISOString().slice(5, 19).replace(/[-:T]/g, "");
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  const base = "http://127.0.0.1:3000";
  await page.goto(`${base}/reports/new`, { waitUntil: "networkidle" });
  console.log(`${width}: new report -> ${await page.locator("#report-form-field-tool option").count() - 1} tools offered; save disabled until one is chosen: ${await page.locator("#report-form-save").isDisabled()}`);
  await page.selectOption("#report-form-field-tool", "time_summary");
  await page.waitForSelector("#report-form-p-group_by", { timeout: 20000 });
  const name = `SMOKE probe ${stamp} ${width} hours by project`;
  await page.fill("#report-form-field-name", name);
  await page.selectOption("#report-form-field-category", "work");
  await page.fill("#report-form-p-period", "last_12_months");
  await page.locator("#report-form-ask-period").evaluate((el) => el.click());   // the fixed header can cover a real click
  await page.selectOption("#report-form-field-visualization", "bar");
  await page.fill("#report-form-field-label", "label");
  await page.fill("#report-form-field-values", "hours, billable_hours");
  await page.locator("#report-form").evaluate((f) => f.requestSubmit());
  await page.waitForURL(/\/reports\/\d+$/, { timeout: 30000 });
  await page.waitForLoadState("networkidle");
  const id = page.url().split("/").pop();
  const canvas = await page.locator("#report-view-result-card canvas").count();
  const rows = await page.locator("#report-view-table tbody tr").count();
  const box = canvas ? await page.locator("#report-view-result-card canvas").first().boundingBox() : null;
  console.log(`${width}: saved -> /reports/${id}; chart canvases: ${canvas} (${box ? Math.round(box.width) + "×" + Math.round(box.height) : "-"}); table rows beneath: ${rows}; asks for: ${await page.locator("#report-view-ask-form select, #report-view-ask-form input").count()} parameter(s)`);
  await page.fill("#report-view-p-period", "ytd");
  await Promise.all([page.waitForURL(/p_period=ytd/, { timeout: 30000 }), page.locator("#report-view-ask-form").evaluate((f) => f.requestSubmit())]);
  await page.waitForLoadState("networkidle");
  console.log(`${width}: re-run with another period -> URL carries it: ${page.url().includes("p_period=")}; rows: ${await page.locator("#report-view-table tbody tr").count()}; error shown: ${await page.locator("#report-view-error").count()}`);
  const href = await page.locator("#report-view-csv-btn").getAttribute("href");
  const res = await page.request.get(`${base}${href}`);
  const csv = await res.text();
  console.log(`${width}: CSV -> ${res.status()} ${res.headers()["content-type"]} | ${res.headers()["content-disposition"]} | first line: ${csv.replace(/^﻿/, "").split(/\r?\n/)[0]}`);
  await page.goto(`${base}/dashboards`, { waitUntil: "networkidle" });
  await page.fill('#dashboard-add-form input[name="name"]', `SMOKE probe ${stamp} ${width} board`);
  await page.locator("#dashboard-add-btn").evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForURL(/\/dashboards\/\d+\/edit$/, { timeout: 30000 });
  await page.waitForLoadState("networkidle");
  await page.selectOption("#dashboard-tile-field-report", id);
  await page.locator("#dashboard-tile-add-btn").evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForSelector("[id^=dashboard-widget-]", { timeout: 20000 });
  await page.selectOption("#dashboard-tile-field-kind", "text");
  await page.fill("#dashboard-tile-field-text", "SMOKE probe note");
  await page.fill("#dashboard-tile-field-title", "SMOKE note");
  await page.locator("#dashboard-tile-add-btn").evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForFunction(() => document.querySelectorAll("[id^=dashboard-widget-]").length >= 2, null, { timeout: 20000 });
  const before = await page.locator("[id^=dashboard-widget-] .fw-semibold").allTextContents();
  await page.locator('[id^=dashboard-widget-][id$="-up"]').nth(1).evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForTimeout(1500); await page.waitForLoadState("networkidle");
  const after = await page.locator("[id^=dashboard-widget-] .fw-semibold").allTextContents();
  await page.locator("#dashboard-edit-done").evaluate((el) => el.click());
  await page.waitForURL(/\/dashboards\/\d+$/, { timeout: 20000 }); await page.waitForLoadState("networkidle");
  console.log(`${width}: dashboard -> tiles ${JSON.stringify(before.map((t) => t.slice(0, 18)))} → after "up" ${JSON.stringify(after.map((t) => t.slice(0, 18)))}; tile canvases: ${await page.locator("[id^=dashboard-tile-] canvas").count()}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
