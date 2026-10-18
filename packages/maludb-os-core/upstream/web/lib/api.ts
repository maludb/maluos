import { cache } from "react";
import { cookies, headers } from "next/headers";

/**
 * The one client for the Business OS platform (docs/react-migration-plan.md, "Target
 * architecture"). SERVER-ONLY: server components read through it, server actions write through
 * it, and the browser never talks to PHP (files included — see apiPost and apiDownload). It forwards the visitor's CSTSID session cookie to PHP
 * on localhost, always asks for JSON, and relays any session cookie PHP issues back to the
 * browser — the delicate part, because login regenerates the session id.
 */

const SESSION_COOKIE = "CSTSID";

export function apiBaseUrl(): string {
  return process.env.API_BASE_URL || "http://localhost";
}

// -------------------------------------------------------------------------------------------
// Errors — PHP's one shape: { error: { code, message, errors?, fields? } }
// -------------------------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    /** Validation messages, in the handler's order (422 only). */
    public errors: string[] = [],
    /** Validation messages keyed by input name, where the handler provides them. */
    public fields: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// -------------------------------------------------------------------------------------------
// Session payload — GET /api/v1/session
// -------------------------------------------------------------------------------------------
/** One sidebar entry — a row of nav_items (db/127), as app_nav() admits it for this member. */
export type NavItem = {
  key: string; label: string; url: string; icon: string; phase: number;
  /** `new_tab`: an external application's own address, not a screen of ours. */
  opens: "same" | "new_tab";
  /** Other paths that belong to this entry (`/quotes` → Sales & Invoices). */
  active_patterns: string[];
};
export type SessionMember = {
  id: number;
  display_name: string;
  email: string;
  job_title: string | null;
  timezone: string;
  kind: "human" | "agent";
  business_role: "super_admin" | "dept_admin" | "user";
  is_external: boolean;
  is_super_admin: boolean;
  is_dept_admin: boolean;
  is_admin: boolean;
  admin_department_ids: number[];
};
export type Session = {
  authenticated: boolean;
  csrf_token: string;
  two_factor_pending: boolean;
  google_enabled: boolean;
  /** logo_url: the company's own logo (versioned, relayed by /api/avatar); null = the shipped logo-full.png. */
  business: { name: string; currency?: string; logo_url?: string | null };
  member: SessionMember | null;
  nav: { group: string; items: NavItem[] }[];
};

// -------------------------------------------------------------------------------------------
// Transport
// -------------------------------------------------------------------------------------------
type FormValue = string | number | boolean | null | undefined | (string | number)[];
type RawResult = { res: Response; sessionCookie: ParsedCookie | null };
type ParsedCookie = { value: string; attrs: Record<string, string | true> };

