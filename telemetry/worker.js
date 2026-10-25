// telemetry.maluos.com/v1/install: the MaluOS installer's one report per install (Phase 11 slice 2,
// docs/phase11-slice2-engine.md "The telemetry report and endpoint"). A Cloudflare Worker beside the
// download site's: POST only, JSON of at most 32 KB with v: 1, 60 requests per minute per address;
// the address is dropped and only the country code from Cloudflare's header is kept; each report is
// written to the R2 bucket bound as TELEMETRY (maluos-telemetry) as install/YYYY/MM/DD/<install_id>.json;
// 204 on success and nothing else. The daily summary is a later job.
const MAX_BODY = 32 * 1024;
const RATE = 60;                       // per minute per address, remembered in the Worker's memory per isolate
const seen = new Map();

function tooMany(ip) {
  const now = Date.now(), minute = Math.floor(now / 60000);
  const key = `${ip}:${minute}`;
  const n = (seen.get(key) || 0) + 1;
  seen.set(key, n);
  if (seen.size > 10000) for (const k of seen.keys()) { if (!k.endsWith(`:${minute}`)) seen.delete(k); }
  return n > RATE;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/v1/install") return new Response("not found", { status: 404 });
    if (request.method !== "POST") return new Response("POST only", { status: 405, headers: { Allow: "POST" } });
    const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
    if (tooMany(ip)) return new Response("too many requests", { status: 429 });
    const len = Number(request.headers.get("Content-Length") || 0);
    if (len > MAX_BODY) return new Response("too large", { status: 413 });
    const text = await request.text();
    if (text.length > MAX_BODY) return new Response("too large", { status: 413 });
    let doc;
    try { doc = JSON.parse(text); } catch { return new Response("bad json", { status: 400 }); }
    if (!doc || doc.v !== 1 || typeof doc.install_id !== "string" || !UUID.test(doc.install_id)
        || !["ok", "failed"].includes(doc.outcome)) {
      return new Response("bad report", { status: 400 });
    }
    // never kept: the address. kept: the country code Cloudflare saw (the owner may drop this too).
    const country = request.headers.get("CF-IPCountry") || "";
    const stored = { ...doc, country, received_at: new Date().toISOString() };
    for (const k of ["hostname", "user", "ip", "mac", "serial"]) delete stored[k];
    const d = new Date();
    const key = `install/${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${String(d.getUTCDate()).padStart(2, "0")}/${doc.install_id}.json`;
    await env.TELEMETRY.put(key, JSON.stringify(stored), { httpMetadata: { contentType: "application/json" } });
    return new Response(null, { status: 204 });
  },
};
