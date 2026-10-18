import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getSession, safeNext } from "@/lib/api";
import LoginForm from "./LoginForm";

export const metadata: Metadata = { title: "Login" };

/** Screen `login` — markup from app/views/auth/login.php. */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; registered?: string; error?: string }>;
}) {
  const params = await searchParams;
  const next = safeNext(params.next);
  const session = await getSession();
  if (session.authenticated) redirect(next);

  return (
    <>
      <h2 className="fs-20 fw-bolder mb-4">Login</h2>
      <h4 className="fs-13 fw-bold mb-2">Login to your account</h4>
      <p className="fs-12 fw-medium text-muted">
        {session.business.name} is invite-only. Use the account you registered with your invitation.
      </p>
      {params.registered && (
        <div className="alert alert-success py-2" id="login-notice">Account created — please log in.</div>
      )}
      {/* The Google callback's one sentence (web/app/auth/google/callback) — the same words PHP's
          login page printed, whatever the reason was. */}
      {params.error === "google" && (
        <div className="alert alert-danger py-2" id="login-google-error" role="alert">We could not sign you in with Google.</div>
      )}
      <LoginForm next={next} />
      {session.google_enabled && (
        <div className="w-100 mt-5 text-center mx-auto">
          <div className="mb-4 border-bottom position-relative">
            <span className="small py-1 px-3 text-uppercase text-muted bg-white position-absolute translate-middle">or</span>
          </div>
          <a href={`/auth/google/start?next=${encodeURIComponent(next)}`} id="auth-login-google-btn"
             className="btn btn-light-brand w-100">
            <i className="feather-log-in me-2"></i>Sign in with Google
          </a>
        </div>
      )}
      <div className="mt-5 text-muted">
        <span>Have an invitation?</span>{" "}
        <a href="/register" className="fw-bold">Create your account</a>
      </div>
    </>
  );
}
