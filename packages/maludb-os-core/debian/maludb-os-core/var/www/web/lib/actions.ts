"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, apiPost } from "./api";
import { afterSave } from "./routes";

/**
 * The one server action behind every form that posts to a PHP write handler. PHP remains the
 * authority — gate, CSRF, validation, approval policy, log_activity() — and this only carries
 * the form there with the visitor's session and brings the answer back. Because handlers
 * answer JSON with no edit (json_mode_finish() in app/http.php), no handler needs an action of
 * its own.
 */
export type ActionState =
  | { status: "idle" }
  | { status: "ok"; message: string | null }
  | { status: "invalid"; message: string; errors: string[]; fields: Record<string, string> }
  | { status: "pending_approval"; message: string }
  | { status: "error"; message: string };

export type ActionTarget = {
  /** The handler's path, e.g. "/contacts/organizations/save.php". */
  path: string;
  /** Navigate to where PHP says the record now lives (saves, deletes); otherwise stay put. */
  follow: boolean;
  /** The page the form was opened from (click-around, R5): after a save the record keeps that trail. */
  back?: string | null;
};

// Only a PHP handler under html/, never /api/ and never a traversal. The visitor could post to
// any of these themselves with their own session — this keeps the action from being aimed at
// anything else.
const HANDLER = /^\/(?!api\/)[a-z0-9_-]+(\/[a-z0-9_-]+)*\.php$/;

const QUIET_COOKIE = "bos_quiet";

type SavedAnswer = { ok: boolean; did?: string; location?: string; status?: string; message?: string };

export async function submitToPlatform(target: ActionTarget, _prev: ActionState, formData: FormData): Promise<ActionState> {
  if (!HANDLER.test(target.path)) return { status: "error", message: "That is not something this form can do." };

  let answer: SavedAnswer;
  try {
    answer = await apiPost<SavedAnswer>(target.path, formData);
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    if (err.status === 422) return { status: "invalid", message: err.message, errors: err.errors.length ? err.errors : [err.message], fields: err.fields };
    return { status: "error", message: err.message };
  }

  if (answer.status === "pending_approval") {
    return { status: "pending_approval", message: answer.message ?? "This needs approval first. Nothing was changed." };
  }
  if (target.follow && answer.location) redirect(afterSave(webPath(answer.location), target.back));

  // The page now re-reads its data to show the change. That re-read is not somebody opening
  // the screen, so it must not be logged as a screen view: mark the next few seconds quiet
  // (renderScreen() honours it). HTMX swapped a partial here and logged nothing either.
  (await cookies()).set(QUIET_COOKIE, "1", { maxAge: 3, httpOnly: true, sameSite: "lax", path: "/" });
  return { status: "ok", message: answer.did ?? null };
}

/** A PHP canonical URL as this app routes it: no trailing slash, local paths only. */
function webPath(location: string): string {
  if (!location.startsWith("/") || location.startsWith("//")) return "/dashboard";
  const [path, query] = location.split("?", 2);
  const trimmed = path.length > 1 ? path.replace(/\/+$/, "") : path;
  return query ? `${trimmed}?${query}` : trimmed;
}

/**
 * Mark the next few seconds quiet, so a timed re-read of a screen (AutoRefresh) is not logged as
 * somebody opening it. HTMX's `every 60s` poll fetched a fragment and logged nothing either.
 */
export async function markQuiet(): Promise<void> {
  (await cookies()).set(QUIET_COOKIE, "1", { maxAge: 3, httpOnly: true, sameSite: "lax", path: "/" });
}
