"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import { mintApplicationToken, type TokenAnswer } from "./tokenActions";

/**
 * The application's own token for the kernel's directory, ledger and chat endpoints (A4): minted
 * here by a super-admin, shown once, written into the application's config/.env as
 * OS_APPLICATION_TOKEN by the installation agent or by hand.
 */
/** A server page may not hand a function to a client component, so the date format lives here. */
function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export default function ApplicationTokenCard({ applicationId, token }: {
  applicationId: number; token: { minted_at: string | null; last_used_at: string | null } | null;
}) {
  const router = useRouter();
  const [answer, setAnswer] = useState<TokenAnswer | null>(null);
  const [pending, startTransition] = useTransition();
  const mint = () => startTransition(async () => {
    const next = await mintApplicationToken(applicationId);
    setAnswer(next);
    if (next.status === "ok") router.refresh();
  });
  return (
    <div className="mt-4" id="application-view-token">
      <h6 className="fs-13 text-muted mb-2">Application token</h6>
      <p className="fs-12 text-muted">What the application presents to the kernel&apos;s directory, ledger and chat endpoints — <code>OS_APPLICATION_TOKEN</code> in its config. One live token; minting again replaces it.</p>
      {answer?.status === "error" && <div className="alert alert-danger py-2 fs-12" id="application-token-error">{answer.message}</div>}
      {answer?.status === "ok" && (
        <div className="alert alert-success fs-12" id="application-token-shown"><strong>Copy it now — it is shown once:</strong><br /><code className="user-select-all">{answer.token}</code></div>
      )}
      {token ? (
        <p className="fs-12 mb-2" id="application-token-status"><span className="badge bg-soft-success text-success">Live</span>
          <span className="text-muted ms-2">minted {formatDate(token.minted_at)}{token.last_used_at ? ` · last used ${formatDate(token.last_used_at)}` : " · never used"}</span></p>
      ) : (
        <p className="fs-12 text-muted mb-2" id="application-token-status">No token yet.</p>
      )}
      <div className="d-flex gap-2">
        <button type="button" className="btn btn-sm btn-primary" disabled={pending} onClick={mint} id="application-token-mint-btn">
          <i className="feather-key me-1"></i>{token ? "Rotate" : "Mint"}
        </button>
        {token && (
          <ActionForm path="/applications/token-revoke.php" confirm="Revoke the application token? The application can no longer read the directory until a new one is minted.">
            <input type="hidden" name="application" value={applicationId} />
            <SubmitButton className="btn btn-sm btn-outline-danger" id="application-token-revoke-btn">Revoke</SubmitButton>
          </ActionForm>
        )}
      </div>
    </div>
  );
}
