import { NextRequest } from "next/server";

// TEMPORARY diagnostic (2026-09-18) — the mirror of html/_hostcheck.php, for the agentview
// host. Delete both once the cookie chain is confirmed. Reports only how the request arrived
// through the reverse proxy and whether a session cookie came with it: no session contents,
// no secrets, no API call.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const h = req.headers;
  const cookie = h.get("cookie") ?? "";
  const lines = [
    ["host", h.get("host")],
    ["x-forwarded-host", h.get("x-forwarded-host")],
    ["x-forwarded-proto", h.get("x-forwarded-proto")],
    ["x-forwarded-for", h.get("x-forwarded-for")],
  ].map(([k, v]) => `${(k as string).padEnd(24)} ${v ?? "(absent)"}`);

  lines.push("-".repeat(50));
  lines.push(`cookie header present:   ${cookie === "" ? "NO" : "yes"}`);
  lines.push(`CSTSID cookie present:   ${/(^|;\s*)CSTSID=/.test(cookie) ? "yes" : "NO"}`);
  lines.push(`cookie names seen:       ${
    cookie === "" ? "(none)" : cookie.split(";").map((c) => c.split("=")[0].trim()).join(", ")
  }`);
  lines.push(`API_BASE_URL configured: ${process.env.API_BASE_URL ?? "(unset)"}`);
  lines.push(`LOGIN_URL configured:    ${process.env.LOGIN_URL ?? "(unset)"}`);

  return new Response(lines.join("\n") + "\n", {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
