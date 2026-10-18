import type { Metadata } from "next";
import { notFound } from "next/navigation";
import DeleteLocation from "@/components/estate/DeleteLocation";
import { KindBadge, PresenceBadge } from "@/components/estate/LocationBadges";
import ActionForm from "@/components/kit/ActionForm";
import AgentViewButton from "@/components/kit/AgentViewButton";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { memberHref, withBack } from "@/lib/routes";
import { locationView } from "@/lib/schemas/estate";

export const metadata: Metadata = { title: "Location" };

const KIND_ICON: Record<string, string> = { building: "feather-server", office: "feather-monitor", desk: "feather-hard-drive", site: "feather-map-pin" };

/**
 * Screen `location-view`. Data: GET /locations/{id} (insider). Both columns stack several cards,
 * so every card here is a plain `.card` (the stacked-card rule — the PHP template stretches them
 * all, which is the same defect the company page had).
 */
export default async function LocationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  if (!/^\d+$/.test(rawId)) notFound();

  const here = await herePath();
  return renderScreen(`/locations/${rawId}`, locationView, (data) => {
    const { location: l, residents, departments, applications, serving_applications: serving, options, can } = data;
    const isSite = l.kind === "site";
    const id = l.id;
    const active = l.status === "active";
    const isOffice = l.kind === "office";
    const isDesk = l.kind === "desk";
    const residentIds = new Set(residents.map((r) => r.id));
    const deptIds = new Set(departments.map((d) => d.id));

    return (
      <>
        <PageHeader title={l.name} icon={KIND_ICON[l.kind] ?? "feather-map-pin"} id="location-view" crumbs={[{ label: "Work Locations", href: "/locations" }, { label: l.name }]} back={{ href: "/locations", label: "Work locations" }}>
          <AgentViewButton kind="location" id={id} screen="location-view" />
          {isOffice && active && (
            <ActionForm path="/locations/move.php" className="d-flex gap-1">
              <input type="hidden" name="location" value={id} />
              <select name="parent_location" className="form-select form-select-sm w-auto" id="location-move-parent"
                      aria-label="Move to building" defaultValue={l.parent_id ?? ""} key={l.parent_id ?? 0}>
                <option value="">— no building —</option>
                {options.buildings.map((b) => <option value={b.id} key={b.id}>{b.name}</option>)}
              </select>
              <SubmitButton className="btn btn-sm btn-light-brand" id="location-move-btn">Move</SubmitButton>
            </ActionForm>
          )}
          {active && (
            <Link href={withBack(`/locations/${id}/edit`, here)} className="btn btn-light-brand" id="location-edit-btn">
              <i className="feather-edit-2 me-2"></i><span>Edit</span>
            </Link>
          )}
          {can.retire && (
            <ActionForm path="/locations/retire.php"
                        confirm="Retire this location? It must have no active children, applications or residents.">
              <input type="hidden" name="location" value={id} />
              <SubmitButton className="btn btn-light-brand text-danger" id="location-retire-btn">Retire</SubmitButton>
            </ActionForm>
          )}
          {can.delete && <DeleteLocation locationId={id} blockers={data.delete_blockers} buttonId="location-delete-btn" />}
        </PageHeader>

        <div className="main-content" data-screen="location-view" data-entity="location" data-record-id={id}>
          <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
            <KindBadge kind={l.kind} />
            <PresenceBadge presence={l.presence} retired={!active} />
            {l.presence !== "online" && l.last_seen_at !== null && <span className="text-muted fs-12">seen {l.last_seen_at}</span>}
            {l.parent_name !== null && l.parent_id !== null && (
              <span className="text-muted fs-12">in <Link href={withBack(`/locations/${l.parent_id}`, here)}>{l.parent_name}</Link></span>
            )}
          </div>
          <div className="mb-3 fs-13" id="location-residency-note">
            <i className="feather-info me-1 text-muted"></i>
            {l.allows_humans
              ? "People and agents work here."
              : "Nobody resides here — a building hosts offices and desks, not people or agents directly."}
          </div>

          <div className="row">
            <div className="col-lg-6">
              <div className="card" id="location-specs-card">
                <div className="card-header"><h5 className="card-title">Specs</h5></div>
                <div className="card-body">
                  {l.description && <p className="mb-3">{l.description}</p>}
                  {isDesk && (
                    <dl className="row mb-3">
                      <dt className="col-5 text-muted fs-12">Owner</dt><dd className="col-7">{l.owner_member_id !== null && l.owner_name ? <Link href={withBack(`/team/${l.owner_member_id}`, here)}>{l.owner_name}</Link> : l.owner_name ?? "—"}</dd>
                    </dl>
                  )}
                  <dl className="row mb-0">
                    {l.spec_rows.map((row) => (
                      <SpecRow key={row.label} label={row.label} value={row.value} muted={row.value === "Not enrolled yet."} />
                    ))}
                  </dl>
                </div>
              </div>

              {isOffice && (
                <div className="card" id="location-office-manager-card">
                  <div className="card-header"><h5 className="card-title">Office manager</h5></div>
                  <div className="card-body">
                    {!l.allows_agents ? (
                      <p className="text-muted fs-13 mb-0">
                        This office is not managed — the host is not under the system&rsquo;s control, so it cannot carry an office manager (an agent).
                      </p>
                    ) : options.agents.length === 0 ? (
                      <p className="text-muted fs-13 mb-0">An office manager is an agent — agents arrive with Agent HR.</p>
                    ) : (
                      <>
                        <p className="mb-2">{l.office_manager_member_id !== null && l.office_manager_name ? <Link href={withBack(`/agents/${l.office_manager_member_id}`, here)}>{l.office_manager_name}</Link> : l.office_manager_name ?? "No office manager set."}</p>
                        <ActionForm path="/locations/office-manager.php" className="d-flex gap-2" id="location-office-manager-form">
                          <input type="hidden" name="location" value={id} />
                          <select name="agent" className="form-select form-select-sm w-auto" id="location-form-field-agent"
                                  defaultValue={l.office_manager_member_id ?? ""} key={l.office_manager_member_id ?? 0}>
                            <option value="">— none —</option>
                            {options.agents.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
                          </select>
                          <SubmitButton className="btn btn-sm btn-light-brand" id="location-office-manager-btn">Set</SubmitButton>
                        </ActionForm>
                      </>
                    )}
                  </div>
                </div>
              )}

              <div className="card" id="location-tasks-card">
                <div className="card-header"><h5 className="card-title">Cross-location tasks</h5></div>
                <div className="card-body">
                  <p className="text-muted fs-13 mb-0">Cross-location tasks arrive with the desk companion.</p>
                </div>
              </div>
              <div className="mb-2">
                <Link href={`/activity?entity_type=location&entity_id=${id}&period=all`} className="fs-12">
                  <i className="feather-activity me-1"></i>This location&rsquo;s history
                </Link>
              </div>
            </div>

            <div className="col-lg-6">
              <div className="card" id="location-residents-card">
                <div className="card-header"><h5 className="card-title">Residents</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="location-residents-table">
                      <thead className="thead-light">
                        <tr><th>Name</th><th>Role</th>{active && <th className="text-end">Actions</th>}</tr>
                      </thead>
                      <tbody>
                        {residents.length === 0 ? (
                          <tr><td colSpan={active ? 3 : 2} className="text-center text-muted py-4">Nobody lives here yet.</td></tr>
                        ) : (
                          residents.map((r) => (
                            <tr id={`location-resident-row-${r.id}`} key={r.id}>
                              <td>
                                <i className={`${r.kind === "agent" ? "feather-cpu" : "feather-user"} me-1`} title={r.kind === "agent" ? "Agent" : "Person"}></i>
                                <Link href={withBack(memberHref({ id: r.id, kind: r.kind }) ?? `/team/${r.id}`, here)}>{r.name}</Link>
                              </td>
                              <td>
                                {r.is_primary ? <span className="badge bg-soft-info text-info">Primary</span>
                                              : <span className="text-muted fs-12">Also works here</span>}
                                {r.is_office_manager && <span className="badge bg-soft-brand text-brand ms-1">Office manager</span>}
                              </td>
                              {active && (
                                <td className="text-end">
                                  <ActionForm path="/locations/resident-remove.php" confirm="Remove this resident?">
                                    <input type="hidden" name="location" value={id} />
                                    <input type="hidden" name="member" value={r.id} />
                                    <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`location-resident-remove-${r.id}`}>Remove</SubmitButton>
                                  </ActionForm>
                                </td>
                              )}
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                  {active && (
                    <div className="p-3 border-top">
                      <ActionForm path="/locations/resident-add.php" id="location-resident-add-form" resetOnSuccess
                                  className="d-flex flex-wrap gap-2 align-items-center">
                        <input type="hidden" name="location" value={id} />
                        <select name="member" id="location-form-field-member" className="form-select w-auto" required defaultValue="">
                          <option value="">Add a resident…</option>
                          {options.residents.filter((s) => !residentIds.has(s.id)).map((s) => (
                            <option value={s.id} key={s.id}>{s.name}{s.kind === "agent" ? " (agent)" : ""}</option>
                          ))}
                        </select>
                        <div className="form-check">
                          <input className="form-check-input" type="checkbox" name="is_primary" value="1" id="location-form-field-is_primary" defaultChecked />
                          <label className="form-check-label fs-12" htmlFor="location-form-field-is_primary">Primary</label>
                        </div>
                        <SubmitButton className="btn btn-primary" id="location-resident-add-btn">Add</SubmitButton>
                      </ActionForm>
                    </div>
                  )}
                </div>
              </div>

              {isOffice && (
                <div className="card" id="location-departments-card">
                  <div className="card-header"><h5 className="card-title">Departments</h5></div>
                  <div className="card-body p-0">
                    <div className="table-responsive">
                      <table className="table table-hover mb-0" id="location-departments-table">
                        <thead className="thead-light"><tr><th>Name</th><th className="text-end">Actions</th></tr></thead>
                        <tbody>
                          {departments.length === 0 ? (
                            <tr><td colSpan={2} className="text-center text-muted py-4">No department calls this home.</td></tr>
                          ) : (
                            departments.map((d) => (
                              <tr id={`location-department-row-${d.id}`} key={d.id}>
                                <td><Link href={withBack(`/team/departments/${d.id}`, here)}>{d.name}</Link></td>
                                <td className="text-end">
                                  <ActionForm path="/locations/department-remove.php" confirm="Remove this department's home here?">
                                    <input type="hidden" name="location" value={id} />
                                    <input type="hidden" name="department" value={d.id} />
                                    <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`location-department-remove-${d.id}`}>Remove</SubmitButton>
                                  </ActionForm>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    <div className="p-3 border-top">
                      <ActionForm path="/locations/department-add.php" id="location-department-add-form" resetOnSuccess
                                  className="d-flex flex-wrap gap-2 align-items-center">
                        <input type="hidden" name="location" value={id} />
                        <select name="department" id="location-form-field-department" className="form-select w-auto" required defaultValue="">
                          <option value="">Add a department…</option>
                          {options.departments.filter((d) => !deptIds.has(d.id)).map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
                        </select>
                        <SubmitButton className="btn btn-primary" id="location-department-add-btn">Add</SubmitButton>
                      </ActionForm>
                    </div>
                  </div>
                </div>
              )}

              {isSite ? (
              <div className="card" id="location-serving-card">
                <div className="card-header"><h5 className="card-title">Applications serving this site</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="location-serving-table">
                      <thead className="thead-light"><tr><th>Application</th><th>Grants here</th></tr></thead>
                      <tbody>
                        {serving.length === 0 ? (
                          <tr><td colSpan={2} className="text-center text-muted py-4">
                            No application serves this site yet — add it as a scope on the application.
                          </td></tr>
                        ) : (
                          serving.map((a) => (
                            <tr id={`location-serving-row-${a.scope_id}`} key={a.scope_id}>
                              <td><Link href={withBack(`/applications/${a.id}?tab=scopes`, here)}>{a.name}</Link></td>
                              <td className="text-muted">{a.live_grant_count}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
              ) : (
              <div className="card" id="location-applications-card">
                <div className="card-header"><h5 className="card-title">Applications</h5></div>
                <div className="card-body p-0">
                  <div className="table-responsive">
                    <table className="table table-hover mb-0" id="location-applications-table">
                      <thead className="thead-light"><tr><th>Name</th><th>Category</th><th>Status</th></tr></thead>
                      <tbody>
                        {applications.length === 0 ? (
                          <tr><td colSpan={3} className="text-center text-muted py-4">Nothing runs here yet.</td></tr>
                        ) : (
                          applications.map((a) => {
                            const c = a.status === "active" ? "success" : "secondary";
                            return (
                              <tr id={`location-application-row-${a.id}`} key={a.id}>
                                <td><Link href={withBack(`/applications/${a.id}`, here)}>{a.name}</Link></td>
                                <td className="text-muted">{a.category_display}</td>
                                <td><span className={`badge bg-soft-${c} text-${c}`}>{a.status[0]?.toUpperCase()}{a.status.slice(1)}</span></td>
                              </tr>
                            );
                          })
                        )}
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

function SpecRow({ label, value, muted }: { label: string; value: string; muted: boolean }) {
  return (
    <>
      <dt className="col-5 text-muted fs-12">{label}</dt>
      <dd className={`col-7${muted ? " text-muted" : ""}`}>{value}</dd>
    </>
  );
}
