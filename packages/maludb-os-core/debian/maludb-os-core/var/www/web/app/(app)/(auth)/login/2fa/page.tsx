import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getSession, safeNext } from "@/lib/api";
import TwoFactorForm from "./TwoFactorForm";

export const metadata: Metadata = { title: "Two-factor" };

/** Screen `login-2fa`. Reachable only while PHP holds a pending-2FA state for this session. */
export default async function TwoFactorPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const next = safeNext((await searchParams).next);
  const session = await getSession();
  if (session.authenticated) redirect(next);
  if (!session.two_factor_pending) redirect("/login");

  return (
    <>
      <h2 className="fs-20 fw-bolder mb-4">Two-factor</h2>
      <h4 className="fs-13 fw-bold mb-2">Enter your authentication code</h4>
      <p className="fs-12 fw-medium text-muted">
        Open your authenticator app and enter the 6-digit code, or use a recovery code.
      </p>
      <TwoFactorForm next={next} />
    </>
  );
}
