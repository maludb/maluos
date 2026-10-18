// Screenshot a signed-in page. Usage: node scripts/shot.mjs <session-id> <path> <out.png> [width] [height] [scrollBottom]
import { chromium } from "playwright";
const [sid, path, out, w = "1280", h = "720", bottom = ""] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: +w, height: +h } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:3000${path}`, { waitUntil: "networkidle" });
await page.mouse.move(+w - 40, 300);
if (bottom) await page.evaluate(() => window.scrollTo({ top: 99999, behavior: "instant" }));
await page.waitForTimeout(400);
await page.screenshot({ path: out });
await browser.close();
