import type { Metadata } from "next";
import AssignForm from "@/components/skills/AssignForm";
import KindBadge from "@/components/skills/KindBadge";
import ProposalBadge from "@/components/skills/ProposalBadge";
import ActionForm from "@/components/kit/ActionForm";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { skillsScreen, type SkillAssignment } from "@/lib/schemas/skills";

export const metadata: Metadata = { title: "Skills" };

const STATUSES = ["proposed", "approved", "rejected", "all"];

function reaches(a: SkillAssignment): string {
  if (a.scope_kind === "org") return "Everyone";
  if (a.scope_kind === "department") return a.department?.name ?? "A department";
  if (a.scope_kind === "role") return `Role: ${a.role_key}`;
  if (a.scope_kind === "application") return `Application: ${a.application?.name ?? "—"}`;
  return a.agent?.name ?? "One agent";
}

/**
 * Screen `skills` — which MaluDB skills reach whom, and what agents have written that waits for a
 * person. Data: GET /skills?status= (insiders; the proposals are the caller's own or ones they may
 * decide). Skills live in MaluDB; this screen is who gets which.
 */
export default async function SkillsPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const sp = await searchParams;
  const status = sp.status && STATUSES.includes(sp.status) ? sp.status : "proposed";
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/skills?status=${status}`, skillsScreen, (data) => (
    <>
      <PageHeader title="Skills" id="skills" crumbs={[{ label: "HR", href: "/agents" }, { label: "Skills" }]} />

      <div className="main-content" data-screen="skills">
        <div className="row">
          <div className="col-lg-8">
            <div className="card" id="skills-proposals-card">
              <div className="card-header d-flex flex-wrap gap-2 align-items-center">
                <h5 className="card-title mb-0">Written by agents</h5>
                <div className="ms-auto">
                  <FilterSelect id="skills-filter-status" name="status" value={status}
                                options={STATUSES.map((s) => ({ value: s, label: s === "proposed" ? "Waiting for review" : s === "all" ? "All" : s }))} />
                </div>
              </div>
              <div className="card-body p-0">
                <div className="table-responsive">
                  <table className="table table-hover mb-0" id="skills-proposals-table">
                    <thead className="thead-light"><tr><th>Skill</th><th>Written by</th><th>Flags</th><th>When</th><th>Status</th></tr></thead>
                    <tbody>
                      {data.proposals.length === 0 ? (
                        <tr><td colSpan={5} className="text-center text-muted py-5">
                          {status === "proposed" ? "No agent-written skill is waiting for review." : "Nothing here."}
                        </td></tr>
                      ) : data.proposals.map((p) => (
                        <tr id={`skill-proposal-row-${p.skill_proposal_id}`} key={p.skill_proposal_id}>
                          <td>
                            <Link href={withBack(`/skills/proposals/${p.skill_proposal_id}`, here)} className="fw-semibold">{p.skill_name}</Link>
                            <div className="fs-12 text-muted">{p.is_change ? "changes an existing skill" : "a new skill"} · {p.file_count} file{p.file_count === 1 ? "" : "s"}</div>
                          </td>
                          <td><Link href={withBack(`/agents/${p.agent.member_id}`, here)}>{p.agent.name}</Link></td>
                          <td>{p.scan_findings.length === 0 ? <span className="text-muted">none</span>
                            : <span className="badge bg-soft-danger text-danger">{p.scan_findings.length} to read</span>}</td>
                          <td className="text-muted">{formatTs(p.created_at, timeZone, false)}</td>
                          <td><ProposalBadge status={p.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="card" id="skills-assignments-card">
              <div className="card-header"><h5 className="card-title mb-0">Who has which skill</h5></div>
              <div className="card-body p-0">
                <div className="table-responsive">
                  <table className="table table-hover mb-0" id="skills-assignments-table">
                    <thead className="thead-light"><tr><th>Skill</th><th>Reaches</th><th>Version</th><th>Assigned</th><th></th></tr></thead>
                    <tbody>
                      {data.assignments.length === 0 ? (
                        <tr><td colSpan={5} className="text-center text-muted py-5">No skill is assigned to anyone yet.</td></tr>
                      ) : data.assignments.map((a) => (
                        <tr id={`skill-assignment-row-${a.skill_assignment_id}`} key={a.skill_assignment_id}>
                          <td><span className="fw-semibold">{a.skill_name}</span> <KindBadge kind={a.kind} />{a.note && <div className="fs-12 text-muted">{a.note}</div>}</td>
                          <td>{a.agent ? <Link href={withBack(`/agents/${a.agent.member_id}`, here)}>{reaches(a)}</Link>
                            : a.application ? <Link href={withBack(`/applications/${a.application.id}?tab=expertise`, here)}>{reaches(a)}</Link>
                            : a.scope_kind === "department" && a.department ? <Link href={withBack(`/team/departments/${a.department.id}`, here)}>{reaches(a)}</Link> : reaches(a)}</td>
                          <td>{a.pinned_bundle_hash
                            ? <span className="badge bg-soft-warning text-warning" title={a.pinned_bundle_hash}>pinned {a.pinned_bundle_hash.slice(0, 10)}</span>
                            : <span className="text-muted">newest</span>}</td>
                          <td className="text-muted">{formatTs(a.created_at, timeZone, false)}{a.assigned_by && <div className="fs-12"><Who who={{ id: a.assigned_by_member_id, name: a.assigned_by }} here={here} /></div>}</td>
                          <td className="text-end">
                            {data.can.assign && (
                              <ActionForm path="/skills/unassign.php" confirm={`Withdraw ${a.skill_name} from ${reaches(a)}? Agents lose it at their next run.`}>
                                <input type="hidden" name="skill_assignment" value={a.skill_assignment_id} />
                                <SubmitButton className="btn btn-sm btn-light-brand" id={`skill-unassign-btn-${a.skill_assignment_id}`}>Withdraw</SubmitButton>
                              </ActionForm>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <div className="col-lg-4">
            {data.can.assign && (
              <div className="card" id="skills-assign-card">
                <div className="card-header"><h5 className="card-title mb-0">Assign a skill</h5></div>
                <div className="card-body"><AssignForm options={data.options} anywhere={data.can.assign_anywhere} /></div>
              </div>
            )}
            <div className="card" id="skills-about-card">
              <div className="card-body fs-12 text-muted">
                <p className="mb-2">A skill is a short written procedure an agent reads before it works. Skills live in MaluDB; this page decides who gets which.</p>
                <p className="mb-2">An agent receives every skill that reaches it — its own, its role&apos;s, its departments&apos; and the organisation&apos;s — read-only, at the start of each run. The most specific assignment of a name wins, so one agent can be pinned to a version while the rest follow the newest.</p>
                <p className="mb-0">A skill an agent writes reaches nobody until a person approves it, and then only its author until it is assigned wider here.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
