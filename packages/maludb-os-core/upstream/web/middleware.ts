import { NextRequest, NextResponse } from "next/server";
import { faceOf, homePath, appHost, hostsConfigured, isLandingHost } from "@/lib/face";

/**
 * Three jobs, all cheap. (1) The host name decides the face (lib/face.ts): the operating system
 * at os.<domain>, the person face at app.<domain>. The bare domain and www.<domain> are the public
 * landing page (Apache's landing vhost serves it; should one reach here, its home is the same file,
 * public/landing → /var/www/landing) and are never sent to app. — the owner's rule, 2026-09-25.
 * Any other name (a retired staging name) is sent on to app.<domain>, path and query intact, with
 * a TEMPORARY redirect: a permanent one is cached by browsers and outlives the rule that sent it
 * (the 308 this used to send kept the bare name on app. after the landing page existed). On the person face
 * only sign-in, the launcher and the person's own settings exist; anything else goes to the
 * launcher. (2) A visitor with no session cookie is sent to /login?next=… before a shell page
 * renders — PHP still decides whether a cookie that IS present is any good (the shell layout asks
 * /api/v1/session). (3) Every request carries its own path as x-pathname and its face as x-face,
 * so a server layout can build a `next` for a session PHP has rejected and choose its chrome.
 */
const SESSION_COOKIE = "CSTSID";

// Reachable signed-out: the Agent View home (it renders its own sign-in card and the demo),
// the auth screens, this app's route handlers, and the diagnostics.
const PUBLIC = [/^\/$/, /^\/login(\/|$)/, /^\/register(\/|$)/, /^\/forgot(\/|$)/, /^\/reset(\/|$)/, /^\/api\//, /^\/hostcheck$/,
  // Google sign-in's two legs are how a visitor GETS a session — they cannot require one.
  /^\/auth\/google\/(start|callback)$/];

// What exists on the person face. Everything else there is the operating system's and redirects to the launcher.
const PERSON_FACE = [/^\/launcher$/, /^\/home$/, /^\/launch\/\d+$/, /^\/settings$/, /^\/settings\/channels$/, /^\/assistant$/, /^\/login(\/|$)/, /^\/register(\/|$)/, /^\/forgot(\/|$)/, /^\/reset(\/|$)/,
  /^\/api\//, /^\/hostcheck$/, /^\/auth\/google\/(start|callback)$/];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  const face = faceOf(host);

  if (face === null && isLandingHost(host)) {
    if (pathname === "/" || pathname === "/index.html") {
      const landing = req.nextUrl.clone();
      landing.pathname = "/landing/index.html";
      return NextResponse.rewrite(landing);
    }
    return NextResponse.redirect(`https://${appHost()}${pathname}${search}`, 307);
  }
  if (face === null && hostsConfigured()) {
    return NextResponse.redirect(`https://${appHost()}${pathname}${search}`, 307);
  }
  // app.<domain>/ — and so every sign-in, whose default `next` is / — goes where the person lands:
  // their default application, the only one they hold, or the launcher (/home decides; db/142).
  if (face === "app" && pathname === "/") {
    // ?app=<key> (an application sending a person with no session there) is kept, so /home can send them back.
    const app = req.nextUrl.searchParams.get("app");
    const home = req.nextUrl.clone();
    home.pathname = "/home";
    home.search = app && /^[a-z][a-z0-9_]{0,31}$/.test(app) ? `?app=${app}` : "";
    return NextResponse.redirect(home);
  }
  if (face === "app" && !PERSON_FACE.some((re) => re.test(pathname))) {
    const launcher = req.nextUrl.clone();
    launcher.pathname = homePath("app");
    launcher.search = "";
    return NextResponse.redirect(launcher);
  }

  if (!PUBLIC.some((re) => re.test(pathname)) && !req.cookies.has(SESSION_COOKIE)) {
    const login = req.nextUrl.clone();
    login.pathname = "/login";
    login.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(login);
  }

  const headers = new Headers(req.headers);
  headers.set("x-pathname", pathname + search);
  headers.set("x-face", face ?? "os");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/|assets/|landing/|favicon.ico).*)"],
};
