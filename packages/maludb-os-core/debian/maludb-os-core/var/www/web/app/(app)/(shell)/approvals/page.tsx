import type { Metadata } from "next";
import ApprovalStatusBadge from "@/components/approvals/StatusBadge";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { approvalsQueue } from "@/lib/schemas/approvals";

export const metadata: Metadata = { title: "Approvals" };

const STATUSES = ["pending", "approved", "executed", "execution_failed", "rejected", "cancelled", "expired"];

/**
 * Screen `approvals` — what waits for the caller's approval, or what they asked for.
 * Data: GET /approvals/?role=&status= (signed in; the rows are the caller's own).
 */
export default async function ApprovalsPage({ searchParams }: { searchParams: Promise<{ role?: string; status?: string }> }) {
  const sp = await searchParams;
  const role = sp.role === "requester" ? "requester" : "approver";
  const status = sp.status && STATUSES.includes(sp.status) ? sp.status : "";
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const query = new URLSearchParams({ role, ...(status ? { status } : {}) });

  const here = await herePath();
  return renderScreen(`/approvals/?${query}`, approvalsQueue, (data) => (
    <>
      <PageHeader title="Approvals" id="approvals" crumbs={[{ label: "Approvals" }]}>
        <Link href="/settings/approval-policies" id="approvals-policies-btn" className="btn btn-light-brand">
          <i className="feather-shield me-2"></i><span>Policies</span>
        </Link>
      </PageHeader>

      <div className="main-content" data-screen="approvals">
        <div className="card stretch stretch-full" id="approvals-card">
          <div className="card-header d-flex flex-wrap gap-2 align-items-center">
            <ul className="nav nav-pills" id="approvals-role-tabs">
              <li className="nav-item"><Link className={`nav-link${role === "approver" ? " active" : ""}`} href={`/approvals?role=approver${status ? `&status=${encodeURIComponent(status)}` : ""}`} id="approvals-tab-approver">Waiting for me</Link></li>
              <li className="nav-item"><Link className={`nav-link${role === "requester" ? " active" : ""}`} href={`/approvals?role=requester${status ? `&status=${encodeURIComponent(status)}` : ""}`} id="approvals-tab-requester">Asked by me</Link></li>
            </ul>
            <div className="ms-auto">
              <FilterSelect id="approvals-filter-status" name="status" value={status}
                            options={[{ value: "", label: "Any status" }, ...STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") }))]} />
            </div>
          </div>
          <div className="card-body p-0">
            <div className="table-responsive">
              <table className="table table-hover mb-0" id="approvals-table">
                <thead className="thead-light">
                  <tr><th>What</th><th>{role === "approver" ? "Asked by" : "Approver"}</th><th className="text-end">Amount</th><th>Asked</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {data.requests.length === 0 ? (
                    <tr><td colSpan={5} className="text-center text-muted py-5">
                      {role === "approver" ? "Nothing is waiting for your approval." : "You have not asked for any approval."}
                    </td></tr>
                  ) : data.requests.map((r) => (
                    <tr id={`approval-row-${r.approval_request_id}`} key={r.approval_request_id}>
                      {/* The theme sets every cell nowrap; the summary is a sentence and must wrap. */}
                      <td className="text-wrap" style={{ minWidth: "16rem" }}>
                        <Link href={withBack(`/approvals/${r.approval_request_id}`, here)} className="fw-semibold">{r.summary}</Link>
                        <div className="fs-12 text-muted">{r.action_key}{r.policy ? <> · {r.policy_id !== null ? <Link href={withBack(`/settings/approval-policies/${r.policy_id}/edit`, here)}>{r.policy}</Link> : r.policy}</> : ""}
                          {r.agent_run_id !== null && <> · <Link href={withBack(`/ai/runs/${r.agent_run_id}`, here)}>run #{r.agent_run_id}</Link></>}</div>
                      </td>
                      <td>
                        {role === "approver" ? <Who who={{ id: r.requested_by.member_id, name: r.requested_by.name, kind: r.requested_by.kind }} here={here} />
                                            : <Who who={{ id: r.approver.member_id, name: r.approver.name, kind: r.approver.kind }} here={here} />}
                        {role === "approver" && r.requested_by.kind === "agent" && <span className="badge bg-soft-primary text-primary ms-1">Agent</span>}
                      </td>
                      <td className="text-end">{r.amount !== null ? `${r.amount} ${r.currency ?? ""}` : "—"}</td>
                      <td className="text-muted">{formatTs(r.created_at, timeZone, false)}</td>
                      <td><ApprovalStatusBadge status={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
