import { NextResponse } from "next/server";
import { ApiError, apiGet } from "@/lib/api";
import { redirectTo } from "@/lib/redirect";

type Destination = { kind: "open"; path: string; application_id: number } | { kind: "launcher"; notice: string | null };

/**
 * /home — where app.<domain>/ takes a signed-in person (db/142; docs/build-specs/kernel-default-application.md).
 * PHP decides (html/home.php, from the launcher's own list): straight into their default application,
 * or the only one they hold; otherwise the launcher. The launcher never redirects back here, so a
 * "switch application" link cannot loop.
 */
export async function GET(req: Request) {
  // ?app=<key>: an application sent the person to app.<domain> with no session of its own — straight back into it.
  const app = new URL(req.url).searchParams.get("app") ?? "";
  const asked = /^[a-z][a-z0-9_]{0,31}$/.test(app) ? app : "";
  try {
    const answer = await apiGet<{ data: { destination: Destination } }>(asked ? `/home.php?app=${asked}` : "/home.php");
    const d = answer.data.destination;
    if (d.kind === "open") {
      if (d.path.startsWith("/launch/")) return redirectTo(d.path);
      if (/^https?:\/\//i.test(d.path)) return NextResponse.redirect(d.path, 302);
    }
    const refused = d.kind === "launcher" && d.notice ? `?refused=${encodeURIComponent(d.notice)}` : "";
    return redirectTo(`/launcher${refused}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return redirectTo(`/login?next=${encodeURIComponent(asked ? `/home?app=${asked}` : "/home")}`);
    return redirectTo("/launcher");
  }
}
