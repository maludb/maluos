import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ApprovalStatusBadge from "@/components/approvals/StatusBadge";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";
import { approvalView } from "@/lib/schemas/approvals";

export const metadata: Metadata = { title: "Approval request" };

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/**
 * Screen `approval-view` — one request and what the caller may do about it. Data:
 * GET /approvals/{id} (visible through mcp_approval_requests, else 404). Who may decide or
 * withdraw is PHP's answer (`can`), and the handlers check it again.
 */
export default async function ApprovalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/approvals/${id}`, approvalView, ({ request: r, can }) => {
    const parameters = Object.entries(r.parameters);
    return (
      <>
        <PageHeader title={r.summary} id="approval-view" crumbs={[{ label: "Approvals", href: "/approvals" }, { label: `#${r.approval_request_id}` }]} back={{ href: "/approvals", label: "Approvals" }} />

        <div className="main-content" data-screen="approval-view" data-entity="approval_request" data-record-id={r.approval_request_id}>
          <div className="row">
            <div className="col-lg-7">
              <div className="card" id="approval-view-request-card">
                <div className="card-header d-flex align-items-center gap-2">
                  <h5 className="card-title mb-0">The request</h5>
                  <span className="ms-auto"><ApprovalStatusBadge status={r.status} /></span>
                </div>
                <div className="card-body">
                  <dl className="row mb-0">
                    <dt className="col-sm-4 text-muted fs-12">Action</dt><dd className="col-sm-8"><code>{r.action_key}</code></dd>
                    <dt className="col-sm-4 text-muted fs-12">Asked by</dt>
                    <dd className="col-sm-8">
                      <Who who={{ id: r.requested_by.member_id, name: r.requested_by.name, kind: r.requested_by.kind }} here={here} />
                      {r.requested_by.kind === "agent" && <span className="badge bg-soft-primary text-primary ms-1">Agent</span>}
                    </dd>
                    <dt className="col-sm-4 text-muted fs-12">Approver</dt><dd className="col-sm-8"><Who who={{ id: r.approver.member_id, name: r.approver.name, kind: r.approver.kind }} here={here} /></dd>
                    {r.amount !== null && (<><dt className="col-sm-4 text-muted fs-12">Amount</dt><dd className="col-sm-8">{r.amount} {r.currency}</dd></>)}
                    {r.policy && (<><dt className="col-sm-4 text-muted fs-12">Caught by</dt><dd className="col-sm-8">{r.policy_id !== null ? <Link href={withBack(`/settings/approval-policies/${r.policy_id}/edit`, here)}>{r.policy}</Link> : r.policy}</dd></>)}
                    <dt className="col-sm-4 text-muted fs-12">Asked</dt><dd className="col-sm-8">{formatTs(r.created_at, timeZone)}</dd>
                    {r.status === "pending" && (<><dt className="col-sm-4 text-muted fs-12">Expires</dt><dd className="col-sm-8">{formatTs(r.expires_at, timeZone)}</dd></>)}
                    {r.decided_at && (<><dt className="col-sm-4 text-muted fs-12">Decided</dt><dd className="col-sm-8">{formatTs(r.decided_at, timeZone)}</dd></>)}
                    {r.decision_note && (<><dt className="col-sm-4 text-muted fs-12">Note</dt><dd className="col-sm-8">{r.decision_note}</dd></>)}
                    {r.executed_at && (<><dt className="col-sm-4 text-muted fs-12">Carried out</dt><dd className="col-sm-8">{formatTs(r.executed_at, timeZone)}</dd></>)}
                  </dl>
                  {r.execution_error && (
                    <div className="alert alert-danger mt-3 mb-0" id="approval-view-execution-error" role="alert">
                      It was approved, but the action then failed: {r.execution_error}
                    </div>
                  )}
                </div>
              </div>

              <div className="card" id="approval-view-parameters-card">
                <div className="card-header"><h5 className="card-title">What would be done</h5></div>
                <div className="card-body p-0">
                  <table className="table mb-0" id="approval-view-parameters">
                    <tbody>
                      {parameters.length === 0 ? (
                        <tr><td className="text-muted text-center py-4">No parameters.</td></tr>
                      ) : parameters.map(([key, value]) => (
                        <tr key={key}><th className="text-muted fw-normal fs-12" style={{ width: "35%" }}>{key}</th><td className="text-wrap text-break">{show(value)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="col-lg-5">
              {can.decide && (
                <>
                  <div className="card" id="approval-view-approve-card">
                    <div className="card-header"><h5 className="card-title">Approve</h5></div>
                    <div className="card-body">
                      <ActionForm path="/approvals/approve.php" confirm="Approve this? The action is carried out straight away.">
                        <input type="hidden" name="approval_request" value={r.approval_request_id} />
                        <label className="form-label" htmlFor="approval-form-field-note">A note <span className="text-muted">(optional)</span></label>
                        <textarea name="note" id="approval-form-field-note" className="form-control mb-3" rows={2} maxLength={1000}></textarea>
                        <SubmitButton className="btn btn-success" id="approval-approve-btn"><i className="feather-check me-2"></i>Approve and carry out</SubmitButton>
                      </ActionForm>
                    </div>
                  </div>
                  <div className="card" id="approval-view-reject-card">
                    <div className="card-header"><h5 className="card-title">Reject</h5></div>
                    <div className="card-body">
                      <ActionForm path="/approvals/reject.php">
                        <input type="hidden" name="approval_request" value={r.approval_request_id} />
                        <label className="form-label" htmlFor="approval-form-field-reason">Why — the requester reads this</label>
                        <textarea name="reason" id="approval-form-field-reason" className="form-control mb-3" rows={2} maxLength={1000} required></textarea>
                        <SubmitButton className="btn btn-light-brand text-danger" id="approval-reject-btn">Reject</SubmitButton>
                      </ActionForm>
                    </div>
                  </div>
                </>
              )}
              {can.cancel && (
                <div className="card" id="approval-view-cancel-card">
                  <div className="card-header"><h5 className="card-title">Withdraw</h5></div>
                  <div className="card-body">
                    <p className="text-muted fs-12">Nothing is done, and the approver is no longer asked.</p>
                    <ActionForm path="/approvals/cancel.php" confirm="Withdraw this request?">
                      <input type="hidden" name="approval_request" value={r.approval_request_id} />
                      <SubmitButton className="btn btn-light-brand" id="approval-cancel-btn">Withdraw the request</SubmitButton>
                    </ActionForm>
                  </div>
                </div>
              )}
              {(r.agent_run_id !== null || r.entity_type !== null) && (
                <div className="card" id="approval-view-run-card">
                  <div className="card-body d-flex flex-column gap-1">
                    {r.agent_run_id !== null && <div>
                      <span className="text-muted fs-12">Behind this request: </span>
                      <Link href={withBack(`/ai/runs/${r.agent_run_id}`, here)}>agent run #{r.agent_run_id}</Link>
                    </div>}
                    {r.entity_type !== null && <div id="approval-view-entity">
                      <span className="text-muted fs-12">About: </span>
                      {(() => { const label = `${r.entity_type}${r.entity_id !== null ? ` #${r.entity_id}` : ""}`; const href = recordHref(r.entity_type, r.entity_id); return href ? <Link href={withBack(href, here)}>{label}</Link> : label; })()}
                    </div>}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </>
    );
  });
}
