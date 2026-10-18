// End-to-end check of the multipart transport, with a request that writes NOTHING: the bank
// import's "Preview first 5 rows" posts the chosen CSV through the server action and
// lib/api.ts to import-preview.php, which parses it in memory and logs nothing.
// Usage: node scripts/probe-upload.mjs <session-id> <bank-account-id> <csv-path>
import { chromium } from "playwright";
const [sid, account, csv] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:3000/books/banks/import?bank_account=${account}`, { waitUntil: "networkidle" });
await page.click("#bank-import-preview-btn");                       // no file yet: PHP's own refusal
await page.waitForSelector("#bank-import-preview", { timeout: 15000 });
console.log("no file  ->", (await page.textContent("#bank-import-preview")).trim());
await page.setInputFiles("#bank-import-field-file", csv);
await page.click("#bank-import-preview-btn");
await page.waitForSelector("#bank-import-preview table", { timeout: 15000 });
console.log("with csv ->", (await page.textContent("#bank-import-preview")).replace(/\s+/g, " ").trim().slice(0, 260));
await browser.close();
