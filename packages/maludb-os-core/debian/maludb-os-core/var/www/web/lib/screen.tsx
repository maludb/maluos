import { cookies, headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";
import type { z } from "zod";
import { ApiError, apiGet } from "./api";
import Refused from "@/components/kit/Refused";

/**
 * Read a screen's data from its PHP endpoint and render it — the one place a page's failure
 * modes are handled, so no page handles them differently:
 *   401 → /login?next=<here>      404 → the not-found page
 *   403 → PHP's own refusal, shown in the shell (it names what is in the way — a production
 *         error boundary would strip the message, so this is rendered, not thrown)
 *   501 → the endpoint has no JSON branch yet (a migration gap, said plainly)
 * The read is marked as a real screen view and PHP logs it — except the refresh that follows an
 * in-place write, which is nobody opening anything. The payload is parsed against the
 * feature's zod schema — a mismatch is a contract bug and throws.
 */
export async function renderScreen<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  render: (data: z.infer<S>) => ReactNode,
): Promise<ReactNode> {
  let body: { data: unknown };
  try {
    // A re-read right after an in-place write (lib/actions.ts) is not a screen view.
    const quiet = (await cookies()).has("bos_quiet");
    body = await apiGet<{ data: unknown }>(path, { screenView: !quiet });
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) {
      const here = (await headers()).get("x-pathname") ?? "/dashboard";
      redirect(`/login?next=${encodeURIComponent(here)}`);
    }
    if (err.status === 404) notFound();
    if (err.status === 403) return <Refused title="You do not have access to this" message={err.message} />;
    if (err.status === 501) {
      return <Refused title="Not converted yet" message="This screen's data endpoint does not answer the new front end yet." />;
    }
    throw err;
  }

  const parsed = schema.safeParse(body.data);
  if (!parsed.success) {
    console.error(`contract mismatch on ${path}`, parsed.error.issues.slice(0, 5));
    throw new Error(`The platform's answer for ${path} does not match its schema.`);
  }
  return render(parsed.data);
}
