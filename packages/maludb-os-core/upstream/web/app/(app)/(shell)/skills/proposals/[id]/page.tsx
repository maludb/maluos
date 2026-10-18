import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ProposalBadge from "@/components/skills/ProposalBadge";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { skillProposalView } from "@/lib/schemas/skills";

export const metadata: Metadata = { title: "Skill proposal" };

const FINDING: Record<string, string> = {
  url: "Points somewhere outside",
  shell: "Looks like a command to run",
  addresses_the_reader_as_a_system: "Tells the reader how to behave",
  credentials: "Mentions a credential",
};

/**
 * Screen `skill-proposal-view` — a skill an agent wrote, beside the one it would replace, with what
 * the scan wants a person to read. Data: GET /skills/proposals/{id} (its author, the author's
 * manager, HR). Whoever approves this is deciding what that agent will do next time it meets the
 * task — and, once it is assigned wider, what other agents will.
 */
export default async function SkillProposalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/skills/proposals/${id}`, skillProposalView, ({ proposal: p, can }) => (
    <>
      <PageHeader title={p.skill_name} id="skill-proposal-view"
                  crumbs={[{ label: "HR", href: "/agents" }, { label: "Skills", href: "/skills" }, { label: `Proposal #${p.skill_proposal_id}` }]} back={{ href: "/skills", label: "Skills" }} />

      <div className="main-content" data-screen="skill-proposal-view" data-entity="skill_proposal" data-record-id={p.skill_proposal_id}>
        <div className="row">
          <div className="col-lg-8">
            {p.scan_findings.length > 0 && (
              <div className="alert alert-warning" id="skill-proposal-findings" role="alert">
                <div className="fw-semibold mb-2">Read these before deciding</div>
                <ul className="mb-0 ps-3">
                  {p.scan_findings.map((f, i) => (
                    <li key={i}>{FINDING[f.kind] ?? f.kind} <span className="text-muted">({f.file})</span>: <code className="text-break">{f.detail}</code></li>
                  ))}
                </ul>
              </div>
            )}
            <div className="card" id="skill-proposal-text-card">
              <div className="card-header"><h5 className="card-title mb-0">{p.is_change ? "The proposed version" : "The proposed skill"}</h5></div>
              <div className="card-body"><pre className="mb-0 fs-12 text-break" style={{ whiteSpace: "pre-wrap" }} id="skill-proposal-text">{p.skill_markdown ?? "(no text was kept)"}</pre></div>
            </div>
            {p.is_change && (
              <div className="card" id="skill-proposal-parent-card">
                <div className="card-header"><h5 className="card-title mb-0">What it would replace</h5></div>
                <div className="card-body"><pre className="mb-0 fs-12 text-break text-muted" style={{ whiteSpace: "pre-wrap" }} id="skill-proposal-parent-text">{p.parent_markdown ?? "(the current text could not be read)"}</pre></div>
              </div>
            )}
          </div>

          <div className="col-lg-4">
            <div className="card" id="skill-proposal-facts-card">
              <div className="card-header d-flex align-items-center"><h5 className="card-title mb-0">Proposal</h5><span className="ms-auto"><ProposalBadge status={p.status} /></span></div>
              <div className="card-body">
                <dl className="row mb-0">
                  <dt className="col-5 text-muted fs-12">Written by</dt><dd className="col-7"><Link href={withBack(`/agents/${p.agent.member_id}`, here)}>{p.agent.name}</Link></dd>
                  {p.agent_run_id !== null && (<><dt className="col-5 text-muted fs-12">During</dt><dd className="col-7"><Link href={withBack(`/ai/runs/${p.agent_run_id}`, here)}>run #{p.agent_run_id}</Link></dd></>)}
                  <dt className="col-5 text-muted fs-12">Files</dt><dd className="col-7">{p.file_count} — text only</dd>
                  <dt className="col-5 text-muted fs-12">Version</dt><dd className="col-7"><code title={p.bundle_hash}>{p.bundle_hash.slice(0, 12)}</code></dd>
                  <dt className="col-5 text-muted fs-12">Proposed</dt><dd className="col-7">{formatTs(p.created_at, timeZone)}</dd>
                  {p.decided_at && (<><dt className="col-5 text-muted fs-12">Decided</dt><dd className="col-7">{formatTs(p.decided_at, timeZone)}{p.decided_by ? <> · <Who who={{ id: p.decided_by_member_id, name: p.decided_by }} here={here} /></> : ""}</dd></>)}
                  {p.decision_note && (<><dt className="col-5 text-muted fs-12">Note</dt><dd className="col-7">{p.decision_note}</dd></>)}
                </dl>
              </div>
            </div>

            {can.decide && (
              <>
                <div className="card" id="skill-proposal-approve-card">
                  <div className="card-header"><h5 className="card-title mb-0">Approve</h5></div>
                  <div className="card-body">
                    <p className="fs-12 text-muted">It is switched on in MaluDB and given to {p.agent.name} only. Giving it to anyone else is a separate step on the Skills page.</p>
                    <ActionForm path="/skills/decide.php" confirm={`Approve ${p.skill_name}? ${p.agent.name} will follow it from the next run.`}>
                      <input type="hidden" name="skill_proposal" value={p.skill_proposal_id} />
                      <input type="hidden" name="decision" value="approve" />
                      <label className="form-label" htmlFor="skill-proposal-field-approve-note">A note <span className="text-muted">(optional)</span></label>
                      <textarea name="note" id="skill-proposal-field-approve-note" className="form-control mb-3" rows={2} maxLength={1000}></textarea>
                      <SubmitButton className="btn btn-success" id="skill-proposal-approve-btn"><i className="feather-check me-2"></i>Approve</SubmitButton>
                    </ActionForm>
                  </div>
                </div>
                <div className="card" id="skill-proposal-reject-card">
                  <div className="card-header"><h5 className="card-title mb-0">Reject</h5></div>
                  <div className="card-body">
                    <ActionForm path="/skills/decide.php">
                      <input type="hidden" name="skill_proposal" value={p.skill_proposal_id} />
                      <input type="hidden" name="decision" value="reject" />
                      <label className="form-label" htmlFor="skill-proposal-field-reject-note">Why — it stays with the proposal</label>
                      <textarea name="note" id="skill-proposal-field-reject-note" className="form-control mb-3" rows={2} maxLength={1000} required></textarea>
                      <SubmitButton className="btn btn-light-brand text-danger" id="skill-proposal-reject-btn">Reject</SubmitButton>
                    </ActionForm>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  ));
}
