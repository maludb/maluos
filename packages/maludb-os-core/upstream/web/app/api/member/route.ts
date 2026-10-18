import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl, sessionCookieHeader } from "@/lib/org-graph";

// Proxies GET /api/v1/members?id={id} server-side for the profile panel's on-demand detail
// fetch (departments, manager, and for an agent: model_key, harness, hired/suspended/
// offboarded timestamps, and the orchestrator roster) — none of which the org-graph payload
// carries. The browser calls this route, never the PHP app directly.
export async function GET(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  if (!id || !/^\d+$/.test(id)) {
    return NextResponse.json({ error: { code: "bad_request", message: "A member id is required." } }, { status: 400 });
  }

  const cookieHeader = await sessionCookieHeader();
  if (!cookieHeader) {
    return NextResponse.json({ error: { code: "unauthorized", message: "Sign in required." } }, { status: 401 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/api/v1/members?id=${encodeURIComponent(id)}`, {
      headers: { Cookie: cookieHeader, Accept: "application/json" },
      cache: "no-store",
    });
  } catch (err) {
    console.error("member detail proxy fetch failed:", err);
    return NextResponse.json({ error: { code: "server_error", message: "Something went wrong." } }, { status: 502 });
  }

  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
