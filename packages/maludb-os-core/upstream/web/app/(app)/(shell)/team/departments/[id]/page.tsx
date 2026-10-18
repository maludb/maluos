import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import DeleteDepartment from "@/components/team/DeleteDepartment";
import DepartmentTies from "@/components/team/DepartmentTies";
import AgentViewButton from "@/components/kit/AgentViewButton";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { memberHref, withBack } from "@/lib/routes";
import { departmentView } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "Department" };

/** Screen `department-view`. Data: GET /team/departments/{id} (admin). `back=department` keeps PHP on this page after a write. */
export default async function DepartmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();

  const here = await herePath();
  return renderScreen(`/team/departments/${id}`, departmentView, (data) => {
    const { department: d, members, options } = data;
    const deptId = d.id as number;
    const inside = new Set(members.map((m) => m.id));
    return (
      <>
        <PageHeader title={d.name} id="department-view" crumbs={[{ label: "Departments", href: "/team/departments" }, { label: d.name }]} back={{ href: "/team/departments", label: "Departments" }}>
          <AgentViewButton kind="department" id={deptId} screen="department-view" />
          <Link href={withBack(`/team/departments/${deptId}/edit`, here)} id="department-view-edit-btn" className="btn btn-primary">
            <i className="feather-edit-2 me-2"></i><span>Edit</span>
          </Link>
          {data.can.delete && <DeleteDepartment departmentId={deptId} blockers={data.delete_blockers} buttonId="department-view-delete-btn" />}
        </PageHeader>

        <div className="main-content" data-screen="department-view">
          <div className="row">
            <div className="col-12">
              <DepartmentTies ties={data.ties} isSystem={d.is_system} canDelete={data.can.delete} here={here} />
            </div>
          </div>
          <div className="row">
            <div className="col-lg-4">
              <div className="card stretch stretch-full" id="department-view-facts-card">
                <div className="card-header"><h5 className="card-title">Department</h5></div>
                <div className="card-body">
                  <p className="text-muted">{d.description ?? ""}</p>
                  <dl className="row mb-0">
                    <dt className="col-5 text-muted fs-12">Manager</dt><dd className="col-7">{d.manager_member_id !== null && d.manager_name ? <Link href={withBack(`/team/${d.manager_member_id}`, here)}>{d.manager_name}</Link> : d.manager_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Reports to</dt>
                    <dd className="col-7">
                      {d.system_key === "front_office" ? (
                        <span className="text-muted">Nobody — the top of the organisation</span>
                      ) : d.parent_id ? (
                        <Link href={withBack(`/team/departments/${d.parent_id}`, here)}>{d.parent_name ?? "Parent department"}</Link>
                      ) : "—"}
                    </dd>
                    <dt className="col-5 text-muted fs-12">Works at</dt><dd className="col-7">{d.home_location_id !== null && d.home_location_name ? <Link href={withBack(`/locations/${d.home_location_id}`, here)}>{d.home_location_name}</Link> : d.home_location_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Members</dt><dd className="col-7">{d.member_count}</dd>
                    <dt className="col-5 text-muted fs-12">Monthly budget</dt><dd className="col-7">{d.budget_display ?? "—"}</dd>
                    {d.is_system && (
                      <>
                        <dt className="col-5 text-muted fs-12">Standing</dt>
                        <dd className="col-7"><code>{d.system_key}</code> — renameable, never deleted</dd>
                      </>
                    )}
                  </dl>
                </div>
              </div>
            </div>
            <div className="col-lg-8">
              <div className="card stretch stretch-full" id="department-view-handbook-card">
                <div className="card-header"><h5 className="card-title">Handbook</h5>
                  <span className="fs-11 text-muted">what its agents read at the start of every run</span></div>
                <div className="card-body">
                  {d.handbook_markdown ? (
                    <pre className="mb-0 fs-12" style={{ whiteSpace: "pre-wrap", maxHeight: 360, overflow: "auto" }}>{d.handbook_markdown}</pre>
                  ) : (
                    <p className="text-muted mb-0">No handbook yet — its agents work from their job descriptions alone. <Link href={withBack(`/team/departments/${deptId}/edit`, here)}>Write one</Link>.</p>
                  )}
                </div>
              </div>
              <div className="card stretch stretch-full" id="department-view-applications-card">
                <div className="card-header"><h5 className="card-title">Applications</h5>
                  <span className="fs-11 text-muted">owned by it, serving it, or granted to everyone in it</span></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="department-applications-table">
                      <thead className="thead-light"><tr><th>Application</th><th>Tie</th><th>Access</th></tr></thead>
                      <tbody>
                        {data.applications.length === 0 ? (
                          <tr><td colSpan={3} className="text-center text-muted py-4">No application is owned by, serves or is granted to this department.</td></tr>
                        ) : (
                          data.applications.map((a, i) => (
                            <tr id={`department-application-row-${a.id}-${i}`} key={`${a.id}-${a.tie}-${i}`}>
                              <td><Link href={withBack(`/applications/${a.id}`, here)}>{a.name}</Link>{a.status !== "active" && <span className="text-muted fs-12 ms-1">({a.status})</span>}</td>
                              <td className="text-muted">{a.tie === "owns" ? "Owns it" : a.tie === "serves" ? "Served by it" : "Granted to the department"}</td>
                              <td className="fs-12">
                                {a.tie === "granted"
                                  ? <>{a.role ?? a.capability}{a.scope_name && <span className="text-muted"> at {a.scope_name}</span>}</>
                                  : <span className="text-muted">—</span>}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
              <div className="card stretch stretch-full" id="department-view-members-card">
                <div className="card-header"><h5 className="card-title">Members</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="department-members-table">
                      <thead className="thead-light"><tr><th>Name</th><th>Kind</th><th>Role here</th><th>Applications</th><th className="text-end">Actions</th></tr></thead>
                      <tbody>
                        {members.length === 0 ? (
                          <tr><td colSpan={5} className="text-center text-muted py-5">Nobody in this department yet.</td></tr>
                        ) : (
                          members.map((m) => (
                            <tr id={`department-member-row-${m.id}`} key={m.id}>
                              <td><Link href={withBack(memberHref({ id: m.id, kind: m.kind }) ?? `/team/${m.id}`, here)}>{m.name}</Link></td>
                              <td className="text-muted">{m.kind === "agent" ? "Agent" : "Person"}</td>
                              <td>
                                {m.is_admin ? <span className="badge bg-soft-warning text-warning">Administers</span> : <span className="text-muted">Member</span>}
                                {m.is_primary && <span className="badge bg-soft-info text-info ms-1">Primary</span>}
                              </td>
                              <td className="fs-12">
                                {m.applications.length === 0 ? <span className="text-muted">—</span> : m.applications.map((a, i) => (
                                  <span key={a.id}>{i > 0 && ", "}<Link href={withBack(`/applications/${a.id}`, here)}>{a.name}</Link> <span className="text-muted">({a.capability})</span></span>
                                ))}
                              </td>
                              <td className="text-end">
                                <span className="d-inline-flex gap-1 justify-content-end">
                                  <ActionForm path="/team/departments/member-add.php">
                                    <input type="hidden" name="department" value={deptId} />
                                    <input type="hidden" name="member" value={m.id} />
                                    <input type="hidden" name="is_primary" value={m.is_primary ? "1" : "0"} />
                                    <input type="hidden" name="is_admin" value={m.is_admin ? "0" : "1"} />
                                    <input type="hidden" name="back" value="department" />
                                    <SubmitButton className="btn btn-sm btn-light-brand">{m.is_admin ? "Revoke admin" : "Make admin"}</SubmitButton>
                                  </ActionForm>
                                  <ActionForm path="/team/departments/member-remove.php" confirm="Remove this member from the department?">
                                    <input type="hidden" name="department" value={deptId} />
                                    <input type="hidden" name="member" value={m.id} />
                                    <input type="hidden" name="back" value="department" />
                                    <SubmitButton className="btn btn-sm btn-light-brand text-danger">Remove</SubmitButton>
                                  </ActionForm>
                                </span>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                  <div className="p-3 border-top">
                    <ActionForm path="/team/departments/member-add.php" id="department-member-add-form" resetOnSuccess
                                className="d-flex flex-wrap gap-2 align-items-center">
                      <input type="hidden" name="department" value={deptId} />
                      <input type="hidden" name="back" value="department" />
                      <select name="member" id="department-form-field-member" className="form-select w-auto" required defaultValue="">
                        <option value="">Add a member…</option>
                        {options.members.filter((s) => !inside.has(s.id)).map((s) => (
                          <option value={s.id} key={s.id}>{s.name}{s.kind === "agent" ? " (agent)" : ""}</option>
                        ))}
                      </select>
                      <div className="form-check">
                        <input className="form-check-input" type="checkbox" name="is_admin" value="1" id="department-form-field-is-admin" />
                        <label className="form-check-label fs-12" htmlFor="department-form-field-is-admin">Administers it</label>
                      </div>
                      <SubmitButton className="btn btn-primary" id="department-member-add-btn">Add</SubmitButton>
                    </ActionForm>
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
