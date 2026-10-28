import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ApiError, apiGet, getSession } from "@/lib/api";
import RegisterForm from "./RegisterForm";

export const metadata: Metadata = { title: "Create account" };
// An invitation token is in the URL: keep this page out of every cache and out of the Referer header.
export const dynamic = "force-dynamic";

/**
 * Screen `register` (invite-only) — markup from app/views/auth/register.php. Data:
 * GET /register.php?token=, which prefills the invited address for the holder of a live
 * invitation and says so when the link is dead. Google sign-up is not offered from React yet
 * (owner's decision 1, 2026-09-19) — it is an OAuth redirect through the PHP host.
 */
export default async function RegisterPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  if ((await getSession()).authenticated) redirect("/");

  let invite = { token: "", email: "", error: null as string | null };
  try {
    invite = (await apiGet<{ data: typeof invite }>(`/register.php${token ? `?token=${encodeURIComponent(token)}` : ""}`)).data;
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    invite.error = err.message;
  }

  return (
    <>
      <meta name="referrer" content="no-referrer" />
      <h2 className="fs-20 fw-bolder mb-4">Create account</h2>
      <h4 className="fs-13 fw-bold mb-2">Accept your invitation</h4>
      <p className="fs-12 fw-medium text-muted">Registration requires a valid invitation for your email address.</p>
      <RegisterForm token={invite.token} email={invite.email} initialError={invite.error ?? ""} />
      <div className="mt-4 text-muted">
        <span>Already have an account?</span>{" "}
        <a href="/login" className="fw-bold">Login</a>
      </div>
    </>
  );
}
