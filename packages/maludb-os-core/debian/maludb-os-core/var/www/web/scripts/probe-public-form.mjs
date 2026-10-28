// A PUBLIC form with NO session at all: fill, a refusal that keeps what was typed, send, thanked
// (or sent on to the form's own redirect); then the trap path — a machine that fills the hidden
// field is thanked exactly the same. Usage: node scripts/probe-public-form.mjs <slug> [<closed-slug>]
import { chromium } from "playwright";
const [slug, closed] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of [1280, 375]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await page.goto(`http://127.0.0.1:3000/f/${slug}`, { waitUntil: "networkidle" });
  console.log(`${width}: open -> ${new URL(page.url()).pathname} "${await page.locator("h1").innerText()}"; shell: ${await page.locator(".nxl-navigation, .nxl-header, #command-bar").count()}; trap off-screen: ${(await page.locator("#public-form-website").boundingBox()).x < 0} out of tab order: ${(await page.locator("#public-form-website").getAttribute("tabindex")) === "-1"}; fields: ${await page.locator("#public-form [id^=public-form-field-]").count()}`);
  await page.fill("#public-form-field-name", `SMOKE probe ${width}`);
  await page.fill("#public-form-field-email", "not-an-email");
  await page.locator("#public-form").evaluate((f) => { f.noValidate = true; });          // let PHP be the one to refuse
  await page.click("#public-form-send");
  await page.waitForSelector("#public-form-errors", { timeout: 20000 });
  console.log(`${width}: refused -> "${(await page.locator("#public-form-errors").innerText()).replace(/\s+/g, " ").slice(0, 90)}"; what was typed is kept: ${(await page.inputValue("#public-form-field-name")) === `SMOKE probe ${width}`}`);
  await page.fill("#public-form-field-name", `SMOKE probe ${width}`);
  await page.check("#public-form-field-i_agree_to_be_emailed"); await page.fill("#public-form-field-email", `smoke-probe-${width}-${Date.now()}@example.invalid`);
  await page.click("#public-form-send");
  await page.waitForSelector("#public-form-thanks", { timeout: 20000 });
  console.log(`${width}: sent -> ${new URL(page.url()).pathname}${new URL(page.url()).search} "${(await page.locator("#public-form-thanks").innerText()).replace(/\s+/g, " ").slice(0, 80)}"`);
  // The trap: a machine fills every input it finds.
  await page.goto(`http://127.0.0.1:3000/f/${slug}`, { waitUntil: "networkidle" });
  await page.fill("#public-form-field-name", `SMOKE bot ${width}`); await page.fill("#public-form-field-email", `bot-${width}@example.invalid`); await page.check("#public-form-field-i_agree_to_be_emailed");
  await page.locator("#public-form-website").evaluate((el) => { el.value = "http://spam.example.invalid"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.click("#public-form-send");
  await page.waitForSelector("#public-form-thanks", { timeout: 20000 });
  console.log(`${width}: bot -> thanked the same: ${await page.isVisible("#public-form-thanks")}; overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  if (closed) {
    await page.goto(`http://127.0.0.1:3000/f/${closed}`, { waitUntil: "networkidle" });
    console.log(`${width}: closed form -> "${(await page.locator("#public-form-refused").innerText()).trim()}"`);
  }
  await ctx.close();
}
await browser.close();
