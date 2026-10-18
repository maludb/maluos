"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, apiPost } from "@/lib/api";

/**
 * The four Settings writes that hand back a ONE-TIME SECRET (owner's decision 3, 2026-09-19):
 * a new API token, the TOTP secret + QR, the recovery codes. PHP puts the
 * secret in its own field of the JSON answer — never in `did`, which is logged. This action
 * returns it to the component that asked, which keeps it in component state only: it is never
 * written to a URL, a cookie, storage or a log, and it is gone when the page is left.
 * lib/actions.ts cannot do this — its ActionState carries one sentence — and must not learn to.
 */
export type SecretAnswer =
  | { status: "error"; message: string; expired?: boolean }
  | { status: "ok"; token?: string; enrolling?: boolean; qrDataUri?: string; manualKey?: string; recoveryCodes?: string[] };

const PATHS = {
  createToken: "/settings/tokens/create.php",
  enroll2fa: "/settings/2fa/enroll.php",
  enable2fa: "/settings/2fa/enable.php",
} as const;

export async function settingsSecret(kind: keyof typeof PATHS, fields: Record<string, string>): Promise<SecretAnswer> {
  let answer: { token?: string; enrolling?: boolean; qr_data_uri?: string; manual_key?: string; recovery_codes?: string[] };
  try {
    answer = await apiPost(PATHS[kind], fields);
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    return { status: "error", message: err.message, expired: err.code === "enrollment_expired" };
  }
  // The page re-reads itself to show the new token row / the enabled badge; that is not a screen view.
  (await cookies()).set("bos_quiet", "1", { maxAge: 3, httpOnly: true, sameSite: "lax", path: "/" });
  return {
    status: "ok", token: answer.token, enrolling: answer.enrolling,
    qrDataUri: answer.qr_data_uri, manualKey: answer.manual_key, recoveryCodes: answer.recovery_codes,
  };
}
