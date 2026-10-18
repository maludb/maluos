// Diagnostic: can a shell page scroll? Usage: node scripts/probe-scroll.mjs <session-id> <path>
import { chromium } from "playwright";
const [sid, path = "/contacts", base = "http://127.0.0.1:3000"] = process.argv.slice(2);
const browser = await chromium.launch();
for (const viewport of [{ width: 1280, height: 720 }, { width: 375, height: 667 }]) {
  const ctx = await browser.newContext({ viewport });
  await ctx.addCookies([
    { name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" },
    { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }, // a probe is not a screen view
  ]);
  const page = await ctx.newPage();
  await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
  const report = await page.evaluate(() => {
    const cs = (el) => { const s = getComputedStyle(el); return `${s.overflowX}/${s.overflowY} h=${s.height} pos=${s.position}`; };
    const chain = [];
    for (let el = document.querySelector("#page-content"); el; el = el.parentElement) chain.push(`${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${[...el.classList].join(".")} → ${cs(el)}`);
    return { docScrollHeight: document.documentElement.scrollHeight, innerHeight: window.innerHeight, scrolledTo: window.scrollY, chain,
             htmlClass: document.documentElement.className, bodyStyle: document.body.getAttribute("style") };
  });
  await page.mouse.move(viewport.width - 200 > 300 ? viewport.width - 200 : 180, 400);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(1200);
  const afterWheel = await page.evaluate(() => window.scrollY);
  await page.evaluate(() => window.scrollTo({ top: 99999, behavior: "instant" }));
  const afterJump = await page.evaluate(() => window.scrollY);
  const under = await page.evaluate(([x, y]) => { const e = document.elementFromPoint(x, y); return e ? `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].join(".")}` : null; }, [viewport.width - 200 > 300 ? viewport.width - 200 : 180, 400]);
  const noteField = await page.evaluate(() => { const el = document.querySelector("[id^='comment-field-']"); if (!el) return null; el.scrollIntoView({ behavior: "instant", block: "center" }); const r = el.getBoundingClientRect(); return { top: Math.round(r.top), inViewport: r.top >= 0 && r.bottom <= window.innerHeight }; });
  console.log(JSON.stringify({ viewport, docScrollHeight: report.docScrollHeight, innerHeight: report.innerHeight, afterWheel, afterJump, under, noteField }));
  await page.screenshot({ path: `/tmp/claude-1000/-var-www/d0f1948b-0e62-44e7-8f18-0432fc247ce5/scratchpad/probe-${viewport.width}.png` });
  await ctx.close();
}
await browser.close();
