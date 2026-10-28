// The PUBLIC signing page, as a signer with NO session cookie: open the private link, draw on the
// canvas, type the name, tick consent, sign — then confirm the same link no longer signs. Also:
// a wrong link says one plain sentence, and nothing of the workspace (sidebar, command bar) is there.
// Usage: node scripts/probe-sign.mjs <width> <link-or-token>
import { chromium } from "playwright";
const [widthArg, link] = process.argv.slice(2);
const width = Number(widthArg);
const token = link.replace(/\/$/, "").split("/").pop();
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width, height: 800 }, hasTouch: width < 500 });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));

await page.goto(`http://127.0.0.1:3000/sign/${"0".repeat(64)}`, { waitUntil: "networkidle" });
console.log(`${width}: wrong link -> "${(await page.locator("#sign-refused").textContent()).trim()}" (url kept: ${page.url().includes("/sign/")})`);

await page.goto(`http://127.0.0.1:3000/sign/${token}`, { waitUntil: "networkidle" });
console.log(`${width}: page -> "${(await page.locator("h1").first().textContent()).trim()}" | workspace chrome present: ${await page.locator(".nxl-navigation, #command-bar, .nxl-header").count()} | document shown: ${await page.locator("#sign-document-body, #sign-document-download").count()}`);
const download = page.locator("#sign-document-download");
if (await download.count()) {
  const res = await page.request.get(`http://127.0.0.1:3000${await download.getAttribute("href")}`);
  console.log(`${width}: document -> ${res.status()} ${res.headers()["content-type"]} | ${res.headers()["content-disposition"]}`);
}
await page.click("#sign-submit");      // nothing typed beyond the prefill, consent unticked: the browser's own required check holds the form
console.log(`${width}: unticked consent -> still on the form: ${await page.locator("#sign-form").count() === 1}`);

const pad = page.locator("#sign-pad-canvas");
await pad.scrollIntoViewIfNeeded();
const box = await pad.boundingBox();
await page.mouse.move(box.x + 20, box.y + 90);
await page.mouse.down();
for (let i = 1; i <= 12; i++) await page.mouse.move(box.x + 20 + i * ((box.width - 40) / 12), box.y + 80 + (i % 2 ? -35 : 30), { steps: 3 });
await page.mouse.up();
const drawn = await page.locator('input[name="drawn"]').inputValue();
console.log(`${width}: drew -> ${drawn.startsWith("data:image/png;base64,") ? `PNG data URL, ${Math.round(drawn.length / 1024)} KB` : "NOTHING"}`);
await page.fill("#sign-field-name", `SMOKE Probe Signer ${width}`);
await page.check("#sign-field-consent");
await page.click("#sign-submit");
await page.waitForSelector("#sign-done, #sign-errors", { timeout: 90000 });
  console.log(`${width}: landed on -> ${page.url().replace(/[a-f0-9]{64}/, "<token>")}`);
console.log(`${width}: sign -> "${(await page.locator("#sign-done, #sign-errors").first().textContent()).trim().slice(0, 150)}"`);

await page.goto(`http://127.0.0.1:3000/sign/${token}`, { waitUntil: "networkidle" });
console.log(`${width}: same link again -> "${(await page.locator("#sign-refused").textContent()).trim()}"`);
console.log(`${width}: overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; session cookie set for the signer: ${(await ctx.cookies()).map((c) => c.name).join(",") || "none"}; page errors: ${errors.length}`);
await browser.close();
