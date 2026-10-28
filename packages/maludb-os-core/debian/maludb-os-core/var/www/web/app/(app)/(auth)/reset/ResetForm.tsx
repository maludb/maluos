"use client";

import { useActionState } from "react";
import AuthOutcome from "../AuthOutcome";
import { resetAction, type AuthFlowState } from "../login/actions";

export default function ResetForm({ token, initialError }: { token: string; initialError: string }) {
  const [state, action, pending] = useActionState<AuthFlowState, FormData>(resetAction, { error: initialError, errors: [], notice: "" });
  return (
    <>
      <AuthOutcome state={state} prefix="reset" />
      <form action={action} className="w-100 mt-4 pt-2" id="reset-form">
        <input type="hidden" name="token" value={token} />
        <div className="mb-3">
          <input type="password" name="password" id="reset-field-password" className="form-control"
                 placeholder="New password (min 12 characters)" required autoFocus />
        </div>
        <div className="mb-3">
          <input type="password" name="password_confirm" id="reset-field-password-confirm" className="form-control"
                 placeholder="Confirm new password" required />
        </div>
        <div className="mt-4">
          <button type="submit" id="reset-submit-btn" className="btn btn-lg btn-primary w-100" disabled={pending}>
            {pending ? "Saving…" : "Set new password"}
          </button>
        </div>
      </form>
    </>
  );
}
