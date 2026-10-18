// AI Ops, clicked: open a real ledger call (the prompt is TEXT, never markup), write an eval set and a case through the forms,
// press Run and read the honest refusal; then confirm nothing pretended to run. Usage: scripts/verify.sh 1 --probe scripts/probe-aiops.mjs <ledger-id>
import { chromium } from "playwright";
const [sid, ledger] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("dialog", (d) => d.accept());
  const go = (p) => page.goto(`http://127.0.0.1:3000${p}`, { waitUntil: "networkidle" });
  await go(`/ai/prompt-log/${ledger}`);
  const ctxText = await page.locator("#prompt-call-context").textContent();
  console.log(`${width}: call #${ledger} -> prompt shown as text (${ctxText.length} chars, starts ${JSON.stringify(ctxText.slice(0, 24))}); child elements inside the <pre>: ${await page.locator("#prompt-call-context *").count()}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}`);
  const name = `SMOKE probe ${width} ${Date.now() % 100000}`;
  await go("/ai/evals/new?role=probe-role");
  await page.fill("#eval-set-form-field-name", name);
  await page.locator("#eval-set-form").evaluate((f) => f.requestSubmit());
  await page.waitForURL(/\/ai\/evals\/\d+$/, { timeout: 20000 });
  const setUrl = new URL(page.url()).pathname;
  await page.waitForLoadState("networkidle");
  await page.locator("#eval-set-run-btn").evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForSelector("#eval-set-facts-card .alert", { timeout: 15000 });
  console.log(`${width}: run with no cases -> "${(await page.locator("#eval-set-facts-card .alert").first().textContent()).trim()}"`);
  await go(`${setUrl}/cases/new`);
  await page.fill("#eval-case-form-field-title", "SMOKE probe case");
  await page.fill("#eval-case-form-field-input", "Categorise: Shell 48.20 USD fuel");
  await page.fill("#eval-case-form-field-rubric", "Names a vehicle or fuel category");
  await page.locator("#eval-case-form").evaluate((f) => f.requestSubmit());
  await page.waitForURL(new RegExp(`${setUrl}$`), { timeout: 20000 });
  await page.waitForLoadState("networkidle");
  console.log(`${width}: case saved -> ${await page.locator("[id^=eval-case-]:not([id*=form])").count()} case(s) on ${setUrl}`);
  await page.locator("#eval-set-run-btn").evaluate((b) => b.closest("form").requestSubmit(b));
  await page.waitForSelector("#eval-set-facts-card .alert", { timeout: 15000 });
  await page.waitForTimeout(500);
  console.log(`${width}: run -> "${(await page.locator("#eval-set-facts-card .alert").first().textContent()).trim()}"; runs card: "${(await page.locator("#eval-set-runs-card .card-body").textContent()).trim()}"; banner shown: ${await page.isVisible("#evals-no-runner")}; page errors: ${errors.length}`);
  await ctx.close();
}
await browser.close();
