// The PDF render service (groundwork for the stubbed modules — owner's decision 5, 2026-09-19:
// headless Chromium through the Playwright already installed, so a PDF looks like its screen).
//
//   POST http://127.0.0.1:8820/render   {"path": "/reports/12/print", "cookie": "CSTSID=…"}
//   → 200 application/pdf
//
// It renders ONLY this app's own pages: `path` must be a relative path, and it is loaded from the
// web app on localhost. It carries whatever session cookie the caller hands it and nothing else,
// so a PDF holds exactly what that person's screen would show — the page's own gate still
// applies. Bound to 127.0.0.1; callers are the Next.js server (a download route, forwarding the
// visitor's cookie) and PHP (a signed document's executed copy, through a public token page).
// One browser for the life of the process, one fresh context per request.
import http from "node:http";
import { chromium } from "playwright";

const PORT = Number(process.env.PDF_PORT || 8820);
const APP = process.env.PDF_APP_ORIGIN || "http://127.0.0.1:3000";
const MAX_BODY = 16 * 1024;
const TIMEOUT_MS = 30_000;

let browser = null;
async function getBrowser() {
  if (!browser || !browser.isConnected()) browser = await chromium.launch({ args: ["--no-sandbox"] });
  return browser;
}

function refuse(res, status, message) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: message }));
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end('{"status":"ok"}');
  }
  if (req.method !== "POST" || req.url !== "/render") return refuse(res, 404, "POST /render");

  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (body.length > MAX_BODY) return refuse(res, 413, "Request too large.");
  }
  let input;
  try { input = JSON.parse(body); } catch { return refuse(res, 400, "Body must be JSON."); }

  const path = String(input.path ?? "");
  // A relative path of this app, never a URL: this service must not become a way to fetch
  // (or print) anything else reachable from this machine.
  if (!/^\/(?!\/)[^\s\\]*$/.test(path) || path.includes("://")) return refuse(res, 400, "path must be a relative path of this app.");
  const cookie = String(input.cookie ?? "");
  if (cookie !== "" && !/^[A-Za-z0-9_]+=[A-Za-z0-9%._,-]+$/.test(cookie)) return refuse(res, 400, "cookie must be one name=value pair.");

  let context;
  try {
    context = await (await getBrowser()).newContext({ viewport: { width: 1100, height: 1400 } });
    if (cookie !== "") {
      const [name, ...rest] = cookie.split("=");
      // bos_quiet: printing a page is not a person opening it — no screen view is logged.
      await context.addCookies([
        { name, value: rest.join("="), domain: "127.0.0.1", path: "/" },
        { name: "bos_quiet", value: "1", domain: "127.0.0.1", path: "/" },
      ]);
    }
    const page = await context.newPage();
    const response = await page.goto(APP + path, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    if (!response || response.status() >= 400) return refuse(res, 502, `The page answered ${response ? response.status() : "nothing"}.`);
    await page.emulateMedia({ media: "print" });
    const pdf = await page.pdf({
      format: input.format === "Letter" ? "Letter" : "A4", printBackground: true,
      margin: { top: "16mm", bottom: "16mm", left: "14mm", right: "14mm" },
    });
    res.writeHead(200, { "Content-Type": "application/pdf", "Content-Length": pdf.length, "Cache-Control": "no-store" });
    res.end(pdf);
  } catch (err) {
    console.error("pdf render failed:", path, String(err).split("\n")[0]);
    refuse(res, 500, "The page could not be rendered.");
  } finally {
    await context?.close().catch(() => {});
  }
});

server.listen(PORT, "127.0.0.1", () => console.log(`pdf service on 127.0.0.1:${PORT}, rendering ${APP}`));
for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, async () => { await browser?.close().catch(() => {}); process.exit(0); });
