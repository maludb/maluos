import { chromium } from "playwright";
const [sid, path] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:3000${path}`, { waitUntil: "networkidle" });
console.log(await page.evaluate(() => {
  const out = [];
  const walk = (el, depth) => {
    if (depth > 4) return;
    const s = getComputedStyle(el);
    out.push(`${"  ".repeat(depth)}${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${[...el.classList].slice(0, 4).join(".")}  client=${el.clientHeight} scroll=${el.scrollHeight} display=${s.display} wrap=${s.flexWrap}`);
    [...el.children].forEach((c) => walk(c, depth + 1));
  };
  walk(document.querySelector(".main-content"), 0);
  return out.join("\n");
}));
await browser.close();
