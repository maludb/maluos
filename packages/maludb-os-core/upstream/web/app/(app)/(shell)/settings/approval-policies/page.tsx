import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { approvalPoliciesScreen } from "@/lib/schemas/approvals";

export const metadata: Metadata = { title: "Approval policies · Settings" };

/**
 * Screen `approval-policies-settings` — which actions need a person's yes, for whom, above what.
 * Data: GET /settings/approval-policies (insider; only a super-admin is offered the buttons).
 */
export default async function ApprovalPoliciesPage() {
  const here = await herePath();
  return renderScreen("/settings/approval-policies/", approvalPoliciesScreen, ({ policies, can }) => (
    <>
      <PageHeader title="Approval policies" id="approval-policies" crumbs={[{ label: "Settings", href: "/settings" }, { label: "Approval policies" }]}>
        <Link href="/approvals" id="approval-policies-queue-btn" className="btn btn-light-brand"><i className="feather-inbox me-2"></i><span>Approvals</span></Link>
        {can.edit && (
          <Link href={withBack("/settings/approval-policies/new", here)} id="approval-policies-add-btn" className="btn btn-primary"><i className="feather-plus me-2"></i><span>New policy</span></Link>
        )}
      </PageHeader>

      <div className="main-content" data-screen="approval-policies-settings">
        <div className="card stretch stretch-full" id="approval-policies-card">
          <div className="card-body p-0">
            <div className="table-responsive">
              <table className="table table-hover mb-0" id="approval-policies-table">
                <thead className="thead-light">
                  <tr><th>Policy</th><th>Action</th><th>Applies to</th><th>Above</th><th>Approver</th><th>On</th>{can.edit && <th className="text-end">Actions</th>}</tr>
                </thead>
                <tbody>
                  {policies.length === 0 ? (
                    <tr><td colSpan={can.edit ? 7 : 6} className="text-center text-muted py-5">No policies — nothing needs approval.</td></tr>
                  ) : policies.map((p) => (
                    <tr id={`approval-policy-row-${p.id}`} key={p.id} className={p.active ? "" : "text-muted"}>
                      <td>{p.id !== null ? <Link href={withBack(`/settings/approval-policies/${p.id}/edit`, here)} className="fw-semibold">{p.name}</Link> : <span className="fw-semibold">{p.name}</span>}<div className="fs-12 text-muted">{p.category_label}</div></td>
                      <td><code>{p.action_pattern}</code></td>
                      <td>{p.agent_member_id !== null ? <Link href={withBack(`/agents/${p.agent_member_id}`, here)}>{p.applies_to_label}</Link>
                         : p.department_id !== null ? <Link href={withBack(`/team/departments/${p.department_id}`, here)}>{p.applies_to_label}</Link> : p.applies_to_label}</td>
                      <td>{p.amount_threshold_display ?? "Any amount"}</td>
                      <td>{p.approver_member_id !== null ? <Link href={withBack(`/team/${p.approver_member_id}`, here)}>{p.approver_name ?? `#${p.approver_member_id}`}</Link> : p.approver_name ?? <span className="text-muted">Their manager</span>}</td>
                      <td>{p.active ? <span className="badge bg-soft-success text-success">On</span> : <span className="badge bg-soft-secondary text-secondary">Off</span>}</td>
                      {can.edit && (
                        <td className="text-end">
                          <span className="d-inline-flex gap-1 justify-content-end">
                            <Link href={withBack(`/settings/approval-policies/${p.id}/edit`, here)} className="btn btn-sm btn-light-brand">Edit</Link>
                            <ActionForm path="/settings/approval-policies/active.php" confirm={p.active ? `Switch off “${p.name}”? Those actions will stop needing approval.` : undefined}>
                              <input type="hidden" name="policy" value={p.id ?? ""} />
                              <input type="hidden" name="active" value={p.active ? "0" : "1"} />
                              <SubmitButton className="btn btn-sm btn-light-brand">{p.active ? "Switch off" : "Switch on"}</SubmitButton>
                            </ActionForm>
                            <ActionForm path="/settings/approval-policies/delete.php" confirm={`Delete “${p.name}”? Requests it caught keep their history.`}>
                              <input type="hidden" name="policy" value={p.id ?? ""} />
                              <SubmitButton className="btn btn-sm btn-light-brand text-danger">Delete</SubmitButton>
                            </ActionForm>
                          </span>
                        </td>
                      )}
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
