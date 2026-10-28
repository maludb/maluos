// The conversation page, clicked as its ASSIGNEE (no Inbox grant): status there and back, a reply
// (to the fixture's example.invalid sender — the confirm dialog is accepted), and the attachment
// download through /api/download. Usage: scripts/verify.sh <member> --probe scripts/probe-inbox.mjs <thread-id>
import { chromium } from "playwright";
const [sid, thread] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:3000/inbox/threads/${thread}`, { waitUntil: "networkidle" });
  const submit = async (selector) => { await page.locator(selector).evaluate((b) => b.closest("form").requestSubmit(b)); await page.waitForLoadState("networkidle"); await page.waitForTimeout(900); };
  console.log(`${width}: assign offered: ${await page.locator("#mail-thread-assign-btn").count()}; ticket offered: ${await page.locator("#mail-thread-ticket-btn").count()}; draft offered: ${await page.locator("#mail-draft-btn").count()}; reply offered: ${await page.locator("#mail-reply-btn").count()}`);
  await page.selectOption("#mail-thread-status-field", "pending"); await submit("#mail-thread-status-btn");
  const waiting = (await page.locator("#mail-thread-facts-card .badge").first().textContent()).trim();
  await page.selectOption("#mail-thread-status-field", "open"); await submit("#mail-thread-status-btn");
  console.log(`${width}: status -> "${waiting}" -> "${(await page.locator("#mail-thread-facts-card .badge").first().textContent()).trim()}"`);
  if (width === 1280) {
    const before = await page.locator("[id^=mail-message-]:not([id$=attachments])").count();
    await page.fill("#mail-reply-field", "SMOKE probe reply from the assignee.");
    await submit("#mail-reply-btn");
    // MaluMail suppresses an address once it has bounced, so a second reply to the fixture's sender is REFUSED by the
    // mail service — which is the other half worth seeing: the refusal is shown, the text is kept, nothing is recorded.
    const said = await page.locator("#mail-reply-box .alert").first().textContent().catch(() => "");
    console.log(`${width}: reply -> ${before} → ${await page.locator("[id^=mail-message-]:not([id$=attachments])").count()} messages; box cleared: ${(await page.inputValue("#mail-reply-field")) === ""}; said: "${(said ?? "").trim().slice(0, 140)}"`);
  }
  const href = await page.locator('a[href^="/api/download"]').first().getAttribute("href");
  const res = await page.request.get(`http://127.0.0.1:3000${href}`);
  console.log(`${width}: attachment -> ${res.status()} ${res.headers()["content-type"]} | ${res.headers()["content-disposition"]} | nosniff=${res.headers()["x-content-type-options"]}`);
  console.log(`${width}: overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
