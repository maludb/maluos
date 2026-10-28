"use client";

import { useActionState } from "react";
import AuthOutcome from "../AuthOutcome";
import { registerAction, type AuthFlowState } from "../login/actions";

export default function RegisterForm({ token, email, initialError }: { token: string; email: string; initialError: string }) {
  const [state, action, pending] = useActionState<AuthFlowState, FormData>(registerAction, { error: initialError, errors: [], notice: "" });
  return (
    <>
      <AuthOutcome state={state} prefix="register" />
      <form action={action} className="w-100 mt-4 pt-2" id="register-form">
        <input type="hidden" name="token" value={token} />
        <div className="mb-3">
          <input type="text" name="display_name" id="register-field-name" className="form-control" placeholder="Display name"
                 defaultValue={state.displayName ?? ""} required autoFocus />
        </div>
        <div className="mb-3">
          {/* An invited address arrives with a live invitation token and cannot be changed, as in PHP. */}
          <input type="email" name="email" id="register-field-email" className="form-control" placeholder="Invited email"
                 defaultValue={email !== "" ? email : state.email ?? ""} readOnly={email !== ""} required />
        </div>
        <div className="mb-3">
          <input type="password" name="password" id="register-field-password" className="form-control"
                 placeholder="Password (min 12 characters)" required />
        </div>
        <div className="mb-3">
          <input type="password" name="password_confirm" id="register-field-password-confirm" className="form-control"
                 placeholder="Confirm password" required />
        </div>
        <div className="mt-4">
          <button type="submit" id="register-submit-btn" className="btn btn-lg btn-primary w-100" disabled={pending}>
            {pending ? "Creating…" : "Create account"}
          </button>
        </div>
      </form>
    </>
  );
}
