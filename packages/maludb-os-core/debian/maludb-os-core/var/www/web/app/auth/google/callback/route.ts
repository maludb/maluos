import { NextRequest, NextResponse } from "next/server";
import { ApiError, apiAuthGet, safeNext } from "@/lib/api";

/**
 * Leg two of Google sign-in: Google sends the browser here (this is the redirect URI to
 * register at Google — GOOGLE_REDIRECT_URI must name it). The query is handed to PHP's
 * callback unchanged, with the visitor's session cookie, and PHP does all of it: the state
 * check, the rate limit, the token exchange, the linking rules, invitations, 2FA, the session
 * and the activity rows. Its answer is where to go next; its new session cookie is relayed.
 */
export async function GET(req: NextRequest) {
  const origin = req.nextUrl.origin;
  const query = new URLSearchParams();
  for (const key of ["code", "state", "error"]) {
    const value = req.nextUrl.searchParams.get(key);
    if (value !== null) query.set(key, value);
  }

  let location: string | undefined;
  try {
    location = (await apiAuthGet<{ ok: true; location?: string }>(`/auth/google/callback.php?${query}`)).location;
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    // One sentence whatever went wrong — PHP logged the reason, the visitor is not told it.
    return NextResponse.redirect(new URL("/login?error=google", origin));
  }

  // PHP names its own pages; these are this app's.
  const twoFactor = location?.match(/^\/login\/2fa\.php\?next=(.*)$/);
  if (twoFactor) {
    return NextResponse.redirect(new URL(`/login/2fa?next=${encodeURIComponent(safeNext(decodeURIComponent(twoFactor[1])))}`, origin));
  }
  if (!location || location.startsWith("/login.php")) return NextResponse.redirect(new URL("/login", origin));
  return NextResponse.redirect(new URL(safeNext(location), origin));
}
