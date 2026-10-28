"use client";

import { useActionState } from "react";
import AuthOutcome from "../AuthOutcome";
import { forgotAction, type AuthFlowState } from "../login/actions";

export default function ForgotForm() {
  const [state, action, pending] = useActionState<AuthFlowState, FormData>(forgotAction, { error: "", errors: [], notice: "" });
  return (
    <>
      {state.notice !== "" && <div className="alert alert-success py-2" id="forgot-notice">{state.notice}</div>}
      <AuthOutcome state={state} prefix="forgot" />
      <form action={action} className="w-100 mt-4 pt-2" id="forgot-form">
        <div className="mb-3">
          <input type="email" name="email" id="forgot-field-email" className="form-control" placeholder="Email" required autoFocus />
        </div>
        <div className="mt-4">
          <button type="submit" id="forgot-submit-btn" className="btn btn-lg btn-primary w-100" disabled={pending}>
            {pending ? "Sending…" : "Send reset link"}
          </button>
        </div>
      </form>
    </>
  );
}
