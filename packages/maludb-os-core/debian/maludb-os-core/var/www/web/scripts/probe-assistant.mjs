// The command bar in a real browser, using ONLY the path that writes nothing and calls no model:
// an empty message, which assistant/message.php answers with its hint before it logs anything.
// Usage: node scripts/probe-assistant.mjs <session-id> [shot-dir]
import { chromium } from "playwright";
const [sid, shots] = process.argv.slice(2);
const browser = await chromium.launch();
for (const viewport of [{ width: 1280, height: 800 }, { width: 375, height: 667 }]) {
  const ctx = await browser.newContext({ viewport });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
  await page.goto("http://127.0.0.1:3000/deals", { waitUntil: "networkidle" });
  await page.keyboard.press("Control+k");
  const focused = await page.evaluate(() => document.activeElement?.id);
  await page.click("#assistant-send-btn");
  await page.waitForSelector("#assistant-reply .assistant-reply-bubble", { timeout: 15000 });
  const text = (await page.textContent("#assistant-reply")).trim();
  const box = await page.locator("#assistant-bar").boundingBox();
  const hScroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  console.log(`${viewport.width}: Ctrl+K focuses "${focused}"; empty message -> "${text.slice(0, 70)}…"; bar at y=${Math.round(box.y)} h=${Math.round(box.height)} of ${viewport.height}; hScroll=${hScroll}; errors=${errors.length}`);
  if (shots) await page.screenshot({ path: `${shots}/assistant-${viewport.width}.png` });
  await ctx.close();
}
await browser.close();
