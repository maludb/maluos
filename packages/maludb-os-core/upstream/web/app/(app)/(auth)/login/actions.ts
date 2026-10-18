"use server";

import { redirect } from "next/navigation";
import { ApiError, apiPost, safeNext } from "@/lib/api";

export type AuthFormState = { error: string; email?: string };

/** POST /login.php. PHP owns the rules (lockout, timing-equalised verify, 2FA gate, logging). */
export async function loginAction(_prev: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const email = String(formData.get("email") ?? "");
  const next = safeNext(String(formData.get("next") ?? "/"));

  let result: { ok: true; location?: string; two_factor_required?: boolean };
  try {
    result = await apiPost("/login.php", { email, password: String(formData.get("password") ?? ""), next });
  } catch (err) {
    if (err instanceof ApiError) return { error: err.message, email };
    throw err;
  }
  // redirect() throws by design, so it stays outside the try.
  if (result.two_factor_required) redirect(`/login/2fa?next=${encodeURIComponent(next)}`);
  redirect(next);
}

/** POST /login/2fa.php — guarded in PHP by the pending-2FA state, which expires in 10 minutes. */
export async function twoFactorAction(_prev: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const next = safeNext(String(formData.get("next") ?? "/"));
  try {
    await apiPost("/login/2fa.php", { code: String(formData.get("code") ?? ""), next });
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === "two_factor_expired") redirect("/login");
      return { error: err.message };
    }
    throw err;
  }
  redirect(next);
}

/** POST /logout.php (POST + CSRF in PHP — a GET logout is a CSRF vector). */
export async function logoutAction(): Promise<void> {
  try {
    await apiPost("/logout.php");
  } catch (err) {
    // Already signed out is still signed out.
    if (!(err instanceof ApiError && err.status === 401)) throw err;
  }
  redirect("/login");
}

// ---- register / forgot / reset (owner's decision 1, 2026-09-19) -----------------------------
// PHP owns every rule here too: the invitation is the authority for registering, forgot answers
// ONE sentence whether or not the account exists, and a reset token is single-use and expiring.

export type AuthFlowState = { error: string; errors: string[]; notice: string; displayName?: string; email?: string };
const blank: AuthFlowState = { error: "", errors: [], notice: "" };

function refused(err: ApiError, keep: Partial<AuthFlowState> = {}): AuthFlowState {
  return err.errors.length > 0 ? { ...blank, ...keep, errors: err.errors } : { ...blank, ...keep, error: err.message };
}

/** POST /register.php. On success PHP has established the session; the cookie is relayed by apiPost. */
export async function registerAction(_prev: AuthFlowState, formData: FormData): Promise<AuthFlowState> {
  const displayName = String(formData.get("display_name") ?? "");
  const email = String(formData.get("email") ?? "");
  try {
    await apiPost("/register.php", {
      token: String(formData.get("token") ?? ""), display_name: displayName, email,
      password: String(formData.get("password") ?? ""), password_confirm: String(formData.get("password_confirm") ?? ""),
    });
  } catch (err) {
    if (err instanceof ApiError) return refused(err, { displayName, email });
    throw err;
  }
  redirect("/");
}

/** POST /forgot.php. The answer is the same sentence either way — never branch on it here. */
export async function forgotAction(_prev: AuthFlowState, formData: FormData): Promise<AuthFlowState> {
  try {
    const answer = await apiPost<{ ok: true; notice: string }>("/forgot.php", { email: String(formData.get("email") ?? "") });
    return { ...blank, notice: answer.notice };
  } catch (err) {
    if (err instanceof ApiError) return refused(err);
    throw err;
  }
}

/** POST /reset.php. On success the visitor signs in with the new password. */
export async function resetAction(_prev: AuthFlowState, formData: FormData): Promise<AuthFlowState> {
  try {
    await apiPost("/reset.php", {
      token: String(formData.get("token") ?? ""),
      password: String(formData.get("password") ?? ""), password_confirm: String(formData.get("password_confirm") ?? ""),
    });
  } catch (err) {
    if (err instanceof ApiError) return refused(err);
    throw err;
  }
  redirect("/login");
}
