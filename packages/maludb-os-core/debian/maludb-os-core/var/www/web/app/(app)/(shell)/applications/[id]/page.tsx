import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { HealthBadge, StatusBadge } from "@/components/applications/Badges";
import RoleChecklist from "@/components/applications/RoleChecklist";
import ApplicationTokenCard from "@/components/applications/ApplicationTokenCard";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import Nl2br from "@/components/kit/Nl2br";
import PageHeader from "@/components/kit/PageHeader";
import KindBadge from "@/components/skills/KindBadge";
import { ucfirst } from "@/lib/format";
import { herePath } from "@/lib/here";
import { memberHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { applicationView, type ApplicationView } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "Application" };

const TABS: [ApplicationView["tab"], string][] = [["overview", "Overview"], ["endpoints", "Endpoints"], ["access", "Access"], ["scopes", "Scopes"], ["expertise", "Expertise"]];

/**
 * Screen `application-view` — tabs are the card header, and each tab is a URL (?tab=), as in
 * PHP. Data: GET /applications/{id}?tab= (insider; Edit/Retire with the applications grant,
 * grants management with module admission).
 */
export default async function ApplicationPage({
  params, searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { id: rawId } = await params;
  if (!/^\d+$/.test(rawId)) notFound();
  const { tab: rawTab } = await searchParams;
  const tabQuery = rawTab && TABS.some(([k]) => k === rawTab) ? `?tab=${rawTab}` : "";
  const here = await herePath();

  return renderScreen(`/applications/${rawId}${tabQuery}`, applicationView, (data) => {
    const a = data.application;
    const id = a.id as number;
    const counts = data.retirement_counts;
    const editable = data.can.edit && a.status !== "retired";

    return (
      <>
        <PageHeader title={a.name} icon="feather-grid" id="application-view"
                    crumbs={[{ label: "Applications", href: "/applications" }, { label: a.name }]} back={{ href: "/applications", label: "Applications" }}>
          {editable && (
            <>
              <Link href={withBack(`/applications/${id}/edit`, here)} className="btn btn-light-brand" id="application-view-edit-btn">
                <i className="feather-edit-2 me-2"></i><span>Edit</span>
              </Link>
              <ActionForm path="/applications/status.php"
                          confirm={`Retire ${a.name}? It has ${counts.access_grants ?? 0} live access grant(s) and ${counts.endpoints ?? 0} endpoint(s) — nothing is deleted, this only changes its status.`}>
                <input type="hidden" name="application" value={id} />
                <input type="hidden" name="status" value="retired" />
                <SubmitButton className="btn btn-light-brand text-danger" id="application-view-retire-btn">Retire</SubmitButton>
              </ActionForm>
            </>
          )}
        </PageHeader>

        <div className="main-content" data-screen="application-view" data-entity="application" data-record-id={id}>
          <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
            <StatusBadge status={a.status} />
            <span className="text-muted fs-12">{a.category_display}</span>
            {a.is_builtin && <span className="badge bg-soft-secondary text-secondary">builtin</span>}
            {data.gaps.length > 0 && (
              <span className="text-muted fs-12"><i className="feather-alert-triangle me-1"></i>{data.gaps.join("; ")}</span>
            )}
          </div>

          <div className="row">
            <div className="col-xxl-8">
              <div className="card border-top-0" id="application-view-detail-card">
                <div className="card-header p-0">
                  <ul className="nav nav-tabs flex-wrap w-100 text-center" id="application-view-tabs" role="tablist">
                    {TABS.filter(([key]) => key !== "scopes" || a.scope_kind !== "none").map(([key, label]) => (
                      <li className="nav-item flex-fill border-top" role="presentation" key={key}>
                        <Link href={`/applications/${id}?tab=${key}`} id={`application-view-tab-${key}`}
                              className={`nav-link${data.tab === key ? " active" : ""}`} scroll={false}>{label}</Link>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="tab-content">
                  <div className="tab-pane fade show active p-4" id={`application-view-pane-${data.tab}`} role="tabpanel">
                    {data.tab === "overview" && <OverviewTab data={data} here={here} />}
                    {data.tab === "endpoints" && <EndpointsTab data={data} here={here} />}
                    {data.tab === "access" && <AccessTab data={data} here={here} />}
                    {data.tab === "scopes" && <ScopesTab data={data} here={here} />}
                    {data.tab === "expertise" && <ExpertiseTab data={data} here={here} />}
                  </div>
                </div>
              </div>
            </div>

            <div className="col-xxl-4">
              <div className="card stretch stretch-full" id="application-view-identity-card">
                <div className="card-header"><h5 className="card-title">Identity</h5></div>
                <div className="card-body">
                  {a.description !== null && <p className="fs-13 text-muted mb-3">{a.description}</p>}
                  <dl className="row mb-0">
                    <dt className="col-5 text-muted fs-12">Vendor</dt><dd className="col-7">{a.vendor ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Self-hosted</dt><dd className="col-7">{a.is_self_hosted ? "Yes" : "No"}</dd>
                    <dt className="col-5 text-muted fs-12">Location</dt>
                    <dd className="col-7">{a.location_id !== null ? <Link href={withBack(`/locations/${a.location_id}`, here)}>{a.location_name ?? ""}</Link> : "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Owner department</dt>
                    <dd className="col-7">{a.owner_department_id !== null ? <Link href={withBack(`/team/departments/${a.owner_department_id}`, here)}>{a.owner_department_name ?? ""}</Link> : a.owner_department_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Accountable</dt>
                    <dd className="col-7">{a.owner_member_id !== null ? <Link href={withBack(`/team/${a.owner_member_id}`, here)}>{a.owner_name ?? ""}</Link> : a.owner_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Business area</dt><dd className="col-7">{a.business_area_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Expert</dt>
                    <dd className="col-7">{a.expert_member_id !== null ? <Link href={withBack(`/agents/${a.expert_member_id}`, here)}>{a.expert_name ?? ""}</Link> : "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Version</dt><dd className="col-7">{a.version ?? "—"}</dd>
                    {a.url !== null && (
                      <>
                        <dt className="col-5 text-muted fs-12">URL</dt>
                        <dd className="col-7 text-truncate"><a href={a.url} target="_blank" rel="noopener">{a.url}</a></dd>
                      </>
                    )}
                  </dl>
                </div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}

function OverviewTab({ data, here }: { data: ApplicationView; here: string | null }) {
  const a = data.application;
  return (
    <>
      <div className="row">
        <div className="col-md-6">
          <h6 className="fs-13 text-muted mb-2">Where it runs</h6>
          <dl className="row mb-4">
            <dt className="col-5 fs-12 text-muted">Location</dt>
            <dd className="col-7">
              {a.location_name !== null ? (
                <>{a.location_id !== null ? <Link href={withBack(`/locations/${a.location_id}`, here)}>{a.location_name}</Link> : a.location_name} {a.siting !== null && <span className="badge bg-soft-info text-info">{ucfirst(a.siting)}</span>}</>
              ) : "—"}
            </dd>
            <dt className="col-5 fs-12 text-muted">Criticality</dt><dd className="col-7">{ucfirst(a.criticality)}</dd>
            <dt className="col-5 fs-12 text-muted">Status</dt><dd className="col-7">{ucfirst(a.status)}</dd>
          </dl>
        </div>
        <div className="col-md-6">
          <h6 className="fs-13 text-muted mb-2">Health</h6>
          <div className="mb-3"><HealthBadge health={a.health} /></div>
          <ActionForm path="/applications/health-check.php">
            <input type="hidden" name="application" value={a.id ?? ""} />
            <SubmitButton className="btn btn-sm btn-light-brand" id="application-view-health-check-btn">
              <i className="feather-refresh-cw me-1"></i>Check now
            </SubmitButton>
          </ActionForm>
        </div>
      </div>
      <RolesPanel data={data} />
      {data.can.mint_token && a.id !== null && (
        <ApplicationTokenCard applicationId={a.id} token={data.kernel_token} />
      )}
      {a.notes !== null && (
        <>
          <h6 className="fs-13 text-muted mb-2">Notes</h6>
          <p className="fs-13"><Nl2br text={a.notes} /></p>
        </>
      )}
      <div className="mt-3 d-flex flex-wrap gap-3">
        <Link href={withBack(`/activity?entity_type=application&entity_id=${a.id}&period=all`, here)} className="fs-12">
          <i className="feather-activity me-1"></i>This application&rsquo;s history
        </Link>
        <Link href={withBack(`/ai/prompt-log?application=${a.id}&period=all`, here)} className="fs-12" id="application-calls-link">
          <i className="feather-cpu me-1"></i>Its model calls in the prompt log
        </Link>
      </div>
    </>
  );
}

function EndpointsTab({ data, here }: { data: ApplicationView; here: string | null }) {
  const id = data.application.id as number;
  const canEdit = data.can.edit;
  return (
    <>
      <div className="d-flex justify-content-end mb-2">
        {canEdit && (
          <Link href={withBack(`/applications/endpoints/new?application=${id}`, here)} className="btn btn-sm btn-primary" id="application-endpoints-add-btn">
            <i className="feather-plus me-1"></i>Add endpoint
          </Link>
        )}
      </div>
      <div className="table-responsive">
        <table className="table table-hover mb-0" id="application-endpoints-table">
          <thead className="thead-light">
            <tr>
              <th>Name</th><th>Kind</th><th>URL</th><th>Auth</th><th>Credential</th><th>Agent-reachable</th>
              {canEdit && <th className="text-end">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.endpoints.length === 0 ? (
              <tr><td colSpan={canEdit ? 7 : 6} className="text-center text-muted py-4">No endpoints yet.</td></tr>
            ) : (
              data.endpoints.map((e) => {
                const agentMcp = e.kind === "mcp" && e.agent_reachable;
                return (
                  <tr id={`application-endpoint-row-${e.id}`} key={e.id}>
                    <td>
                      {e.id !== null ? <Link href={withBack(`/applications/endpoints/${e.id}/edit`, here)} className="fw-semibold">{e.name}</Link> : e.name}
                      {agentMcp && <div className="text-muted fs-11">Agents may be granted tools on this endpoint.</div>}
                    </td>
                    <td><span className="badge bg-soft-info text-info">{e.kind}</span></td>
                    <td className="text-muted fs-12 text-truncate" style={{ maxWidth: "220px" }}>{e.url ?? "—"}</td>
                    <td className="text-muted fs-12">{e.auth_kind}</td>
                    <td>
                      {e.auth_kind === "none" ? <span className="text-muted fs-12">n/a</span>
                        : e.has_credential ? <span className="badge bg-soft-success text-success">On file</span>
                        : <span className="badge bg-soft-warning text-warning">Needed</span>}
                    </td>
                    <td>{agentMcp ? <span className="badge bg-soft-brand text-brand">Yes</span> : <span className="text-muted fs-12">No</span>}</td>
                    {canEdit && (
                      <td className="text-end">
                        <Link href={withBack(`/applications/endpoints/${e.id}/edit`, here)} className="btn btn-sm btn-light-brand" aria-label="Edit endpoint">
                          <i className="feather-edit-2"></i>
                        </Link>{" "}
                        <ActionForm path="/applications/endpoints/remove.php" className="d-inline" confirm={`Remove endpoint "${e.name}"?`}>
                          <input type="hidden" name="endpoint" value={e.id ?? ""} />
                          <input type="hidden" name="application" value={id} />
                          <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`application-endpoint-remove-${e.id}`} ariaLabel="Remove endpoint">
                            <i className="feather-trash-2"></i>
                          </SubmitButton>
                        </ActionForm>
                      </td>
                    )}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <p className="fs-12 text-muted mt-2">
        Credentials attach once the secret store exists (the Stripe slice) — no screen, view, tool or log row here ever carries a value.
      </p>
    </>
  );
}

function AccessTab({ data, here }: { data: ApplicationView; here: string | null }) {
  const id = data.application.id as number;
  const manage = data.can.manage_access;
  const scoped = data.application.scope_kind !== "none";
  const scopeLabel = data.application.scope_kind === "location" ? "Site" : "Department";
  const offered = data.roles.filter((r) => !r.withdrawn);
  const hasRoles = data.roles.length > 0;
  return (
    <>
      {!manage && (
        <div className="alert alert-info fs-13" role="alert" id="application-access-scope-note">
          You&rsquo;re seeing only your own access grants (or your department&rsquo;s). The super-admin grants access and sets
          the roles people hold here.
        </div>
      )}
      {data.withdrawn_holdings.length > 0 && (
        <div className="alert alert-warning fs-13" role="alert" id="application-access-withdrawn">
          <i className="feather-alert-triangle me-2"></i>{data.application.name} no longer offers some roles that grants still give —
          change these grants:{" "}
          {data.withdrawn_holdings.map((w, i) => {
            const href = w.grantee_member_id !== null ? memberHref({ id: w.grantee_member_id, kind: w.grantee_member_kind })
              : w.grantee_department_id !== null ? `/team/departments/${w.grantee_department_id}`
              : w.grantee_location_id !== null ? `/locations/${w.grantee_location_id}` : null;
            return <span key={`${w.grant_id}-${w.role_key}`}>{i > 0 && ", "}{href ? <Link href={withBack(href, here)}>{w.grantee}</Link> : w.grantee} ({w.role_name})</span>;
          })}.
        </div>
      )}
      <div className="table-responsive">
        <table className="table table-hover mb-0" id="application-access-table">
          <thead className="thead-light">
            <tr>
              <th>Grantee</th>{scoped && <th>{scopeLabel}</th>}<th>{hasRoles ? "Roles" : "Capability"}</th><th>Granted by</th><th>Granted</th><th>Expires</th>
              {manage && <th className="text-end">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.access.length === 0 ? (
              <tr><td colSpan={(manage ? 6 : 5) + (scoped ? 1 : 0)} className="text-center text-muted py-4">No access grants yet.</td></tr>
            ) : (
              data.access.map((g) => (
                <tr id={`application-access-row-${g.id}`} key={g.id}>
                  <td><i className={`${g.grantee_kind === "member" ? "feather-user" : g.grantee_kind === "residents" ? "feather-map-pin" : "feather-users"} me-1 text-muted`}></i>{(() => {
                    const href = g.grantee_kind === "member" ? memberHref({ id: g.member_id, kind: g.member_kind })
                      : g.grantee_kind === "department" && g.department_id !== null ? `/team/departments/${g.department_id}`
                      : g.grantee_kind === "residents" && g.resident_location_id !== null ? `/locations/${g.resident_location_id}` : null;
                    return href ? <Link href={withBack(href, here)}>{g.grantee_name}</Link> : g.grantee_name;
                  })()}</td>
                  {scoped && <td>{g.scope_name && g.scope_location_id !== null ? <Link href={withBack(`/locations/${g.scope_location_id}`, here)}>{g.scope_name}</Link>
                    : g.scope_name && g.scope_department_id !== null ? <Link href={withBack(`/team/departments/${g.scope_department_id}`, here)}>{g.scope_name}</Link> : g.scope_name ?? "—"}</td>}
                  <td>
                    {g.roles.length > 0 ? g.roles.map((r) => (
                      <span key={r.key} className={`badge ${r.withdrawn ? "bg-soft-warning text-warning" : "bg-soft-info text-info"} me-1`}
                            title={r.withdrawn ? "No longer offered by the application" : undefined}>{r.name}</span>
                    )) : <span className="badge bg-soft-info text-info">{g.role_name ?? ucfirst(g.capability)}</span>}
                    {g.roles.length > 0 && <div className="fs-11 text-muted">amounts to {g.capability}</div>}
                  </td>
                  <td className="text-muted fs-12">{g.granted_by_member_id !== null && g.granted_by_display !== "You"
                    ? <Who who={{ id: g.granted_by_member_id, name: g.granted_by_display }} here={here} /> : g.granted_by_display}</td>
                  <td className="text-muted fs-12">{g.granted_at ?? "—"}</td>
                  <td className="text-muted fs-12">{g.expires_at ?? "—"}</td>
                  {manage && (
                    <td className="text-end">
                      {hasRoles && (
                        <details className="text-start mb-1" id={`application-access-change-${g.id}`}>
                          <summary className="fs-12">Change roles</summary>
                          <ActionForm path="/applications/access-change.php" className="mt-1">
                            <input type="hidden" name="application_access" value={g.id} />
                            <input type="hidden" name="application" value={id} />
                            <RoleChecklist roles={offered} checked={g.roles.map((r) => r.key)} idPrefix={`application-access-${g.id}`} compact />
                            <SubmitButton className="btn btn-sm btn-light-brand mt-1">Save roles</SubmitButton>
                          </ActionForm>
                        </details>
                      )}
                      <ActionForm path="/applications/access-revoke.php" confirm="Revoke this access grant?">
                        <input type="hidden" name="application_access" value={g.id} />
                        <input type="hidden" name="application" value={id} />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`application-access-revoke-${g.id}`}>Revoke</SubmitButton>
                      </ActionForm>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {manage && (
        <>
          <ActionForm path="/applications/access-grant.php" id="application-access-grant-form" resetOnSuccess
                      className="row g-2 align-items-end mt-3 p-3 border-top">
            <input type="hidden" name="application" value={id} />
            <div className="col-sm-3">
              <label className="form-label fs-12" htmlFor="application-access-field-member">Member</label>
              <select name="member" id="application-access-field-member" className="form-select form-select-sm" defaultValue="">
                <option value="">— none —</option>
                {data.options.members.map((m) => <option value={m.id} key={m.id}>{m.name}</option>)}
              </select>
            </div>
            <div className="col-sm-3">
              <label className="form-label fs-12" htmlFor="application-access-field-department">…or department</label>
              <select name="department" id="application-access-field-department" className="form-select form-select-sm" defaultValue="">
                <option value="">— none —</option>
                {data.options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div className="col-sm-3">
              <label className="form-label fs-12" htmlFor="application-access-field-residents">…or everyone at</label>
              <select name="residents" id="application-access-field-residents" className="form-select form-select-sm" defaultValue="">
                <option value="">— none —</option>
                {data.options.sites.map((l) => <option value={l.id} key={l.id}>{l.name}{l.kind === "office" ? " (office)" : ""}</option>)}
              </select>
            </div>
            {scoped && (
              <div className="col-sm-3">
                <label className="form-label fs-12" htmlFor="application-access-field-scope">{scopeLabel} *</label>
                <select name="scope" id="application-access-field-scope" className="form-select form-select-sm" required defaultValue="">
                  <option value="">— choose —</option>
                  {data.scopes.map((sc) => <option value={sc.id} key={sc.id}>{sc.name}</option>)}
                </select>
              </div>
            )}
            {hasRoles ? (
              <div className="col-12">
                <span className="form-label fs-12 d-block">Roles * <span className="text-muted">— several may be held; the grant amounts to the highest</span></span>
                <RoleChecklist roles={offered} idPrefix="application-access-field" />
              </div>
            ) : (
              <div className="col-sm-2">
                <label className="form-label fs-12" htmlFor="application-access-field-capability">Capability</label>
                <select name="capability" id="application-access-field-capability" className="form-select form-select-sm" defaultValue="read">
                  {data.options.capabilities.map((c) => <option value={c} key={c}>{ucfirst(c)}</option>)}
                </select>
              </div>
            )}
            <div className="col-sm-2">
              <label className="form-label fs-12" htmlFor="application-access-field-expires_at">Expires</label>
              <input type="date" name="expires_at" id="application-access-field-expires_at" className="form-control form-control-sm" />
            </div>
            <div className="col-sm-2">
              <SubmitButton className="btn btn-sm btn-primary w-100" id="application-access-grant-btn">Grant</SubmitButton>
            </div>
            <div className="col-12">
              <input type="text" name="note" className="form-control form-control-sm" id="application-access-field-note" placeholder="Note (optional)" />
            </div>
          </ActionForm>
          <div className="form-text px-3">
            Pick one grantee: a member, a department, or everyone residing at a site.
            {scoped && ` A grant admits to one ${scopeLabel.toLowerCase()} — grant again for another.`}
          </div>
        </>
      )}
    </>
  );
}

/** Who knows this application, and the skills that belong to it (db/130). Active applications only. */
function ExpertiseTab({ data, here }: { data: ApplicationView; here: string | null }) {
  const a = data.application;
  const id = a.id as number;
  const x = data.expertise;
  if (!x.available) {
    return <p className="text-muted mb-0" id="application-expertise-unavailable">An expert and skills belong to an application that is active.</p>;
  }
  return (
    <>
      <h6 className="fs-13 text-muted mb-2">Subject matter expert</h6>
      <p className="fs-12 text-muted">
        The agent people and other agents ask about {a.name}. Naming an expert grants nothing — access is still given on the Access tab or by a module grant.
      </p>
      {data.can.edit ? (
        <ActionForm path="/applications/sme-set.php" id="application-expert-form" className="row g-2 align-items-end mb-4">
          <input type="hidden" name="application" value={id} />
          <div className="col-sm-8">
            <label className="form-label fs-12" htmlFor="application-expert-field-agent">Expert agent</label>
            <select name="agent" id="application-expert-field-agent" className="form-select form-select-sm"
                    defaultValue={a.expert_member_id ?? ""} key={a.expert_member_id ?? 0}>
              <option value="">— no expert —</option>
              {x.agents.map((g) => <option value={g.id} key={g.id}>{g.name}</option>)}
            </select>
          </div>
          <div className="col-sm-4">
            <SubmitButton className="btn btn-sm btn-primary w-100" id="application-expert-save-btn">Save expert</SubmitButton>
          </div>
        </ActionForm>
      ) : (
        <p className="mb-4" id="application-expert-name">
          {a.expert_member_id !== null ? <Link href={withBack(`/agents/${a.expert_member_id}`, here)}><i className="feather-cpu me-1"></i>{a.expert_name}</Link>
                                       : <span className="text-muted">No expert yet.</span>}
        </p>
      )}

      <h6 className="fs-13 text-muted mb-2">Runbooks and skills</h6>
      <p className="fs-12 text-muted">
        A runbook is the application&rsquo;s generic skill (its SKILL.md says <code>kind: runbook</code>); a skill is a narrower one. Either, given to {a.name}, reaches its expert and every agent that may use it, at their next run
        {x.agent_options.length > 0 && <> &mdash; or give one to a single agent, and it appears in that agent&rsquo;s Skills tab as its own</>}.
      </p>
      <div className="table-responsive">
        <table className="table table-hover mb-0" id="application-skills-table">
          <thead className="thead-light">
            <tr><th>Skill</th><th>Version</th><th>Since</th>{x.can_set_skills && <th className="text-end">Actions</th>}</tr>
          </thead>
          <tbody>
            {x.skills.length === 0 ? (
              <tr><td colSpan={x.can_set_skills ? 4 : 3} className="text-center text-muted py-4">No skills yet.</td></tr>
            ) : (
              x.skills.map((s) => (
                <tr id={`application-skill-row-${s.id}`} key={s.id}>
                  <td><Link href={withBack(`/ai/skills/${encodeURIComponent(s.skill_name)}`, here)} className="fw-semibold">{s.skill_name}</Link> <KindBadge kind={s.kind} />{s.note && <div className="fs-12 text-muted">{s.note}</div>}</td>
                  <td>{s.pinned_bundle_hash
                    ? <span className="badge bg-soft-warning text-warning" title={s.pinned_bundle_hash}>pinned {s.pinned_bundle_hash.slice(0, 10)}</span>
                    : <span className="text-muted">newest</span>}</td>
                  <td className="text-muted fs-12">{s.created_at ?? "—"}</td>
                  {x.can_set_skills && (
                    <td className="text-end">
                      <div className="d-flex flex-wrap justify-content-end gap-2">
                        {x.agent_options.length > 0 && (
                          <ActionForm path="/skills/assign.php" className="d-flex gap-1" id={`application-skill-give-${s.id}`}>
                            <input type="hidden" name="scope_kind" value="agent" />
                            <input type="hidden" name="skill_name" value={s.skill_name} />
                            <select className="form-select form-select-sm" name="agent" required defaultValue="" aria-label={`Give ${s.skill_name} to an agent`} style={{ minWidth: 150 }}>
                              <option value="" disabled>Give to an agent…</option>
                              {x.agent_options.map((g) => <option value={g.id} key={g.id}>{g.name}</option>)}
                            </select>
                            <SubmitButton className="btn btn-sm btn-light-brand" id={`application-skill-give-btn-${s.id}`}>Give</SubmitButton>
                          </ActionForm>
                        )}
                        <ActionForm path="/skills/unassign.php" confirm={`Withdraw ${s.skill_name} from ${a.name}?`}>
                          <input type="hidden" name="skill_assignment" value={s.id} />
                          <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`application-skill-unassign-${s.id}`}>Withdraw</SubmitButton>
                        </ActionForm>
                      </div>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {x.can_set_skills && (
        <ActionForm path="/skills/assign.php" id="application-skill-assign-form" resetOnSuccess
                    className="row g-2 align-items-end mt-3 p-3 border-top">
          <input type="hidden" name="scope_kind" value="application" />
          <input type="hidden" name="application" value={id} />
          <div className="col-sm-4">
            <label className="form-label fs-12" htmlFor="application-skill-field-name">Skill name</label>
            <input type="text" name="skill_name" id="application-skill-field-name" className="form-control form-control-sm"
                   placeholder="month-end-close" pattern="[a-z0-9][a-z0-9\-]*" required />
          </div>
          <div className="col-sm-3">
            <label className="form-label fs-12" htmlFor="application-skill-field-pin">Pin to version (optional)</label>
            <input type="text" name="pinned_bundle_hash" id="application-skill-field-pin" className="form-control form-control-sm" />
          </div>
          <div className="col-sm-3">
            <label className="form-label fs-12" htmlFor="application-skill-field-note">Note (optional)</label>
            <input type="text" name="note" id="application-skill-field-note" className="form-control form-control-sm" />
          </div>
          <div className="col-sm-2">
            <SubmitButton className="btn btn-sm btn-primary w-100" id="application-skill-assign-btn">Add skill</SubmitButton>
          </div>
          <div className="col-12 form-text">The skill must exist and be enabled in MaluDB — see <Link href="/skills">Skills</Link>.</div>
        </ActionForm>
      )}
    </>
  );
}


/**
 * The application's own roles (db/141, db/145): published by the application through its MCP server
 * (app_roles) and read here by the super-admin with "Read roles from the application"; each amounts to a
 * capability and lists the rights it gives inside the application. Set by hand only for an application
 * that does not publish them.
 */
function RolesPanel({ data }: { data: ApplicationView }) {
  const a = data.application;
  if (data.roles.length === 0 && !data.can.set_roles && !data.can.refresh_roles) return null;
  const json = JSON.stringify(data.roles.filter((r) => !r.withdrawn).map((r) => ({ key: r.key, name: r.name, capability: r.capability, is_admin: r.is_admin })), null, 1);
  const synced = data.roles_synced_at;
  return (
    <div className="mb-4" id="application-roles-panel">
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
        <h6 className="fs-13 text-muted mb-0">Roles</h6>
        {data.can.refresh_roles && a.id !== null && (
          <ActionForm path="/applications/roles-refresh.php" className="d-flex align-items-center gap-2">
            <input type="hidden" name="application" value={a.id} />
            <span className="fs-11 text-muted">{synced ? `read from ${a.name} ${new Date(synced).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}` : "never read from the application"}</span>
            <SubmitButton className="btn btn-sm btn-light-brand" id="application-roles-refresh">
              <i className="feather-refresh-cw me-1"></i>Read roles from the application
            </SubmitButton>
          </ActionForm>
        )}
      </div>
      {data.roles.length === 0 ? (
        <p className="fs-13 text-muted">
          No roles yet — grants carry a capability (read, write or admin).
          {data.can.refresh_roles && ` If ${a.name} publishes its roles (the app_roles tool on its MCP server), read them.`}
        </p>
      ) : (
        <div className="row g-2" id="application-roles-list">
          {data.roles.map((r) => (
            <div className="col-md-6" key={r.key}>
              <div className={`border rounded p-2 h-100 ${r.withdrawn ? "border-warning" : ""}`} id={`application-role-row-${r.key}`}>
                <div className="d-flex justify-content-between align-items-start gap-2">
                  <span className="fw-semibold">{r.name} <span className="text-muted fs-11">{r.key}</span></span>
                  <span className="text-nowrap">
                    {r.is_admin && <span className="badge bg-soft-brand text-brand me-1">admin</span>}
                    {r.withdrawn && <span className="badge bg-soft-warning text-warning me-1">no longer offered</span>}
                    <span className="badge bg-soft-secondary text-secondary">{r.capability}</span>
                  </span>
                </div>
                {r.description && <div className="fs-12 text-muted mt-1">{r.description}</div>}
                {r.rights.length > 0 && (
                  <ul className="fs-12 mb-1 mt-1 ps-3">
                    {r.rights.map((x) => <li key={x.key}>{x.description || x.key} <span className="text-muted fs-11">{x.key}</span></li>)}
                  </ul>
                )}
                <div className="fs-11 text-muted">{r.live_grant_count} live {r.live_grant_count === 1 ? "grant" : "grants"}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      {data.can.set_roles && a.id !== null && synced === null && (
        <details id="application-roles-edit" className="mt-2">
          <summary className="fs-12">Set the roles by hand</summary>
          <ActionForm path="/applications/roles-set.php" className="mt-2">
            <input type="hidden" name="application" value={a.id} />
            <textarea name="roles" className="form-control font-monospace fs-12" rows={6} defaultValue={json}
                      id="application-roles-field" aria-label="Roles, as a JSON list"></textarea>
            <div className="form-text">
              Only for an application that does not publish its roles. A list of key, name, capability (read, write or admin) and
              is_admin — exactly one admin role, the one a super-admin holds everywhere.
            </div>
            <SubmitButton className="btn btn-sm btn-light-brand mt-2" id="application-roles-save">Save roles</SubmitButton>
          </ActionForm>
        </details>
      )}
    </div>
  );
}

/** The sites or departments one installation serves (db/141) — the kernel owns them; the application creates each on its next sync. */
function ScopesTab({ data, here }: { data: ApplicationView; here: string | null }) {
  const id = data.application.id as number;
  const byLocation = data.application.scope_kind === "location";
  const canEdit = data.can.edit;
  const taken = new Set(data.scopes.map((sc) => (byLocation ? sc.location_id : sc.department_id)));
  const choices = byLocation
    ? data.options.sites.filter((l) => l.kind === "site" && !taken.has(l.id))
    : data.options.departments.filter((d) => !taken.has(d.id));
  return (
    <>
      <p className="fs-13 text-muted">
        {byLocation ? "The sites this installation serves — each has its own data in the application."
          : "The departments this installation serves — each has its own data in the application."}{" "}
        People reach one only through a grant on the Access tab.
      </p>
      {data.scopes.length === 0 ? (
        <p className="text-muted fs-13" id="application-scopes-empty">It serves none yet.</p>
      ) : (
        <div className="row g-3 mb-3" id="application-scopes-list">
          {data.scopes.map((sc) => (
            <div className="col-md-6" key={sc.id}>
              <div className="card mb-0 h-100" id={`application-scope-card-${sc.id}`}>
                <div className="card-body">
                  <div className="d-flex justify-content-between align-items-start gap-2">
                    <div>
                      <div className="fw-semibold">
                        <i className={`${byLocation ? "feather-map-pin" : "feather-users"} me-1 text-muted`}></i>
                        {byLocation && sc.location_id !== null ? <Link href={withBack(`/locations/${sc.location_id}`, here)}>{sc.name}</Link>
                          : !byLocation && sc.department_id !== null ? <Link href={withBack(`/team/departments/${sc.department_id}`, here)}>{sc.name}</Link> : sc.name}
                      </div>
                      {sc.address !== null && <div className="text-muted fs-12">{sc.address}</div>}
                      <div className="text-muted fs-12">
                        {sc.timezone !== null && <>{sc.timezone} · </>}{sc.live_grant_count} grant{sc.live_grant_count === 1 ? "" : "s"}
                      </div>
                    </div>
                    {canEdit && (
                      <ActionForm path="/applications/scope-remove.php"
                                  confirm={`Stop serving ${sc.name}? Its ${sc.live_grant_count} grant(s) are revoked.`}>
                        <input type="hidden" name="application" value={id} />
                        <input type="hidden" name="scope" value={sc.id} />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`application-scope-remove-${sc.id}`}>Remove</SubmitButton>
                      </ActionForm>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {canEdit && (
        <ActionForm path="/applications/scope-add.php" id="application-scope-add-form" resetOnSuccess className="row g-2 align-items-end border-top pt-3">
          <input type="hidden" name="application" value={id} />
          <div className="col-sm-8">
            <label className="form-label fs-12" htmlFor="application-scope-field">{byLocation ? "Site" : "Department"}</label>
            <select name={byLocation ? "location" : "department"} id="application-scope-field" className="form-select form-select-sm" required defaultValue="">
              <option value="">— choose —</option>
              {choices.map((c) => <option value={c.id} key={c.id}>{c.name}</option>)}
            </select>
            {byLocation && choices.length === 0 && (
              <div className="form-text">No site left to add — <Link href="/locations/new?kind=site">add a site</Link> on Work Locations.</div>
            )}
          </div>
          <div className="col-sm-4">
            <SubmitButton className="btn btn-sm btn-primary w-100" id="application-scope-add-btn">Serve it</SubmitButton>
          </div>
        </ActionForm>
      )}
    </>
  );
}
