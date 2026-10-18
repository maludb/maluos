"use server";

import { redirect } from "next/navigation";
import { ApiError, apiPost } from "@/lib/api";
import type { JevCheck } from "@/lib/schemas/aiops";

/**
 * `eval_case_draft_checks` (db/144): a draft of JEV checks from a rubric, returned to the case form to
 * edit — nothing is saved. lib/actions.ts carries one sentence back; this carries the draft.
 */
export async function draftJevChecks(rubric: string, evalCase: number | null): Promise<{ checks?: JevCheck[]; error?: string }> {
  try {
    const answer = await apiPost<{ checks?: JevCheck[] }>("/ai/evals/draft-checks.php",
      { rubric, ...(evalCase !== null ? { eval_case: String(evalCase) } : {}) });
    return { checks: answer.checks ?? [] };
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) redirect("/login");
    return { error: err.message };
  }
}
