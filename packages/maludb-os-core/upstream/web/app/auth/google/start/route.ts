import { NextRequest, NextResponse } from "next/server";
import { ApiError, apiAuthGet, safeNext } from "@/lib/api";

/**
 * Leg one of Google sign-in (owner's decision, 2026-09-19: ported to the React login). PHP
 * still owns the flow — html/auth/google/start.php builds the authorisation URL and keeps the
 * `state` in the visitor's pre-login session; this route relays that session cookie and sends
 * the browser on to Google. The browser never talks to PHP.
 */
export async function GET(req: NextRequest) {
  const next = safeNext(req.nextUrl.searchParams.get("next"));
  const login = new URL(`/login?next=${encodeURIComponent(next)}`, req.nextUrl.origin);
  try {
    const answer = await apiAuthGet<{ ok: true; location?: string }>(`/auth/google/start.php?next=${encodeURIComponent(next)}`);
    // Only ever Google. Anything else PHP answers (Google not configured → its login page) is
    // this app's own sign-in page.
    if (answer.location && /^https:\/\/accounts\.google\.com\//.test(answer.location)) {
      return NextResponse.redirect(answer.location);
    }
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
  }
  return NextResponse.redirect(login);
}
