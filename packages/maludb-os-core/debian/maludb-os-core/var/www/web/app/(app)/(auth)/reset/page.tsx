import type { Metadata } from "next";
import { ApiError, apiGet } from "@/lib/api";
import ResetForm from "./ResetForm";

export const metadata: Metadata = { title: "Reset password" };
// The token is in the URL: keep this page out of every cache and out of the Referer header.
export const dynamic = "force-dynamic";

/**
 * Screen `reset` — markup from app/views/auth/reset.php. Data: GET /reset.php?token=, which says
 * only whether the link still works. As in PHP, a dead link keeps the form but empties the token,
 * so nothing typed into it can succeed.
 */
export default async function ResetPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  let valid = false;
  let error = "This reset link is invalid or has expired.";
  try {
    const answer = await apiGet<{ data: { valid: boolean; error: string | null } }>(`/reset.php?token=${encodeURIComponent(token)}`);
    valid = answer.data.valid;
    error = answer.data.error ?? "";
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    error = err.message;
  }

  return (
    <>
      <meta name="referrer" content="no-referrer" />
      <h2 className="fs-20 fw-bolder mb-4">Reset password</h2>
      <h4 className="fs-13 fw-bold mb-2">Choose a new password</h4>
      <ResetForm token={valid ? token : ""} initialError={valid ? "" : error} />
      <div className="mt-4 text-muted"><a href="/login" className="fw-bold">Back to login</a></div>
    </>
  );
}
