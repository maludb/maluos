import { headers } from "next/headers";

/**
 * The request's own path and query — what the middleware stamps as x-pathname — for a server page
 * to hand to withBack() (lib/routes.ts) on every link that leaves it. Server components only.
 */
export async function herePath(): Promise<string | null> {
  return (await headers()).get("x-pathname");
}
