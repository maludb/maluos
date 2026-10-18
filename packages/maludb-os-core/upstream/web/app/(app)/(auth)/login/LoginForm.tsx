"use client";

import { useActionState } from "react";
import { loginAction, type AuthFormState } from "./actions";

export default function LoginForm({ next }: { next: string }) {
  const [state, action, pending] = useActionState<AuthFormState, FormData>(loginAction, { error: "" });

  return (
    <>
      {state.error !== "" && (
        <div className="alert alert-danger py-2" id="login-error" role="alert">
          {state.error}
        </div>
      )}
      <form action={action} className="w-100 mt-4 pt-2" id="login-form">
        <input type="hidden" name="next" value={next} />
        <div className="mb-4">
          <input type="email" name="email" id="login-field-email" className="form-control"
                 placeholder="Email" defaultValue={state.email ?? ""} required autoFocus />
        </div>
        <div className="mb-3">
          <input type="password" name="password" id="login-field-password" className="form-control"
                 placeholder="Password" required />
        </div>
        <div className="d-flex align-items-center justify-content-end">
          <a href="/forgot" className="fs-11 text-primary">Forgot password?</a>
        </div>
        <div className="mt-5">
          <button type="submit" id="login-submit-btn" className="btn btn-lg btn-primary w-100" disabled={pending}>
            {pending ? "Signing in…" : "Login"}
          </button>
        </div>
      </form>
    </>
  );
}