async function browserSessionCookie(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

/**
 * Headers every call carries. X-Web-Key proves to PHP that this localhost caller is us, so the
 * visitor's address in X-Forwarded-For is believed (per-IP login lockout, activity log ip).
 * Forwarded host/proto let PHP scope and secure the session cookie as if it saw the browser.
 */
async function baseHeaders(sessionId: string | null): Promise<Record<string, string>> {
  const incoming = await headers();
  const out: Record<string, string> = { Accept: "application/json" };
  if (sessionId) out.Cookie = `${SESSION_COOKIE}=${sessionId}`;
  if (process.env.WEB_INTERNAL_KEY) out["X-Web-Key"] = process.env.WEB_INTERNAL_KEY;

  const forwardedFor = incoming.get("x-forwarded-for") ?? incoming.get("x-real-ip");
  if (forwardedFor) out["X-Forwarded-For"] = forwardedFor.split(",")[0].trim();
  const host = incoming.get("x-forwarded-host") ?? incoming.get("host");
  if (host) out["X-Forwarded-Host"] = host;
  const proto = incoming.get("x-forwarded-proto");
  if (proto) out["X-Forwarded-Proto"] = proto;
  // The visitor's browser, for evidence PHP keeps (a signer's signature trail). Believed, like the
  // address, only with X-Web-Key.
  const agent = incoming.get("user-agent");
  if (agent) out["X-Forwarded-User-Agent"] = agent.slice(0, 300);
  return out;
}

function parseSessionCookie(res: Response): ParsedCookie | null {
  for (const line of res.headers.getSetCookie()) {
    const [pair, ...rest] = line.split(";");
    const eq = pair.indexOf("=");
    if (eq < 0 || pair.slice(0, eq).trim() !== SESSION_COOKIE) continue;
    const attrs: Record<string, string | true> = {};
    for (const part of rest) {
      const i = part.indexOf("=");
      if (i < 0) attrs[part.trim().toLowerCase()] = true;
      else attrs[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim();
    }
    return { value: decodeURIComponent(pair.slice(eq + 1).trim()), attrs };
  }
  return null;
}

/**
 * Hand PHP's session cookie to the browser with the attributes PHP chose. Only possible in a
 * server action or route handler; during a render Next.js forbids it, and losing a cookie
 * there is harmless (an anonymous GET's throwaway pre-login session).
 */
async function relaySessionCookie(cookie: ParsedCookie | null): Promise<void> {
  if (!cookie) return;
  try {
    const jar = await cookies();
    const expires = typeof cookie.attrs.expires === "string" ? new Date(cookie.attrs.expires) : undefined;
    if (cookie.value === "" || cookie.value === "deleted" || (expires && expires.getTime() < Date.now())) {
      jar.delete(SESSION_COOKIE);
      return;
    }
    jar.set(SESSION_COOKIE, cookie.value, {
      httpOnly: true,
      secure: cookie.attrs.secure === true,
      sameSite: "lax",
      path: typeof cookie.attrs.path === "string" ? cookie.attrs.path : "/",
      domain: typeof cookie.attrs.domain === "string" ? cookie.attrs.domain : undefined,
      expires,
    });
  } catch {
    // Render context — see above.
  }
}

async function raw(path: string, init: RequestInit, sessionId: string | null): Promise<RawResult> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      headers: { ...(await baseHeaders(sessionId)), ...(init.headers as Record<string, string> | undefined) },
      cache: "no-store",
      redirect: "manual",
    });
  } catch (err) {
    console.error(`platform unreachable: ${path}`, err);
    throw new ApiError(502, "unreachable", "The platform could not be reached.");
  }
  return { res, sessionCookie: parseSessionCookie(res) };
}

async function unwrap<T>(path: string, res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text === "" ? null : JSON.parse(text);
  } catch {
    // Not JSON: the endpoint ignored Accept (HTML from an unconverted handler, a PHP fatal).
    console.error(`non-JSON answer from ${path} [${res.status}]`, text.slice(0, 200));
    throw new ApiError(res.ok ? 502 : res.status, "bad_response", "The platform gave an unexpected answer.");
  }
  if (!res.ok) {
    const e = (body as { error?: { code?: string; message?: string; errors?: string[]; fields?: Record<string, string> } })?.error;
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? "Something went wrong.", e?.errors ?? [], e?.fields ?? {});
  }
  return body as T;
}

// -------------------------------------------------------------------------------------------
// Public surface
// -------------------------------------------------------------------------------------------

/**
 * Read a screen or resource. `screenView: true` marks a real page render so PHP logs the screen
 * view; leave it off for anything speculative (prefetch, background refresh) — activity memory
 * cannot be un-polluted.
 */
export async function apiGet<T>(path: string, opts: { screenView?: boolean } = {}): Promise<T> {
  const { res } = await raw(
    path,
    { method: "GET", headers: opts.screenView ? { "X-Screen-View": "1" } : undefined },
    await browserSessionCookie(),
  );
  return unwrap<T>(path, res);
}

/**
 * A GET that may change who the visitor is — the two legs of Google sign-in. Like apiGet(), but
 * PHP's session cookie is relayed to the browser (the OAuth state lives in the pre-login
 * session; a successful callback issues a new session id). Route handlers only.
 */
export async function apiAuthGet<T>(path: string): Promise<T> {
  const { res, sessionCookie } = await raw(path, { method: "GET" }, await browserSessionCookie());
  await relaySessionCookie(sessionCookie);
  return unwrap<T>(path, res);
}

/**
 * The session + shell payload: fetched once per request however many components ask, and kept
 * for this process for SHELL_TTL_MS per signed-in session (owner, 2026-09-28: every navigation
 * paid a second PHP call, ~90 ms, for the member, the business and the navigation tree, which
 * change rarely). Keyed by the session cookie, so one person's shell never serves another; only
 * a signed-in session past 2FA is kept, so the sign-in pages always ask PHP; forgotten the moment
 * this person writes anything (apiPost) — their settings, their default application, a logout —
 * and expired by time for what someone else changes (a role, an application enabled). A session
 * PHP has stopped honouring is still caught: the page's own read answers 401 and renderScreen()
 * sends the visitor to sign in.
 */
