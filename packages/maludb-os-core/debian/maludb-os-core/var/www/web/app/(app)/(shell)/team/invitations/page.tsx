import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { invitationsScreen } from "@/lib/schemas/invitations";

export const metadata: Metadata = { title: "Invitations · People & access" };

/**
 * Screen `invitations` — invite people and manage the invitations still pending. Data:
 * GET /team/invitations (admin; a dept-admin sees and sends only into departments they
 * administer). The first screen built after the React cut-over: no PHP template exists for it.
 */
export default async function InvitationsPage() {
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();

  return renderScreen("/team/invitations", invitationsScreen, (data) => {
    const { invitations, options, can } = data;
    return (
      <>
        <PageHeader title="Invitations" id="invitations"
                    crumbs={[{ label: "HR", href: "/agents" }, { label: "People & access", href: "/team" }, { label: "Invitations" }]} />

        <div className="main-content" data-screen="invitations">
          <div className="row">
            <div className="col-lg-4">
              <div className="card stretch stretch-full" id="invitations-send-card">
                <div className="card-header"><h5 className="card-title">Invite someone</h5></div>
                <div className="card-body">
                  <ActionForm path="/team/invitations/save.php" id="invitation-send-form" resetOnSuccess>
                    <div className="mb-3">
                      <label className="form-label" htmlFor="invitation-form-field-email">Email</label>
                      <input type="email" name="email" id="invitation-form-field-email" className="form-control" required
                             maxLength={254} autoComplete="off" placeholder="name@example.com" />
                    </div>
                    <div className="mb-3">
                      <label className="form-label" htmlFor="invitation-form-field-business-role">They will be</label>
                      <select name="business_role" id="invitation-form-field-business-role" className="form-select" defaultValue="user">
                        {options.business_roles.map((r) => <option value={r.id} key={r.id}>{r.name}</option>)}
                      </select>
                    </div>
                    <div className="mb-3">
                      <label className="form-label" htmlFor="invitation-form-field-department">Department</label>
                      <select name="department" id="invitation-form-field-department" className="form-select"
                              defaultValue="" required={!can.invite_without_department}>
                        <option value="">{can.invite_without_department ? "No department yet" : "Choose a department…"}</option>
                        {options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
                      </select>
                      <div className="form-text">A department admin administers the department chosen here.</div>
                    </div>
                    <div className="mb-3">
                      <label className="form-label" htmlFor="invitation-form-field-message">A note for them <span className="text-muted">(optional)</span></label>
                      <textarea name="message" id="invitation-form-field-message" className="form-control" rows={3} maxLength={2000}></textarea>
                    </div>
                    <SubmitButton className="btn btn-primary" id="invitation-send-btn">
                      <i className="feather-send me-2"></i>Send invitation
                    </SubmitButton>
                    <p className="fs-12 text-muted mt-3 mb-0">
                      The link in the email lets them choose a password. It works for {data.ttl_days} days, once.
                    </p>
                  </ActionForm>
                </div>
              </div>
            </div>

            <div className="col-lg-8">
              <div className="card stretch stretch-full" id="invitations-pending-card">
                <div className="card-header"><h5 className="card-title">Pending</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="invitations-table">
                      <thead className="thead-light">
                        <tr><th>Email</th><th>As</th><th>Invited by</th><th>Sent</th><th>Expires</th><th className="text-end">Actions</th></tr>
                      </thead>
                      <tbody>
                        {invitations.length === 0 ? (
                          <tr><td colSpan={6} className="text-center text-muted py-5">Nobody is waiting on an invitation.</td></tr>
                        ) : (
                          invitations.map((i) => (
                            <tr id={`invitation-row-${i.id}`} key={i.id}>
                              <td>{i.email}</td>
                              <td className="text-muted">{i.business_role_label}</td>
                              <td className="text-muted"><Who who={{ id: i.invited_by_member_id, name: i.invited_by_name }} here={here} /></td>
                              <td className="text-muted">{formatTs(i.sent_at, timeZone, false)}</td>
                              <td>
                                {i.expired
                                  ? <span className="badge bg-soft-danger text-danger">Expired</span>
                                  : <span className="text-muted">{formatTs(i.expires_at, timeZone, false)}</span>}
                              </td>
                              <td className="text-end">
                                <span className="d-inline-flex gap-1 justify-content-end">
                                  <ActionForm path="/team/invitations/resend.php">
                                    <input type="hidden" name="invitation" value={i.id} />
                                    <SubmitButton className="btn btn-sm btn-light-brand">Resend</SubmitButton>
                                  </ActionForm>
                                  <ActionForm path="/team/invitations/revoke.php" confirm={`Revoke the invitation to ${i.email}? Their link stops working.`}>
                                    <input type="hidden" name="invitation" value={i.id} />
                                    <SubmitButton className="btn btn-sm btn-light-brand text-danger">Revoke</SubmitButton>
                                  </ActionForm>
                                </span>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
