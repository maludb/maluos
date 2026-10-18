// Personal Settings' one-time-secret transport, exercised with the ONE secret path that writes
// nothing durable: starting a 2FA enrollment stores its pending secret in the PHP session only
// (no database write, no activity row) — and this probe's session is thrown away afterwards.
// A wrong code is then refused before anything is enabled. Usage: node scripts/probe-settings.mjs <session-id>
import { chromium } from "playwright";
const [sid] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
await page.goto("http://127.0.0.1:3000/settings?section=security", { waitUntil: "networkidle" });
await page.click("text=Enable 2FA");
await page.waitForSelector('img[alt="2FA QR code"]', { timeout: 15000 });
const src = await page.getAttribute('img[alt="2FA QR code"]', "src");
const key = (await page.textContent("code.user-select-all")).trim();
console.log(`enroll -> QR is a ${src.slice(0, 22)}… data URI (${src.length} chars); manual key has ${key.length} characters`);
console.log(`secret in the URL? ${page.url().includes(key)}; in a cookie? ${(await ctx.cookies()).some((c) => c.value.includes(key))}; in storage? ${await page.evaluate((k) => JSON.stringify({ ...localStorage, ...sessionStorage }).includes(k), key)}`);
await page.fill("#settings-2fa-code", "1");
await page.click("text=Confirm & enable");
await page.waitForSelector(".alert-danger", { timeout: 15000 });
console.log(`wrong code -> "${(await page.textContent(".alert-danger")).trim()}"; QR still shown: ${await page.isVisible('img[alt="2FA QR code"]')}`);
await page.goto("http://127.0.0.1:3000/settings?section=security", { waitUntil: "networkidle" });
console.log(`after leaving and returning -> QR shown: ${await page.isVisible('img[alt="2FA QR code"]')} (the secret lived in component state only)`);
console.log(`console errors: ${errors.length}`);
await browser.close();
