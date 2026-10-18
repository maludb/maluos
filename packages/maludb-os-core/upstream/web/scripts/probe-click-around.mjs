// Click-around, step 0 (docs/build-specs/click-around.md): spend by agent → the agent → a run → back → back.
// Usage: node scripts/probe-click-around.mjs <session-id> [base-url]   (base defaults to http://127.0.0.1:3000)
// Sends the quiet cookie, so nothing here is logged as a screen view.
import { chromium } from "playwright";
const [sid, base = "http://127.0.0.1:3000"] = process.argv.slice(2);
const host = new URL(base).hostname;
const browser = await chromium.launch();
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failed++; };
const rel = (page) => { const u = new URL(page.url()); return u.pathname + u.search; };

for (const viewport of [{ width: 1280, height: 800 }, { width: 375, height: 667 }]) {
  console.log(`--- ${viewport.width}px`);
  const ctx = await browser.newContext({ viewport });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: host, path: "/" }, { name: "bos_quiet", value: "1", domain: host, path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
  // The sidebar expands under the pointer and would sit over what we click: park the mouse off it.
  const park = async () => { await page.mouse.move(viewport.width - 30, 300); await page.waitForTimeout(350); };
  const noScroll = async (what) => check(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), `${what}: no horizontal scroll`);

  const spend = "/ai/spend?group_by=agent&period=all";
  await page.goto(base + spend, { waitUntil: "networkidle" }); await park();
  const rows = page.locator('a[id^="ai-spend-row-"]');
  check((await rows.count()) > 0, `spend rows are links (${await rows.count()})`);
  const first = rows.first();
  const href = await first.getAttribute("href");
  check(/^\/(agents|team)\/\d+\?back=%2Fai%2Fspend/.test(href ?? ""), `row href carries back: ${href}`);
  check((await page.locator("#ai-spend-header .breadcrumb a", { hasText: "AI Ops" }).count()) === 1, "AI Ops crumb is a link");

  await first.click(); await page.waitForURL(/\/(agents|team)\/\d+\?/); await page.waitForLoadState("networkidle");
  const agentUrl = rel(page);
  check(/^\/agents\/\d+\?back=/.test(agentUrl), `landed on the agent: ${agentUrl}`);
  const back = page.locator("#agent-view-back");
  check((await back.textContent())?.trim() === "Back to AI spend", `agent header says "${(await back.textContent())?.trim()}"`);
  check((await back.getAttribute("data-back")) === "carried", "back is the carried one");
  await noScroll("agent page");

  await park();
  await page.locator("#agent-view-tab-performance").click(); await page.waitForURL(/tab=performance/); await page.waitForLoadState("networkidle");
  check(/tab=performance/.test(rel(page)) && /back=/.test(rel(page)), `tab keeps back: ${rel(page)}`);
  const perfUrl = rel(page);

  const run = page.locator('#agent-performance-runs a[href^="/ai/runs/"]').first();
  if ((await run.count()) === 0) { console.log("skip  no run on this agent's Performance tab"); }
  else {
    const runHref = await run.getAttribute("href");
    check(/back=%2Fagents%2F\d+%3Ftab%3Dperformance%26back%3D/.test(runHref ?? ""), `run link chains back: ${runHref?.slice(0, 90)}…`);
    await park();
    await run.click(); await page.waitForURL(/\/ai\/runs\/\d+/); await page.waitForLoadState("networkidle");
    check(/^\/ai\/runs\/\d+\?back=/.test(rel(page)), `landed on the run: ${rel(page).slice(0, 60)}…`);
    const rb = page.locator("#agent-run-back");
    check((await rb.textContent())?.trim() === "Back to the agent", `run header says "${(await rb.textContent())?.trim()}"`);
    await noScroll("run page");
    await park();
    await rb.click(); await page.waitForURL(/\/agents\/\d+\?tab=performance/); await page.waitForLoadState("networkidle");
    check(rel(page) === perfUrl, `back returns to the agent's Performance tab with its back: ${rel(page) === perfUrl}`);
  }
  await park();
  await page.locator("#agent-view-back").click(); await page.waitForURL(/\/ai\/spend/); await page.waitForLoadState("networkidle");
  check(rel(page) === spend, `back returns to spend with period and grouping: ${rel(page)}`);

  // Step 5: Edit opened from the agent's Performance tab carries the page; Cancel returns to it, trail intact.
  await page.goto(base + perfUrl, { waitUntil: "networkidle" }); await park();
  const edit = page.locator("#agent-view-edit-btn");
  if ((await edit.count()) === 0) { console.log("skip  no Edit button for this viewer"); }
  else {
    check(/\/agents\/\d+\/edit\?back=%2Fagents%2F\d+%3Ftab%3Dperformance/.test((await edit.getAttribute("href")) ?? ""), `Edit carries the tab page: ${(await edit.getAttribute("href"))?.slice(0, 70)}…`);
    // On a phone the header's actions sit behind the open toggle (PageHeader): open it first.
    if (!(await edit.isVisible())) { await page.locator(".page-header-right-open-toggle").click(); await page.waitForTimeout(300); }
    await edit.click(); await page.waitForURL(/\/agents\/\d+\/edit/); await page.waitForLoadState("networkidle"); await park();
    check((await page.locator("#agent-form-back").textContent())?.trim() === "Back to the agent", `edit form header says "${(await page.locator("#agent-form-back").textContent())?.trim()}"`);
    if (!(await page.locator("#agent-form-cancel").isVisible())) { await page.locator(".page-header-right-open-toggle").click(); await page.waitForTimeout(300); }
    await page.locator("#agent-form-cancel").click(); await page.waitForURL(/\/agents\/\d+\?tab=performance/); await page.waitForLoadState("networkidle");
    check(rel(page) === perfUrl, `Cancel returns to the Performance tab with its back: ${rel(page) === perfUrl}`);
  }

  // The Skills tab (2026-09-27): the resolved set with its delivery, reachable from the tab strip and by URL.
  await page.goto(base + agentUrl, { waitUntil: "networkidle" }); await park();
  await page.locator("#agent-view-tab-skills").click(); await page.waitForURL(/tab=skills/); await page.waitForLoadState("networkidle");
  check(/tab=skills/.test(rel(page)) && /back=/.test(rel(page)), `Skills tab keeps back: ${rel(page).slice(0, 60)}…`);
  check((await page.locator("#agent-skills-table tbody tr").count()) > 0, `skills rows: ${await page.locator("#agent-skills-table tbody tr").count()}`);
  check((await page.locator("#agent-skills-rule").count()) === 1, "the delivery rule is stated");

  // No back carried → the structural parent; a foreign back → ignored, the parent again.
  const agentPath = agentUrl.split("?")[0];
  await page.goto(base + agentPath, { waitUntil: "networkidle" });
  check((await page.locator("#agent-view-back").textContent())?.trim() === "Back to Agents", "bare agent URL: Back to Agents");
  check((await page.locator("#agent-view-back").getAttribute("data-back")) === "parent", "bare agent URL: parent back");
  await page.goto(`${base}${agentPath}?back=${encodeURIComponent("https://evil.example/x")}`, { waitUntil: "networkidle" });
  check((await page.locator("#agent-view-back").getAttribute("href")) === "/agents", "foreign back ignored → /agents");
  await page.goto(`${base}${agentPath}?back=${encodeURIComponent("//evil.example/x")}`, { waitUntil: "networkidle" });
  check((await page.locator("#agent-view-back").getAttribute("href")) === "/agents", "protocol-relative back ignored → /agents");

  // /ai is the AI Ops front page (owner, 2026-09-27), with a card a section that opens it.
  await page.goto(`${base}/ai`, { waitUntil: "networkidle" });
  check(rel(page) === "/ai" && (await page.locator("#ai-ops-spend-open").count()) === 1, `/ai is the index with its Spend card: ${rel(page)}`);

  check(errors.length === 0, `no console errors${errors.length ? ` ${JSON.stringify(errors.slice(0, 2))}` : ""}`);
  await ctx.close();
}
await browser.close();
console.log(failed ? `${failed} FAILED` : "all ok");
process.exit(failed ? 1 : 0);
