import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "@/components/kit/Link";
import SubmitButton from "@/components/kit/SubmitButton";
import ActionForm from "@/components/kit/ActionForm";
import DefaultApplicationForm from "@/components/settings/DefaultApplicationForm";
import PageHeader from "@/components/kit/PageHeader";
import RoleBadge from "@/components/team/RoleBadge";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { memberView } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "Member · Team" };

/**
 * Screen `member-view`. Data: GET /team/{id} (admin). The left column stacks two cards, so they
 * are plain `.card` (the stacked-card rule); the right column's single card keeps stretch-full.
 */
export default async function MemberPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();

  const here = await herePath();
  return renderScreen(`/team/${id}`, memberView, (data) => {
    const { member: m, departments, modules, applications, default_application: defaultApp, can } = data;
    const granted = modules.filter((mod) => mod.access !== "");
    return (
      <>
        <PageHeader title={m.display_name} id="member-view"
                    crumbs={[{ label: m.kind === "human" ? "Human Workforce" : "People", href: m.kind === "human" ? "/team?kind=human" : "/team" }, { label: m.display_name }]}
                    back={{ href: m.kind === "human" ? "/team?kind=human" : "/team", label: "People" }}>
          {m.kind === "agent" && (
            <Link href={withBack(`/agents/${m.id}`, here)} id="member-view-agent-btn" className="btn btn-light-brand">
              <i className="feather-cpu me-2"></i><span>The agent&rsquo;s page</span>
            </Link>
          )}
          {can.admin && (
            <Link href={withBack(`/team/${m.id}/edit`, here)} id="member-view-edit-btn" className="btn btn-primary">
              <i className="feather-edit-2 me-2"></i><span>{can.update ? "Edit details & access" : "Edit access"}</span>
            </Link>
          )}
          {can.suspend && (
            <ActionForm path="/team/suspend.php" confirm={`Suspend ${m.display_name}? They can no longer sign in or open any application until reinstated. Nothing is deleted.`}>
              <input type="hidden" name="member" value={m.id} />
              <SubmitButton className="btn btn-light-brand text-danger" id="member-view-suspend-btn">Suspend</SubmitButton>
            </ActionForm>
          )}
          {can.reinstate && (
            <ActionForm path="/team/reinstate.php">
              <input type="hidden" name="member" value={m.id} />
              <SubmitButton className="btn btn-light-brand" id="member-view-reinstate-btn">Reinstate</SubmitButton>
            </ActionForm>
          )}
        </PageHeader>

        <div className="main-content" data-screen="member-view">
          <div className="row">
            <div className="col-lg-5">
              <div className="card" id="member-view-facts-card">
                <div className="card-header"><h5 className="card-title">Identity</h5></div>
                <div className="card-body">
                  <dl className="row mb-0">
                    <dt className="col-5 text-muted fs-12">Role</dt><dd className="col-7"><RoleBadge role={m.business_role} /></dd>
                    <dt className="col-5 text-muted fs-12">Kind</dt><dd className="col-7">{m.kind === "agent" ? "AI agent" : "Person"}</dd>
                    <dt className="col-5 text-muted fs-12">Email</dt><dd className="col-7">{m.email ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Job title</dt><dd className="col-7">{m.job_title ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Status</dt><dd className="col-7">{m.status ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Timezone</dt><dd className="col-7">{m.timezone ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">2FA</dt>
                    <dd className="col-7">
                      {m.has_2fa === null ? "—" : m.has_2fa
                        ? <span className="badge bg-soft-success text-success">On</span>
                        : <span className="badge bg-soft-warning text-warning">Off</span>}
                    </dd>
                    <dt className="col-5 text-muted fs-12">Last login</dt><dd className="col-7">{m.last_login_display ?? "—"}</dd>
                  </dl>
                </div>
              </div>
              <div className="card" id="member-view-departments-card">
                <div className="card-header"><h5 className="card-title">Departments</h5></div>
                <div className="card-body p-0">
                  <ul className="list-group list-group-flush">
                    {departments.length === 0 ? (
                      <li className="list-group-item text-muted">In no department.</li>
                    ) : (
                      departments.map((d) => (
                        <li className="list-group-item d-flex justify-content-between align-items-center" key={d.id}>
                          <Link href={withBack(`/team/departments/${d.id}`, here)}>{d.name}</Link>
                          <span>
                            {d.is_admin && <span className="badge bg-soft-warning text-warning">Administers</span>}{" "}
                            {d.is_primary && <span className="badge bg-soft-info text-info">Primary</span>}
                          </span>
                        </li>
                      ))
                    )}
                  </ul>
                </div>
              </div>
            </div>
            <div className="col-lg-7">
              <div className="card stretch stretch-full" id="member-view-grants-card">
                <div className="card-header"><h5 className="card-title">Module access</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="member-view-grants-table">
                      <thead className="thead-light"><tr><th>Module</th><th>Access</th></tr></thead>
                      <tbody>
                        {granted.length === 0 ? (
                          <tr>
                            <td colSpan={2} className="text-center text-muted py-5">
                              No module grants.
                              {m.business_role !== "user" && (
                                <div className="fs-12 mt-1">An administrator reaches their own departments&rsquo; records without a grant.</div>
                              )}
                            </td>
                          </tr>
                        ) : (
                          granted.map((mod) => (
                            <tr id={`member-grant-row-${mod.key}`} key={mod.key}>
                              <td>{mod.label} <code className="fs-11 text-muted">{mod.key}</code></td>
                              <td>
                                <span className={`badge bg-soft-${mod.access === "write" ? "success text-success" : "secondary text-secondary"}`}>{mod.access}</span>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
              <div className="card stretch stretch-full" id="member-view-applications-card">
                <div className="card-header"><h5 className="card-title">Applications</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="member-view-applications-table">
                      <thead className="thead-light"><tr><th>Application</th><th>Where</th><th>Role</th><th>Through</th></tr></thead>
                      <tbody>
                        {applications.length === 0 ? (
                          <tr><td colSpan={4} className="text-center text-muted py-4">No application has been granted — application users are granted, never assumed.</td></tr>
                        ) : (
                          applications.map((ap, i) => (
                            <tr id={`member-application-row-${ap.id}-${i}`} key={`${ap.id}-${i}`}>
                              <td><Link href={withBack(`/applications/${ap.id}?tab=access`, here)}>{ap.name}</Link></td>
                              <td className="text-muted fs-12">{ap.scope && ap.scope_location_id !== null ? <Link href={withBack(`/locations/${ap.scope_location_id}`, here)}>{ap.scope}</Link>
                                : ap.scope && ap.scope_department_id !== null ? <Link href={withBack(`/team/departments/${ap.scope_department_id}`, here)}>{ap.scope}</Link> : ap.scope ?? "—"}</td>
                              <td><span className="badge bg-soft-info text-info">{ap.role ?? ap.capability}</span></td>
                              <td className="text-muted fs-12">{ap.route_department_id !== null ? <Link href={withBack(`/team/departments/${ap.route_department_id}`, here)}>{ap.route}</Link>
                                : ap.route_location_id !== null ? <Link href={withBack(`/locations/${ap.route_location_id}`, here)}>{ap.route}</Link> : ap.route}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
                {defaultApp !== null && (
                  <div className="card-footer" id="member-view-default-app">
                    {can.set_default_application ? (
                      <DefaultApplicationForm value={defaultApp} memberId={m.id} idPrefix="member-default-app" />
                    ) : (
                      <span className="fs-12 text-muted">
                        Opens on sign-in: {defaultApp.options.find((o) => o.id === defaultApp.application_id)?.name ?? "the launcher decides"}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
