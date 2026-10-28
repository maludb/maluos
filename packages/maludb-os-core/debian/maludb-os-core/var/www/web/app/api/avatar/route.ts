import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl, sessionCookieHeader } from "@/lib/org-graph";

// Streams an avatar/agent photo from the platform, server-side, forwarding the visitor's
// session cookie — the browser never talks to the PHP app directly (agent photos require
// an authenticated "insider" session; see html/agents/photo.php). `src` must be a
// same-origin-relative path from the org-graph/member payloads, e.g.
// "/assets/img/avatars/avatar-01.svg" or "/agents/photo.php?agent=34" (the agents screens send
// it versioned, "&v=<unix time of the upload>", so a new picture is a new address), or the
// company's logo "/settings/business/logo.php?v=…" (db/134), which the shell shows on every
// signed-in screen.
export async function GET(req: NextRequest) {
  const src = req.nextUrl.searchParams.get("src") || "";

  // Only a relative, same-app path is allowed — never an absolute URL, never a
  // protocol-relative one, both of which could be used to make this route fetch an
  // arbitrary third-party URL.
  if (!src.startsWith("/") || src.startsWith("//")) {
    return new NextResponse(null, { status: 400 });
  }
  // And only the two places a picture lives. Without this the route would relay ANY platform
  // path under the visitor's session — a page of HTML, a JSON endpoint — to the browser,
  // which is exactly the "browser talks to PHP" the architecture rules out.
  const photo = /^\/agents\/photo\.php\?agent=\d+(&v=\d+)?$/.exec(src)
    ?? /^\/settings\/business\/logo\.php(?:\?v=(\d+))?$/.exec(src);
  if (!photo && !/^\/assets\/[\w./-]+\.(svg|png|jpe?g|webp|gif)$/i.test(src)) {
    return new NextResponse(null, { status: 400 });
  }

  const cookieHeader = await sessionCookieHeader();
  if (!cookieHeader) {
    return new NextResponse(null, { status: 401 });
  }

  let upstream: Response;
  try {
    const headers: Record<string, string> = { Cookie: cookieHeader };
    const ifNoneMatch = req.headers.get("if-none-match");
    if (ifNoneMatch) headers["If-None-Match"] = ifNoneMatch;
    // redirect: "manual" — a dead session answers with a redirect to the login page, and
    // following it would relay that page of HTML as the picture.
    upstream = await fetch(`${apiBaseUrl()}${src}`, { headers, cache: "no-store", redirect: "manual" });
  } catch (err) {
    console.error("avatar proxy fetch failed:", err);
    return new NextResponse(null, { status: 502 });
  }

  // An agent's photo (or the logo) is replaced under an unchanged address, so a copy the browser may reuse
  // unasked shows the old face after a new upload. A versioned address can be kept for as long
  // as the browser likes; an unversioned photo is kept but re-checked every time against PHP's
  // ETag (the sha256 of the bytes) — a 304 when nothing changed. Static avatars never change.
  const cacheControl = !photo ? "private, max-age=300"
    : photo[1] ? "private, max-age=86400, immutable"
    : "private, no-cache";
  const etag = upstream.headers.get("etag");

  if (upstream.status >= 300 && upstream.status < 400 && upstream.status !== 304) {
    return new NextResponse(null, { status: 401 });
  }
  if (upstream.status === 304) {
    return new NextResponse(null, {
      status: 304,
      headers: { "Cache-Control": cacheControl, ...(etag ? { ETag: etag } : {}) },
    });
  }
  if (!upstream.ok || !upstream.body) {
    return new NextResponse(null, { status: upstream.status || 502 });
  }

  const contentType = upstream.headers.get("content-type") || "image/svg+xml";
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": cacheControl,
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
