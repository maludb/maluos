// The customer portal, as an EXTERNAL member. Usage:
//   scripts/verify.sh <external-member> --probe scripts/probe-portal.mjs request       -> workspace URLs end at /portal; sends a new request; prints its id
//   scripts/verify.sh <external-member> --probe scripts/probe-portal.mjs thread <id>   -> the request page: public replies shown, internal notes absent; replies
import { chromium } from "playwright";
const [sid, phase, ticket] = process.argv.slice(2);
const browser = await chromium.launch();
for (const width of phase === "request" ? [1280, 375] : [1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  await ctx.addCookies([{ name: "CSTSID", value: sid, domain: "127.0.0.1", path: "/" }, { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  if (phase === "request") {
    for (const path of ["/dashboard", "/contacts", "/tickets", "/settings/portal", "/forms/submissions"]) {
      await page.goto(`http://127.0.0.1:3000${path}`, { waitUntil: "networkidle" });
      console.log(`${width}: ${path} -> ${new URL(page.url()).pathname}`);
    }
    await page.goto("http://127.0.0.1:3000/portal", { waitUntil: "networkidle" });
    console.log(`${width}: portal -> sidebar: ${await page.locator(".nxl-navigation, #sidenav, .nxl-header").count()}; command bar: ${await page.locator("#command-bar, [data-command-bar]").count()}; cards: ${(await page.locator(".card[id^=portal-]").evaluateAll((els) => els.map((e) => e.id))).join(",")}`);
    console.log(`${width}: invoices: ${await page.locator("#portal-invoices-table tbody tr").count()} row(s) "${(await page.locator("#portal-invoices-table tbody tr").first().innerText()).replace(/\s+/g, " ").slice(0, 80)}"; quotes: ${(await page.locator("#portal-quotes-table tbody").innerText()).replace(/\s+/g, " ").slice(0, 70)}; payment note: ${await page.isVisible("#portal-payment-note")}`);
    if (width === 1280) {
      await page.click("#portal-request-add-btn");
      await page.waitForURL("**/portal/requests/new");
      await page.fill("#portal-request-subject", "SMOKE Keep — portal probe: the gate code stopped working");
      await page.fill("#portal-request-description", "SMOKE since Monday the side gate rejects our code.");
      await page.click("#portal-request-send");
      await page.waitForURL(/\/portal\/requests\/\d+$/, { timeout: 20000 });
      const id = new URL(page.url()).pathname.split("/").pop();
      await page.goto("http://127.0.0.1:3000/portal", { waitUntil: "networkidle" });
      console.log(`${width}: new request -> /portal/requests/${id}; listed on the portal: ${await page.locator(`#portal-requests a[href="/portal/requests/${id}"]`).count()}`);
      console.log(`REQUEST_ID=${id}`);
    }
    const res = await page.request.get("http://127.0.0.1:3000/api/download?src=" + encodeURIComponent("/portal/document.php?document=17"));
    const other = await page.request.get("http://127.0.0.1:3000/api/download?src=" + encodeURIComponent("/portal/document.php?document=21"));
    console.log(`${width}: shared document -> ${res.status()} ${res.headers()["content-type"]}; a document NOT shared -> ${other.status()}`);
    console.log(`${width}: overflow: ${await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)}; page errors: ${errors.length}`);
  } else {
    await page.goto(`http://127.0.0.1:3000/portal/requests/${ticket}`, { waitUntil: "networkidle" });
    const text = await page.locator("#portal-request-thread").innerText();
    console.log(`thread -> public reply shown: ${text.includes("SMOKE public reply")}; internal note shown: ${text.includes("SMOKE INTERNAL")}; messages: ${await page.locator("[id^=portal-message-]").count()}`);
    await page.fill("#portal-reply-field", "SMOKE thank you — that fixed it.");
    await page.locator("#portal-reply-btn").evaluate((b) => b.closest("form").requestSubmit(b));
    await page.waitForLoadState("networkidle"); await page.waitForTimeout(900);
    console.log(`reply -> messages: ${await page.locator("[id^=portal-message-]").count()}; box cleared: ${(await page.inputValue("#portal-reply-field")) === ""}`);
    await page.goto("http://127.0.0.1:3000/portal/requests/5", { waitUntil: "networkidle" });
    console.log(`someone else's ticket (5) -> ${(await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 90)}`);
  }
  await ctx.close();
}
await browser.close();
