"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, apiPost } from "@/lib/api";

/**
 * Minting an application's token (A4) hands back a ONE-TIME SECRET, like a personal token: PHP
 * puts it in its own field of the answer, never in `did`. It reaches the card that asked and lives
 * in component state only — never a URL, a cookie, storage or a log.
 */
export type TokenAnswer = { status: "error"; message: string } | { status: "ok"; token: string };

export async function mintApplicationToken(applicationId: number): Promise<TokenAnswer> {
  let answer: { token?: string };
  try {
    answer = await apiPost("/applications/token-mint.php", { application: String(applicationId) });
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    return { status: "error", message: err.message };
  }
  (await cookies()).set("bos_quiet", "1", { maxAge: 3, httpOnly: true, sameSite: "lax", path: "/" });
  return answer.token ? { status: "ok", token: answer.token } : { status: "error", message: "The platform gave no token." };
}
