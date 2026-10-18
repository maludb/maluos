// Company Profile through the browser: the React forms → server action → PHP, files included.
// It WRITES (as the session's member): replaces the logo with the given picture, tries an impostor,
// adds a social-link row and saves the profile, then moves a card down and back up.
// Usage: scripts/verify.sh <super-admin-id> --probe scripts/probe-company.mjs <picture.png> <impostor.png>
import { chromium } from "playwright";
const [sid, picture, impostor] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("dialog", (d) => d.accept());

await page.goto("http://127.0.0.1:3000/company/edit", { waitUntil: "networkidle" });
await page.setInputFiles("#company-profile-edit-field-logo", impostor);
await page.click("#company-profile-edit-logo-upload");
await page.waitForSelector("#company-profile-edit-logo .alert", { timeout: 15000 });
console.log("impostor  ->", (await page.textContent("#company-profile-edit-logo .alert")).trim());

const before = await page.getAttribute("#company-profile-edit-logo img", "src");
await page.setInputFiles("#company-profile-edit-field-logo", picture);
await page.click("#company-profile-edit-logo-upload");
await page.waitForFunction((old) => document.querySelector("#company-profile-edit-logo img")?.getAttribute("src") !== old, before, { timeout: 15000 });
console.log("logo      ->", before, "=>", await page.getAttribute("#company-profile-edit-logo img", "src"));

const rows = await page.locator('#company-profile-edit-social input[name="social_url[]"]').count();
await page.click("#company-profile-edit-social-add");
await page.locator('#company-profile-edit-social input[name="social_label[]"]').nth(rows).fill("Probe");
await page.locator('#company-profile-edit-social input[name="social_url[]"]').nth(rows).fill("https://example.org/probe");
await page.click("#company-profile-edit-save");
await page.waitForURL(/\/company\?saved=1$/, { timeout: 15000 });
console.log("saved     ->", (await page.textContent("#company-profile-saved")).trim(), "| social:", (await page.textContent("#company-profile-social")).replace(/\s+/g, " ").trim());

const order = async () => (await page.locator("#company-profile-items h6").allTextContents()).join(" | ");
const first = await order();
await page.locator('#company-profile-items button[aria-label^="Move"][aria-label$="down"]').first().click();
await page.waitForFunction((o) => [...document.querySelectorAll("#company-profile-items h6")].map((h) => h.textContent).join(" | ") !== o, first, { timeout: 15000 });
console.log("moved     ->", first, "=>", await order());
const second = await order();
await page.locator('#company-profile-items button[aria-label^="Move"][aria-label$="up"]').nth(1).click();
await page.waitForFunction((o) => [...document.querySelectorAll("#company-profile-items h6")].map((h) => h.textContent).join(" | ") !== o, second, { timeout: 15000 });
console.log("and back  ->", await order());
console.log("page errors:", errors.length ? errors : "none");
await browser.close();
