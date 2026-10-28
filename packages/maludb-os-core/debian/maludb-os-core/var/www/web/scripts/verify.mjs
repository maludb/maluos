// Mechanical conformance for converted screens, in a real browser, at 1280 and 375.
// Usage: node scripts/verify.mjs <session-id> [--shots <dir>] <path>...
// Sends the quiet cookie, so a check is never logged as a screen view.
import { chromium } from "playwright";
const args = process.argv.slice(2);
const sid = args.shift();
let shots = null;
if (args[0] === "--shots") { args.shift(); shots = args.shift(); }
const browser = await chromium.launch();
let failed = 0;
for (const path of args) {
  for (const viewport of [{ width: 1280, height: 800 }, { width: 375, height: 667 }]) {
    const ctx = await browser.newContext({ viewport });
    await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
    const res = await page.goto(`http://127.0.0.1:3000${path}`, { waitUntil: "networkidle" });
    await page.mouse.move(viewport.width - 30, 300);
    await page.waitForTimeout(350);   // let the sidebar's hover transition finish before measuring
    const r = await page.evaluate(() => {
      const main = document.querySelector(".main-content");
      return {
        title: document.querySelector(".page-header-title h5")?.textContent ?? null,
        refused: document.querySelector("#screen-refused")?.textContent?.slice(0, 120) ?? null,
        notConverted: !!document.querySelector("#not-converted-card"),
        hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
        innerScroll: main ? main.scrollHeight > main.clientHeight + 2 : false,   // the stacked-card defect
        hx: document.querySelectorAll("[hx-get],[hx-post]").length,
      };
    });
    const bad = res.status() >= 400 || r.refused || r.notConverted || r.hScroll || r.innerScroll || r.hx || errors.length;
    if (bad) failed++;
    console.log(`${bad ? "FAIL" : "ok  "} ${String(viewport.width).padStart(4)} ${path} [${res.status()}] "${r.title}"` +
      (r.refused ? ` refused=${r.refused}` : "") + (r.notConverted ? " NOT-CONVERTED" : "") + (r.hScroll ? " H-SCROLL" : "") +
      (r.innerScroll ? " INNER-SCROLL" : "") + (errors.length ? ` errors=${JSON.stringify(errors.slice(0, 2))}` : ""));
    if (shots) await page.screenshot({ path: `${shots}/${path.replace(/[^a-z0-9]+/gi, "_")}-${viewport.width}.png`, fullPage: true });
    await ctx.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
