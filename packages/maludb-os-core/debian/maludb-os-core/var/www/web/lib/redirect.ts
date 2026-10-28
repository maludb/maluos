import { NextResponse } from "next/server";

/**
 * A redirect to one of this app's own paths from a route handler. Behind the two proxies
 * (openresty → Apache → :3000) a route handler's `req.url` names the address Next LISTENS on,
 * not the one the visitor typed — `new URL("/login", req.url)` sent the browser to
 * https://localhost:3000/login (2026-09-28). A Location that is just the path is resolved by
 * the browser against whatever name it used, so no host has to be guessed. Middleware needs
 * none of this: Next already strips its own origin from a middleware redirect.
 */
export function redirectTo(path: string, status: 302 | 303 | 307 | 308 = 307): NextResponse {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error(`redirectTo: not a path of this app: ${path}`);
  return new NextResponse(null, { status, headers: { Location: path } });
}
