import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import MemberApplicationAccess from "@/components/team/MemberApplicationAccess";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { isSafeBack, withBack } from "@/lib/routes";
import { memberAccess } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "Access" };

const ROLES: [string, string][] = [["user", "User"], ["dept_admin", "Dept-admin"], ["super_admin", "Super-admin"]];

/**
 * Screen `member-edit` — role, departments, application access and (where the member can reach
 * the OS screens) module grants. Data: GET /team/{id}/edit
 * (admin + can_admin_member). Every control is its own small write; there is no Save — "Done"
 * leaves. The left column stacks two cards, so they are plain `.card`.
 */
export default async function MemberAccessPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();

  const here = await herePath();
  return renderScreen(`/team/${id}/edit`, memberAccess, (data) => {
    const { member: m, departments, modules, options, can, timezones } = data;
    const mine = new Set(departments.map((d) => d.id));
    return (
      <>
        <PageHeader title={can.update ? m.display_name : `Access · ${m.display_name}`} id="member-edit"
                    crumbs={[{ label: m.kind === "human" ? "Human Workforce" : "People", href: m.kind === "human" ? "/team?kind=human" : "/team" }, { label: m.display_name, href: `/team/${m.id}` }, { label: "Edit" }]}
                    back={{ href: `/team/${m.id}`, label: "the person" }}>
          <Link href={back ?? `/team/${m.id}`} id="member-edit-done-btn" className="btn btn-light-brand">Done</Link>
        </PageHeader>

        <div className="main-content" data-screen="member-edit">
          <div className="row">
            <div className="col-lg-5">
              {can.update && (
                <div className="card" id="member-edit-details-card">
                  <div className="card-header"><h5 className="card-title">Details</h5></div>
                  <div className="card-body">
                    <ActionForm path="/team/update.php" id="member-edit-details-form">
                      <input type="hidden" name="member" value={m.id} />
                      <div className="mb-3">
                        <label className="form-label fs-12" htmlFor="member-form-field-display_name">Name</label>
                        <input type="text" className="form-control" id="member-form-field-display_name" name="display_name"
                               defaultValue={m.display_name} maxLength={120} required />
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-12" htmlFor="member-form-field-job_title">Job title</label>
                        <input type="text" className="form-control" id="member-form-field-job_title" name="job_title"
                               defaultValue={m.job_title ?? ""} maxLength={120} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-12" htmlFor="member-form-field-phone">Phone</label>
                        <input type="tel" className="form-control" id="member-form-field-phone" name="phone"
                               defaultValue={m.phone ?? ""} maxLength={40} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label fs-12" htmlFor="member-form-field-timezone">Time zone</label>
                        <select className="form-select" id="member-form-field-timezone" name="timezone" defaultValue={m.timezone ?? "UTC"}>
                          {timezones.map((tz) => <option value={tz} key={tz}>{tz}</option>)}
                        </select>
                      </div>
                      <div className="form-text mb-2">Their email ({m.email ?? "none"}) is how they sign in; they change it themselves.</div>
                      <SubmitButton className="btn btn-primary" id="member-edit-details-save">Save details</SubmitButton>
                    </ActionForm>
                  </div>
                </div>
              )}
              <div className="card" id="member-edit-role-card">
                <div className="card-header"><h5 className="card-title">Role</h5></div>
                <div className="card-body">
                  {can.set_role ? (
                    <ActionForm path="/team/role.php" id="member-edit-role-form" confirm="Change this member's role?">
                      <input type="hidden" name="member" value={m.id} />
                      <div className="row mb-3">
                        <label className="col-lg-4 col-form-label" htmlFor="member-form-field-role">Business role</label>
                        <div className="col-lg-8">
                          <select name="business_role" id="member-form-field-role" className="form-select"
                                  defaultValue={m.business_role} key={m.business_role}>
                            {ROLES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                          </select>
                          <div className="form-text">
                            A dept-admin administers only the departments they are flagged admin of, or manage.
                            Everywhere else they are an ordinary user. Agents are always users.
                          </div>
                        </div>
                      </div>
                      <SubmitButton className="btn btn-primary" id="member-edit-role-save">Save role</SubmitButton>
                    </ActionForm>
                  ) : (
                    <p className="text-muted mb-0">Only the super-admin changes roles.</p>
                  )}
                </div>
              </div>

              <div className="card" id="member-edit-departments-card">
                <div className="card-header"><h5 className="card-title">Departments</h5></div>
                <div className="card-body">
                  <ul className="list-group list-group-flush mb-3" id="member-edit-department-list">
                    {departments.length === 0 ? (
                      <li className="list-group-item text-muted px-0">In no department.</li>
                    ) : (
                      departments.map((d) => (
                        <li className="list-group-item d-flex justify-content-between align-items-center px-0"
                            id={`member-department-row-${d.id}`} key={d.id}>
                          <span>
                            <Link href={withBack(`/team/departments/${d.id}`, here)}>{d.name}</Link>
                            {d.is_admin && <span className="badge bg-soft-warning text-warning ms-1">Administers</span>}
                            {d.is_primary && <span className="badge bg-soft-info text-info ms-1">Primary</span>}
                          </span>
                          <span className="d-flex gap-1">
                            <ActionForm path="/team/departments/member-add.php">
                              <input type="hidden" name="member" value={m.id} />
                              <input type="hidden" name="department" value={d.id} />
                              <input type="hidden" name="is_primary" value={d.is_primary ? "1" : "0"} />
                              <input type="hidden" name="is_admin" value={d.is_admin ? "0" : "1"} />
                              <SubmitButton className="btn btn-sm btn-light-brand">{d.is_admin ? "Revoke admin" : "Make admin"}</SubmitButton>
                            </ActionForm>
                            <ActionForm path="/team/departments/member-remove.php" confirm="Remove this member from the department?">
                              <input type="hidden" name="member" value={m.id} />
                              <input type="hidden" name="department" value={d.id} />
                              <SubmitButton className="btn btn-sm btn-light-brand text-danger">Remove</SubmitButton>
                            </ActionForm>
                          </span>
                        </li>
                      ))
                    )}
                  </ul>
                  <ActionForm path="/team/departments/member-add.php" id="member-edit-department-add-form" resetOnSuccess>
                    <input type="hidden" name="member" value={m.id} />
                    <div className="d-flex flex-wrap gap-2 align-items-center">
                      <select name="department" id="member-form-field-department" className="form-select w-auto" required defaultValue="">
                        <option value="">Add to department…</option>
                        {options.departments.filter((d) => !mine.has(d.id)).map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
                      </select>
                      <div className="form-check">
                        <input className="form-check-input" type="checkbox" name="is_admin" value="1" id="member-form-field-dept-admin" />
                        <label className="form-check-label fs-12" htmlFor="member-form-field-dept-admin">Administers it</label>
                      </div>
                      <SubmitButton className="btn btn-primary" id="member-edit-department-add">Add</SubmitButton>
                    </div>
                  </ActionForm>
                </div>
              </div>
            </div>

            <div className="col-lg-7">
              <MemberApplicationAccess memberId={m.id} grants={data.application_grants} applications={data.application_options}
                                       canManage={can.manage_applications} />
              {can.kernel_modules && (
              <div className="card" id="member-edit-grants-card">
                <div className="card-header"><h5 className="card-title">OS module access</h5>
                  <span className="fs-11 text-muted">the operating system's own screens and tools</span></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="member-edit-grants-table">
                      <thead className="thead-light"><tr><th>Module</th><th>Access</th><th className="text-end">Actions</th></tr></thead>
                      <tbody>
                        {modules.map((mod) => (
                          <tr id={`member-grant-edit-row-${mod.key}`} key={mod.key}>
                            <td>{mod.label}<div className="fs-11 text-muted"><code>{mod.key}</code></div></td>
                            <td>
                              {mod.access !== "" ? (
                                <span className={`badge bg-soft-${mod.access === "write" ? "success text-success" : "secondary text-secondary"}`}>{mod.access}</span>
                              ) : (
                                <span className="text-muted">—</span>
                              )}
                            </td>
                            <td className="text-end">
                              <span className="d-inline-flex gap-1 justify-content-end flex-wrap">
                                {([["read", "Read"], ["write", "Write"]] as const).filter(([access]) => access !== mod.access).map(([access, label]) => (
                                  <ActionForm path="/team/grant.php" key={access}>
                                    <input type="hidden" name="member" value={m.id} />
                                    <input type="hidden" name="module" value={mod.key} />
                                    <input type="hidden" name="access" value={access} />
                                    <SubmitButton className="btn btn-sm btn-light-brand">{label}</SubmitButton>
                                  </ActionForm>
                                ))}
                                {mod.access !== "" && (
                                  <ActionForm path="/team/grant-revoke.php">
                                    <input type="hidden" name="member" value={m.id} />
                                    <input type="hidden" name="module" value={mod.key} />
                                    <SubmitButton className="btn btn-sm btn-light-brand text-danger">Revoke</SubmitButton>
                                  </ActionForm>
                                )}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
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
