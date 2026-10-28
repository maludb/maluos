import { NextRequest, NextResponse } from "next/server";
import { ApiError, apiGet } from "@/lib/api";
import { redirectTo } from "@/lib/redirect";

/**
 * /launch/<id> — the launcher's Open (A3, 2026-09-22): PHP mints the hand-off token for this
 * person and this application (html/launch.php) and this route sends the browser on to the
 * application's sign-on path. The browser never talks to PHP; a refusal comes back to the
 * launcher in PHP's own words.
 */
export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) return redirectTo("/launcher");
  // ?scope=<id>: open a scoped application at one of the person's sites or departments (db/141).
  const scope = req.nextUrl.searchParams.get("scope") ?? "";
  const scopeQuery = /^\d+$/.test(scope) ? `&scope=${scope}` : "";
  try {
    const answer = await apiGet<{ data: { location: string } }>(`/launch.php?application=${id}${scopeQuery}`);
    const location = answer.data.location;
    if (!/^https?:\/\//i.test(location)) throw new ApiError(502, "bad_response", "The platform gave an unexpected answer.");
    return NextResponse.redirect(location, 302);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return redirectTo(`/login?next=${encodeURIComponent(`/launch/${id}`)}`);
    const message = err instanceof ApiError ? err.message : "The application could not be opened.";
    return redirectTo(`/launcher?refused=${encodeURIComponent(message)}`);
  }
}
