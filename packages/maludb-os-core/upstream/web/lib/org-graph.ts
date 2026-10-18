import { cookies } from "next/headers";
import type { OrgGraph, OrgGraphLoad } from "./types";
import { buildDemoGraph } from "./demo-data";

const SESSION_COOKIE = "CSTSID";

export function apiBaseUrl(): string {
  return process.env.API_BASE_URL || "http://localhost";
}

/**
 * Where to send a signed-out visitor. Returns null when LOGIN_URL is unset, and the sign-in
 * card then SAYS it is unconfigured rather than offering a link.
 *
 * It used to fall back to "http://localhost/login.php", which is the worst possible default:
 * a browser follows it to the VISITOR'S OWN machine, so the failure looks like a broken app
 * rather than missing configuration. Verified in the field 2026-09-18 — clicking sign-in
 * landed on localhost. A default that is silently wrong is worse than no default.
 */
export function loginUrl(): string | null {
  // Since the move into the one web app (docs/react-migration-plan.md) sign-in is a route of
  // this same app, so the fallback is a relative path — which cannot point at the wrong machine.
  const configured = (process.env.LOGIN_URL || "").trim();
  return configured === "" ? "/login" : configured;
}

/** The incoming visitor's session cookie, if any — forwarded server-side only. */
export async function sessionCookieHeader(): Promise<string | null> {
  const jar = await cookies();
  const value = jar.get(SESSION_COOKIE)?.value;
  if (!value) return null;
  return `${SESSION_COOKIE}=${value}`;
}

/**
 * Loads the org graph for the current request: demo data with no network call when
 * `demo=1`, otherwise a server-side fetch of the real org graph, forwarding the visitor's
 * session cookie. Never calls the PHP API from the browser — this only ever runs on the
 * server (route handlers / server components).
 */
export async function loadOrgGraph(demo: boolean): Promise<OrgGraphLoad> {
  if (demo) {
    return { ok: true, mode: "demo", graph: buildDemoGraph() };
  }

  const cookieHeader = await sessionCookieHeader();
  if (!cookieHeader) {
    return { ok: false, reason: "signed_out", loginUrl: loginUrl() };
  }

  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/v1/org-graph`, {
      headers: { Cookie: cookieHeader, Accept: "application/json" },
      cache: "no-store",
    });
  } catch (err) {
    // The upstream platform is unreachable — treat this the same as signed-out rather
    // than crashing the page; the link still gets the visitor somewhere useful.
    console.error("org-graph fetch failed:", err);
    return { ok: false, reason: "signed_out", loginUrl: loginUrl() };
  }

  if (res.status === 401) {
    return { ok: false, reason: "signed_out", loginUrl: loginUrl() };
  }
  if (!res.ok) {
    console.error("org-graph fetch returned", res.status, await res.text().catch(() => ""));
    return { ok: false, reason: "signed_out", loginUrl: loginUrl() };
  }

  const graph = (await res.json()) as OrgGraph;
  return { ok: true, mode: "live", graph };
}
