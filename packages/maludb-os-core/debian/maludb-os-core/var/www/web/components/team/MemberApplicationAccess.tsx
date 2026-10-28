"use client";

import { useState } from "react";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import RoleChecklist from "@/components/applications/RoleChecklist";
import type { GrantableApplication, MemberApplicationGrant } from "@/lib/schemas/team";

const CAPABILITIES = ["read", "write", "admin"] as const;

/** "Payroll, Employee (write)" — the roles a grant gives and what they amount to; a bare capability without roles. */
function held(g: MemberApplicationGrant): string {
  if (g.roles.length > 0) return `${g.roles.map((r) => r.name + (r.withdrawn ? " — no longer offered" : "")).join(", ")} (${g.capability})`;
  return g.role_key ? `${g.role_name ?? g.role_key} (${g.capability})` : g.capability;
}

/** The roles an application publishes, as tick boxes (several may be held), else the capability picker. */
function AccessSelect({ app, current, id, compact = false }: { app: GrantableApplication | undefined; current?: MemberApplicationGrant; id: string; compact?: boolean }) {
  if (app && app.roles.length > 0) {
    return <RoleChecklist roles={app.roles} checked={current ? current.roles.map((r) => r.key) : []} idPrefix={id} compact={compact} />;
  }
  return (
    <select name="capability" id={id} className="form-select form-select-sm w-auto" defaultValue={current?.capability ?? "read"}>
      {CAPABILITIES.map((c) => <option value={c} key={c}>{c}</option>)}
    </select>
  );
}

/**
 * Screen `member-edit`, "Application access": what the member can use beyond the OS. Their own
 * grants are changed (role, or capability on an application without roles) and revoked here;
 * grants that reach them through a department or a site are named with where to change them.
 * The writes are the application access actions (access-grant / access-change / access-revoke).
 */
export default function MemberApplicationAccess({ memberId, grants, applications, canManage }: {
  memberId: number;
  grants: MemberApplicationGrant[];
  applications: GrantableApplication[];
  canManage: boolean;
}) {
  const [appId, setAppId] = useState("");
  const byId = new Map(applications.map((a) => [a.id, a]));
  const chosen = appId === "" ? undefined : byId.get(Number(appId));
  const own = grants.filter((g) => g.route === "member");
  const inherited = grants.filter((g) => g.route !== "member");

  return (
    <div className="card" id="member-edit-applications-card">
      <div className="card-header">
        <h5 className="card-title">Application access</h5>
        <span className="fs-11 text-muted">the roles an application publishes, and what each lets them do there</span>
      </div>
      <div className="card-body p-0">
        <div className="table-responsive">
          <table className="table table-hover mb-0" id="member-edit-applications-table">
            <thead className="thead-light"><tr><th>Application</th><th>Roles</th><th className="text-end">Actions</th></tr></thead>
            <tbody>
              {own.length === 0 && inherited.length === 0 && (
                <tr><td colSpan={3} className="text-center text-muted py-4">No application access yet.</td></tr>
              )}
              {own.map((g) => (
                <tr id={`member-application-grant-${g.id}`} key={g.id}>
                  <td>
                    <Link href={`/applications/${g.application_id}`}>{g.application_name}</Link>
                    {g.scope_name && <div className="fs-11 text-muted">at {g.scope_name}</div>}
                  </td>
                  <td>
                    <div className="fs-12">{held(g)}</div>
                    {canManage && (
                      <details id={`member-application-grant-${g.id}-change`}>
                        <summary className="fs-12">Change</summary>
                        <ActionForm path="/applications/access-change.php" className="mt-1">
                          <input type="hidden" name="application" value={g.application_id} />
                          <input type="hidden" name="application_access" value={g.id} />
                          <AccessSelect app={byId.get(g.application_id)} current={g} id={`member-application-grant-${g.id}-role`} compact />
                          <SubmitButton className="btn btn-sm btn-light-brand mt-1">Save</SubmitButton>
                        </ActionForm>
                      </details>
                    )}
                  </td>
                  <td className="text-end">
                    {canManage && (
                      <ActionForm path="/applications/access-revoke.php" confirm={`Revoke their access to ${g.application_name}${g.scope_name ? ` at ${g.scope_name}` : ""}?`}>
                        <input type="hidden" name="application" value={g.application_id} />
                        <input type="hidden" name="application_access" value={g.id} />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger">Revoke</SubmitButton>
                      </ActionForm>
                    )}
                  </td>
                </tr>
              ))}
              {inherited.map((g) => (
                <tr id={`member-application-grant-${g.id}`} key={g.id} className="text-muted">
                  <td>
                    <Link href={`/applications/${g.application_id}`}>{g.application_name}</Link>
                    {g.scope_name && <div className="fs-11">at {g.scope_name}</div>}
                  </td>
                  <td>{held(g)}</td>
                  <td className="text-end fs-12">
                    through{" "}
                    {g.route === "department" && g.through_id !== null
                      ? <Link href={`/team/departments/${g.through_id}`}>{g.through_name}</Link>
                      : <>everyone at {g.through_name}</>}
                    <div className="fs-11">change it on the <Link href={`/applications/${g.application_id}?tab=access`}>application's access</Link></div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canManage && (
          <div className="p-3 border-top">
            <ActionForm path="/applications/access-grant.php" id="member-edit-application-add-form" resetOnSuccess
                        className="d-flex flex-wrap gap-2 align-items-center">
              <input type="hidden" name="member" value={memberId} />
              <select name="application" id="member-form-field-application" className="form-select w-auto" required
                      value={appId} onChange={(e) => setAppId(e.target.value)}>
                <option value="">Grant an application…</option>
                {applications.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
              </select>
              {chosen && chosen.scope_kind !== "none" && (
                chosen.scopes.length === 0 ? (
                  <span className="fs-12 text-warning">It serves no {chosen.scope_kind === "location" ? "site" : "department"} yet — add one on the <Link href={`/applications/${chosen.id}`}>application</Link>.</span>
                ) : (
                  <select name="scope" id="member-form-field-application-scope" className="form-select form-select-sm w-auto" required defaultValue="" key={`scope-${chosen.id}`}>
                    <option value="">{chosen.scope_kind === "location" ? "Site…" : "Department…"}</option>
                    {chosen.scopes.map((s) => <option value={s.id} key={s.id}>{s.name}</option>)}
                  </select>
                )
              )}
              {chosen && (
                <div className="w-100" key={`role-${chosen.id}`}>
                  <AccessSelect app={chosen} id="member-form-field-application-role" />
                </div>
              )}
              <SubmitButton className="btn btn-primary" id="member-edit-application-add">Grant</SubmitButton>
            </ActionForm>
            {chosen && chosen.roles.length === 0 && (
              <div className="form-text">{chosen.name} publishes no roles yet, so the grant is a plain capability. A super-admin reads its roles on the application&rsquo;s Access tab.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
