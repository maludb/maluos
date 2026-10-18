import type { Metadata } from "next";
import ForgotForm from "./ForgotForm";

export const metadata: Metadata = { title: "Reset password" };

/** Screen `forgot` — markup from app/views/auth/forgot.php. The form needs nothing from PHP to render. */
export default function ForgotPage() {
  return (
    <>
      <h2 className="fs-20 fw-bolder mb-4">Reset password</h2>
      <h4 className="fs-13 fw-bold mb-2">Forgot your password?</h4>
      <p className="fs-12 fw-medium text-muted">Enter your email and we&rsquo;ll send a reset link if an account exists.</p>
      <ForgotForm />
      <div className="mt-4 text-muted"><a href="/login" className="fw-bold">Back to login</a></div>
    </>
  );
}
