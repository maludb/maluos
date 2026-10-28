import { NextRequest, NextResponse } from "next/server";
import { apiDownload } from "@/lib/api";
import { redirectTo } from "@/lib/redirect";

// The files PHP streams, relayed to the browser — which never talks to PHP itself. The list is
// closed: without it this route would hand the browser ANY platform path under the visitor's
// session. Each entry is a GET that PHP gates, and the accountant export also LOGS the download
// (accountant_export.download) — apiDownload() carries the visitor's forwarded address so that
// row names them, not this server.
// Since the kernel cut of 2026-09-22 only the kernel's own files are here; a kernel screen that streams
// a file adds its pattern.
const ALLOWED: RegExp[] = [
  // The ledger's period statement as a file (A5): PHP builds the os.ledger-period/1 document for the ledger grant and logs ai_period.export.
  /^\/ai\/spend\/export\.php\?period=\d{4}-\d{2}&format=(csv|json)$/,
];

export async function GET(req: NextRequest) {
  const src = req.nextUrl.searchParams.get("src") ?? "";
  if (!ALLOWED.some((pattern) => pattern.test(src))) return new NextResponse(null, { status: 400 });

  const upstream = await apiDownload(src);
  // Asked for a file, not JSON, PHP answers a signed-out visitor with its login redirect.
  if (upstream.status === 401 || (upstream.status >= 300 && upstream.status < 400)) {
    return redirectTo("/login");
  }
  if (!upstream.ok || !upstream.body) return new NextResponse(null, { status: upstream.status === 403 || upstream.status === 404 ? upstream.status : 502 });

  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of ["content-type", "content-disposition", "x-content-type-options"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new NextResponse(upstream.body, { status: 200, headers });
}
