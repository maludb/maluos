import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl, sessionCookieHeader } from "@/lib/org-graph";

// The Chat tab's poll (docs/build-specs/agent-chat.md): GET ?run=<id>&after=<event seq> asks PHP for the state of
// ONE chat turn — its words, its status, the tool events since the cursor. The browser calls this route, never the
// PHP app; PHP decides (the turn must belong to one of the caller's own conversations) and this only carries it.
export async function GET(req: NextRequest) {
  const run = req.nextUrl.searchParams.get("run");
  const after = req.nextUrl.searchParams.get("after") ?? "0";
  if (!run || !/^\d+$/.test(run) || !/^\d+$/.test(after)) {
    return NextResponse.json({ error: { code: "bad_request", message: "A run id is required." } }, { status: 400 });
  }
  const cookieHeader = await sessionCookieHeader();
  if (!cookieHeader) {
    return NextResponse.json({ error: { code: "unauthorized", message: "Sign in required." } }, { status: 401 });
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/agents/chat-turn.php?run=${run}&after=${after}`, {
      headers: { Cookie: cookieHeader, Accept: "application/json" },
      cache: "no-store",
    });
  } catch (err) {
    console.error("agent chat poll failed:", err);
    return NextResponse.json({ error: { code: "server_error", message: "Something went wrong." } }, { status: 502 });
  }
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
