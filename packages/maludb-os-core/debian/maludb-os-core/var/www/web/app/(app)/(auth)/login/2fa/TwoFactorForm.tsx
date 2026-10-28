"use client";

import { useActionState } from "react";
import { twoFactorAction, type AuthFormState } from "../actions";

export default function TwoFactorForm({ next }: { next: string }) {
  const [state, action, pending] = useActionState<AuthFormState, FormData>(twoFactorAction, { error: "" });

  return (
    <>
      {state.error !== "" && (
        <div className="alert alert-danger py-2" id="twofa-error" role="alert">
          {state.error}
        </div>
      )}
      <form action={action} className="w-100 mt-4 pt-2" id="twofa-form">
        <input type="hidden" name="next" value={next} />
        <div className="mb-4">
          <input type="text" name="code" id="twofa-field-code" className="form-control" inputMode="numeric"
                 autoComplete="one-time-code" placeholder="123456" required autoFocus />
        </div>
        <div className="mt-5">
          <button type="submit" id="twofa-submit-btn" className="btn btn-lg btn-primary w-100" disabled={pending}>
            {pending ? "Checking…" : "Verify"}
          </button>
        </div>
      </form>
    </>
  );
}