const SHELL_TTL_MS = 30_000;
const SHELL_CACHE_MAX = 1000;
const shellCache = new Map<string, { at: number; session: Session }>();

export function forgetShell(sessionId: string | null): void {
  if (sessionId) shellCache.delete(sessionId);
}

export const getSession = cache(async (): Promise<Session> => {
  const sessionId = await browserSessionCookie();
  const hit = sessionId ? shellCache.get(sessionId) : undefined;
  if (hit && Date.now() - hit.at < SHELL_TTL_MS) return hit.session;
  const session = await apiGet<Session>("/api/v1/session");
  if (sessionId && session.authenticated && !session.two_factor_pending) {
    if (shellCache.size >= SHELL_CACHE_MAX) {
      const oldest = shellCache.keys().next().value;
      if (oldest !== undefined) shellCache.delete(oldest);
    }
    shellCache.set(sessionId, { at: Date.now(), session });
  }
  return session;
});

/**
 * State change: POST a form to a PHP handler at its existing path. Fetches the session's CSRF
 * token first (creating the pre-login session if the visitor has none), sends it as
 * X-CSRF-Token, and relays whichever session cookie PHP ends up with. Server actions only.
 */
export async function apiPost<T = { ok: true; location?: string }>(
  path: string,
  form: Record<string, FormValue> | FormData = {},
): Promise<T> {
  let sessionId = await browserSessionCookie();

  const pre = await raw("/api/v1/session", { method: "GET" }, sessionId);
  const session = await unwrap<Session>("/api/v1/session", pre.res);
  if (pre.sessionCookie) sessionId = pre.sessionCookie.value;

  const body = new URLSearchParams();
  const files: [string, File][] = [];
  if (form instanceof FormData) {
    // A browser form as submitted: names already carry their [] suffix; Next.js's own
    // bookkeeping fields ($ACTION_…) are not PHP's business. An empty file input arrives as a
    // nameless zero-byte File — that is "no file chosen", and PHP must see no upload at all.
    for (const [name, value] of form.entries()) {
      if (name.startsWith("$ACTION")) continue;
      if (typeof value === "string") body.append(name, value);
      else if (value.size > 0) files.push([name, value]);
    }
  }
  for (const [name, value] of form instanceof FormData ? [] : Object.entries(form)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) value.forEach((v) => body.append(`${name}[]`, String(v)));
    else body.append(name, typeof value === "boolean" ? (value ? "1" : "") : String(value));
  }

  // A form that carries a file goes as multipart/form-data (owner's decision 4, 2026-09-19);
  // everything else stays urlencoded, as before. fetch() writes the multipart boundary itself,
  // so no Content-Type is set for it. The size a server action accepts is
  // serverActions.bodySizeLimit in next.config.mjs; PHP's own limits still apply after that.
  let payload: URLSearchParams | FormData = body;
  const postHeaders: Record<string, string> = { "X-CSRF-Token": session.csrf_token };
  if (files.length > 0) {
    const multipart = new FormData();
    for (const [name, value] of body.entries()) multipart.append(name, value);
    for (const [name, file] of files) multipart.append(name, file, file.name);
    payload = multipart;
  } else {
    postHeaders["Content-Type"] = "application/x-www-form-urlencoded";
  }

  const post = await raw(path, { method: "POST", headers: postHeaders, body: payload }, sessionId);

  // A write may have changed this person's shell (their name, their default application, a logout):
  // the cached copy goes, under the cookie they came with and the one they leave with.
  forgetShell(sessionId);
  forgetShell(post.sessionCookie?.value ?? null);
  // Relay before unwrapping: a refused login still leaves the visitor on the pre-login session
  // PHP just created, and the next attempt must present that same cookie.
  await relaySessionCookie(post.sessionCookie ?? pre.sessionCookie);
  return unwrap<T>(path, post.res);
}

/** Constrain a post-login destination to a local path (mirrors PHP's safe_next()). */
/**
 * Fetch a file PHP streams (a CSV export), as the visitor: their session cookie AND the
 * forwarded-address headers every other call carries — a download PHP logs must record who
 * asked, not 127.0.0.1. Asks for the file, not JSON, so the endpoint answers as it always has.
 * Route handlers only, and only for a path the route has allow-listed (app/api/download).
 */
export async function apiDownload(path: string): Promise<Response> {
  const { res } = await raw(path, { method: "GET", headers: { Accept: "*/*" } }, await browserSessionCookie());
  return res;
}

export function safeNext(next: string | undefined | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  return next;
}
