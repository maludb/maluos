import { chromium } from "playwright";
const [sid, path] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
page.on("console", (m) => console.log("  console:", m.text().slice(0, 200)));
page.on("pageerror", (e) => console.log("  pageerror:", String(e).slice(0, 300)));
await page.goto(`http://127.0.0.1:3000${path}`, { waitUntil: "networkidle" });
await page.evaluate(() => {
  window.__w = [];
  window.addEventListener("wheel", (e) => setTimeout(() => window.__w.push({ target: e.target.tagName + "." + e.target.className, prevented: e.defaultPrevented }), 0), { capture: true, passive: true });
});
for (const [x, y] of [[1000, 400], [700, 650]]) {
  await page.mouse.move(x, y);
  await page.mouse.wheel(0, 500);
  await page.waitForTimeout(1000);
  const r = await page.evaluate(() => ({ y: window.scrollY, events: window.__w.splice(0), scrolled: [...document.querySelectorAll("*")].filter((e) => e.scrollTop > 0).map((e) => e.tagName + "#" + e.id + "." + e.className + "=" + e.scrollTop) }));
  console.log(JSON.stringify({ at: [x, y], ...r }));
}
console.log(await page.evaluate(() => ({ scrollingElement: document.scrollingElement?.tagName, compat: document.compatMode,
  htmlOverflow: getComputedStyle(document.documentElement).overflow, bodyOverflow: getComputedStyle(document.body).overflow,
  overlay: [...document.querySelectorAll("body *")].filter((e) => { const s = getComputedStyle(e); const r = e.getBoundingClientRect(); return s.position === "fixed" && r.width >= 1000 && r.height >= 600; }).map((e) => e.tagName + "#" + e.id + "." + e.className) })));
await browser.close();
