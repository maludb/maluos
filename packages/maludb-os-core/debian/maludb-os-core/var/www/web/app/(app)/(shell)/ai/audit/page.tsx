import type { Metadata } from "next";
import AiOpsNav, { StateBadge } from "@/components/aiops/AiOpsNav";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { auditScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Audit · AI Ops" };

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");
/** Where a decision's subject lives — the route map knows agent_run, eval_run and ledger; eval_schedule, eval_result, system_event and probe have no page (step 2 of click-around gives the first two a parent id). */
const subjectHref = (kind: string | undefined, id: number | null | undefined): string | null => recordHref(kind, id);

/**
 * Screen `audit` — what the Auditor found about agents' work (db/145): regressions, runs below their pass mark, real
 * runs JEV failed or doubted, gaps in the audit trail; the open eval alerts; the real runs it graded. Findings advise —
 * a person decides. Data: GET /ai/audit/ (super-admin, Audit admins).
 */
export default async function AuditPage() {
  const here = await herePath();
  return renderScreen("/ai/audit/", auditScreen, (data) => (
    <>
      <PageHeader title="Audit" id="audit" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Audit" }]} />
      <div className="main-content" data-screen="audit">
        <AiOpsNav active="audit" />
        {data.agents.length === 0 && <div className="alert alert-soft-warning-message py-2">No Auditor has run yet.</div>}
        {data.agents.map((a) => (
          <div className={`alert ${a.mode === "live" ? "alert-soft-success-message" : "alert-soft-warning-message"} py-2`} key={a.id} id={`audit-agent-${a.id}`}>
            <strong>{a.name}</strong> is {a.mode === "live" ? "live — it starts evaluations, opens alerts and escalates." : "in shadow — it records what it would do and sends nothing."}{" "}
            <Link href={`/agents/${a.id}`}>Its page</Link>
          </div>
        ))}
        <div className="row">
          <div className="col-xl-7">
            <div className="card" id="audit-findings-card">
              <div className="card-header"><h5 className="card-title">Findings</h5></div>
              <div className="card-body p-0"><div className="table-responsive"><table className="table table-sm mb-0">
                <thead className="thead-light"><tr><th>When</th><th>Decision</th><th>About</th><th>Note</th></tr></thead>
                <tbody>
                  {data.decisions.length === 0 && <tr><td colSpan={4} className="text-center text-muted py-4">Nothing yet.</td></tr>}
                  {data.decisions.map((d) => {
                    const href = subjectHref(d.subject_kind, d.subject_id);
                    return (
                      <tr key={d.id} id={`audit-decision-${d.id}`}>
                        <td className="fs-12 text-muted text-nowrap">{fmt(d.at)}</td>
                        <td><StateBadge state={d.decision} />{d.mode === "shadow" && d.decision !== "record" && <span className="badge bg-light text-dark ms-1" title="Shadow: nothing was sent">would</span>}</td>
                        <td className="fs-12">{href ? <Link href={withBack(href, here)}>{d.subject}</Link> : d.subject}<div className="text-muted fs-11">{d.playbook.replace(/_/g, " ")}{d.agent_run_id !== null && <> · <Link href={withBack(`/ai/runs/${d.agent_run_id}`, here)}>run #{d.agent_run_id}</Link></>}</div></td>
                        <td className="fs-12 text-muted" style={{ overflowWrap: "anywhere" }}>{d.note}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table></div></div>
            </div>
          </div>
          <div className="col-xl-5">
            <div className="card" id="audit-alerts-card">
              <div className="card-header"><h5 className="card-title">Open eval alerts</h5></div>
              <div className="card-body">
                {data.alerts.length === 0 ? <p className="text-muted mb-0">None open.</p> : data.alerts.map((a) => (
                  <div key={a.id} className="mb-2" id={`audit-alert-${a.id}`}>
                    <div className="d-flex gap-2 align-items-center"><StateBadge state={a.severity === "critical" ? "failed" : "warning"} label={a.kind.replace(/_/g, " ")} />
                      <Link href={withBack(`/ai/evals/alerts/${a.id}`, here)} className="fs-12">Alert #{a.id}</Link><span className="fs-12 text-muted">{a.eval_set_id !== null ? <Link href={withBack(`/ai/evals/${a.eval_set_id}`, here)}>{a.eval_set_name}</Link> : a.eval_set_name}{a.agent_member_id !== null && <> · <Link href={withBack(`/agents/${a.agent_member_id}`, here)}>{a.agent_name ?? `#${a.agent_member_id}`}</Link></>} · {fmt(a.opened_at)}</span></div>
                    <div className="fs-13">{a.detail}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card" id="audit-traces-card">
              <div className="card-header"><h5 className="card-title">Real runs it graded</h5></div>
              <div className="card-body">
                {data.trace_grades.length === 0 ? <p className="text-muted mb-0">None yet — a set needs a trace-sampling schedule.</p> : data.trace_grades.map((g) => (
                  <div key={g.id} className="mb-2" id={`audit-trace-${g.id}`}>
                    <div className="d-flex gap-2 align-items-center">
                      {g.passed === null ? <StateBadge state="warning" label="unsure" /> : <StateBadge state={g.passed ? "passed" : "failed"} />}
                      <Link href={withBack(`/ai/runs/${g.agent_run_id}`, here)} className="fs-12">run #{g.agent_run_id}</Link>
                      <span className="fs-12 text-muted">{g.agent_member_id !== null ? <Link href={withBack(`/agents/${g.agent_member_id}`, here)}>{g.agent_name ?? `#${g.agent_member_id}`}</Link> : g.agent_name} · {fmt(g.graded_at)}</span>
                    </div>
                    {g.notes && <div className="fs-11 text-muted" style={{ overflowWrap: "anywhere" }}>{g.notes}</div>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
