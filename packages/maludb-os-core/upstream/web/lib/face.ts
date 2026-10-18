/**
 * The kernel has two faces on one codebase (A2, 2026-09-22 — docs/business-os-integration.md,
 * "Hosts"): `os.<domain>`, where super-admins run the operating system, and `app.<domain>`, where
 * every human signs in and launches the applications they are granted. The face is decided from
 * the host name the browser used; the middleware stamps it on the request as `x-face`, and a
 * layout reads it from there. With no hosts configured (a development box) there is one face, the
 * operating system, and nothing here changes behaviour.
 */
export type Face = "os" | "app";

const clean = (value: string | undefined | null): string =>
  (value ?? "").trim().toLowerCase().split(":")[0];

export function osHost(): string { return clean(process.env.OS_HOST); }
export function appHost(): string { return clean(process.env.APP_HOST); }
export function hostsConfigured(): boolean { return osHost() !== "" && appHost() !== ""; }

/** The face a host name belongs to, or null for a name that is neither (the bare domain, an old name). */
export function faceOf(host: string | null | undefined): Face | null {
  if (!hostsConfigured()) return "os";
  const h = clean(host);
  if (h === osHost()) return "os";
  if (h === appHost()) return "app";
  if (h === "localhost" || h === "127.0.0.1" || h === "") return "os";   // health checks and the deploy script
  return null;
}

/**
 * The bare domain and its www. name: the public landing page, never a face. The domain is what
 * follows the first label of APP_HOST (app.subello.com → subello.com).
 */
export function isLandingHost(host: string | null | undefined): boolean {
  if (!hostsConfigured()) return false;
  const bare = appHost().split(".").slice(1).join(".");
  const h = clean(host);
  return bare !== "" && (h === bare || h === `www.${bare}`);
}

/** Where a signed-in visitor lands on each face. */
export const homePath = (face: Face): string => (face === "app" ? "/launcher" : "/dashboard");

export const osUrl = (): string | null => (hostsConfigured() ? `https://${osHost()}` : null);
export const appUrl = (): string | null => (hostsConfigured() ? `https://${appHost()}` : null);
