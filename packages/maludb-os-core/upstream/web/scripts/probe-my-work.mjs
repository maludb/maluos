// What My Work shows a member: the header sentence, each section with its count and first item, overflow at both
// widths, and that an item's link opens a real page. Usage: scripts/verify.sh <member> --probe scripts/probe-my-work.mjs
import { chromium } from "playwright";
const [sid] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await page.goto("http://127.0.0.1:3000/my-work", { waitUntil: "networkidle" });
  const sections = await page.locator("[data-section]").evaluateAll((cards) => cards.map((c) => `${c.dataset.section}=${c.querySelector(".badge")?.textContent} (${c.querySelectorAll("li").length} shown)`));
  console.log(`${width}: "${(await page.locator("#my-work-count").textContent()).trim()}" | ${sections.join("; ") || "no sections"} | empty cards: ${await page.locator("[data-section]:not(:has(li))").count()} | overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)} | errors: ${errors.length}`);
  if (width === 1280 && sections.length > 0) {
    const href = await page.locator("[data-section] li a").first().getAttribute("href");
    await page.goto(`http://127.0.0.1:3000${href}`, { waitUntil: "networkidle" });
    console.log(`${width}: first item ${href} -> ${page.url().replace("http://127.0.0.1:3000", "")} "${(await page.title()).slice(0, 60)}" refused: ${await page.locator("text=You do not have access").count()}`);
  }
  await ctx.close();
}
await browser.close();
