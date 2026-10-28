// The signed-out auth screens in a real browser, at 1280 and 375, using only requests that
// write nothing: a forgot for an address that cannot exist, a register with no invitation,
// a reset with a dead token. Usage: node scripts/probe-auth.mjs
import { chromium } from "playwright";
const browser = await chromium.launch();
let failed = 0;
const say = (ok, what, detail = "") => { if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${detail ? " — " + detail : ""}`); };
for (const viewport of [{ width: 1280, height: 800 }, { width: 375, height: 667 }]) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
  const w = viewport.width;
  const noScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

  await page.goto("http://127.0.0.1:3000/forgot", { waitUntil: "networkidle" });
  say(await page.isVisible("#forgot-form") && await noScroll(), `${w} /forgot renders`);
  await page.fill("#forgot-field-email", `nobody-${Date.now()}@example.invalid`);
  await page.click("#forgot-submit-btn");
  await page.waitForSelector("#forgot-notice", { timeout: 15000 });
  say(true, `${w} /forgot answers`, (await page.textContent("#forgot-notice")).trim());

  await page.goto("http://127.0.0.1:3000/reset?token=not-a-real-token", { waitUntil: "networkidle" });
  say((await page.textContent("#reset-error"))?.includes("invalid or has expired") && await noScroll(), `${w} /reset with a dead token`,
      `hidden token="${await page.inputValue('#reset-form input[name=token]')}"`);

  await page.goto("http://127.0.0.1:3000/register?token=not-a-real-token", { waitUntil: "networkidle" });
  say((await page.textContent("#register-error"))?.includes("invitation link is invalid"), `${w} /register with a dead token`);
  await page.goto("http://127.0.0.1:3000/register", { waitUntil: "networkidle" });
  say(await page.isVisible("#register-form") && await noScroll(), `${w} /register renders`);
  await page.fill("#register-field-name", "Probe");
  await page.fill("#register-field-email", `nobody-${Date.now()}@example.invalid`);
  await page.fill("#register-field-password", "short");
  await page.fill("#register-field-password-confirm", "other");
  await page.click("#register-submit-btn");
  await page.waitForSelector("#register-errors", { timeout: 15000 });
  say(true, `${w} /register refuses`, (await page.textContent("#register-errors")).replace(/\s+/g, " ").trim().slice(0, 140));
  say((await page.inputValue("#register-field-name")) === "Probe", `${w} /register keeps what was typed`);
  say(errors.length === 0, `${w} no console errors`, errors.slice(0, 2).join(" | "));
  say((await page.locator("[hx-get],[hx-post]").count()) === 0, `${w} no hx- attributes`);
  await ctx.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
