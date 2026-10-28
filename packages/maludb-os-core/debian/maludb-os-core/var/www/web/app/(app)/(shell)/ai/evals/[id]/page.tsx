import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NoRunner, StateBadge } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { evalSetScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Eval set · AI Ops" };

/** Screen `eval-set-view` — one set: cases, schedules, runs. Data: GET /ai/evals/{id}. "Run now" is offered, and answers honestly that there is no runner yet. */
export default async function EvalSetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const here = await herePath();
  return renderScreen(`/ai/evals/${id}`, evalSetScreen, ({ set: s, cases, schedules, runs, runner_note, can, calibration }) => (
    <>
      <PageHeader title={s.name} id="eval-set" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: s.name }]} back={{ href: "/ai/evals", label: "Evals" }}>
        {can.write && <Link href={withBack(`/ai/evals/${s.id}/edit`, here)} id="eval-set-edit-btn" className="btn btn-light-brand"><i className="feather-edit-2 me-2"></i><span>Edit</span></Link>}
        {can.write && <Link href={withBack(`/ai/evals/${s.id}/cases/new`, here)} id="eval-set-case-add-btn" className="btn btn-primary"><i className="feather-plus me-2"></i><span>Write a case</span></Link>}
      </PageHeader>
      <div className="main-content" data-screen="eval-set-view" data-entity="eval_set" data-record-id={s.id ?? ""}>
        <NoRunner note={runner_note} />
        <div className="row">
          <div className="col-lg-8">
            <div className="card" id="eval-set-cases-card">
              <div className="card-header"><h5 className="card-title">Cases <span className="text-muted fs-12 fw-normal">({s.active_case_count} active of {s.case_count})</span></h5></div>
              <div className="card-body">
                {cases.length === 0 && <p className="text-muted mb-0">No cases yet. A case is one thing the agent is given, and what a good answer looks like.</p>}
                {cases.map((c) => (
                  <div key={c.id} id={`eval-case-${c.id}`} className={`border rounded p-3 mb-2 ${c.active ? "" : "opacity-75"}`}>
                    <div className="d-flex flex-wrap align-items-center gap-2">
                      {can.write ? <Link href={withBack(`/ai/evals/cases/${c.id}/edit`, here)} className="fw-semibold">{c.title}</Link> : <span className="fw-semibold">{c.title}</span>}
                      {!c.active && <span className="badge bg-soft-secondary text-secondary">Off</span>}
                      {c.origin === "promoted_trace" && (c.source_run_id !== null ? <Link href={withBack(`/ai/runs/${c.source_run_id}`, here)} className="badge bg-soft-info text-info" title={`From run #${c.source_run_id}`}>From real work</Link>
                        : c.source_ledger_id !== null ? <Link href={withBack(`/ai/prompt-log/${c.source_ledger_id}`, here)} className="badge bg-soft-info text-info" title={`From call #${c.source_ledger_id}`}>From real work</Link>
                        : <span className="badge bg-soft-info text-info">From real work</span>)}
                      <span className="text-muted fs-12">{c.grader_label} · weight {Number(c.weight)}</span>
                      {can.write && (
                        <ActionForm path="/ai/evals/case-active.php" className="ms-auto"><input type="hidden" name="eval_case" value={c.id ?? ""} /><input type="hidden" name="active" value={c.active ? "0" : "1"} />
                          <SubmitButton className="btn btn-sm btn-light-brand">{c.active ? "Switch off" : "Switch on"}</SubmitButton></ActionForm>
                      )}
                    </div>
                    <div className="text-muted fs-12 mt-1" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 72, overflow: "hidden" }}>{c.input.slice(0, 400)}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card" id="eval-set-runs-card">
              <div className="card-header"><h5 className="card-title">Runs</h5></div>
              <div className="card-body">
                {runs.length === 0 ? <p className="text-muted mb-0">This set has never run.</p> : (
                  <ul className="list-unstyled mb-0">{runs.map((r) => (<li key={r.id} className="d-flex flex-wrap gap-2 py-1"><Link href={withBack(`/ai/evals/runs/${r.id}`, here)}>Run #{r.id}</Link><StateBadge state={r.status} />
                    <span className="text-muted fs-12">{r.score !== null ? `${Number(r.score)}% (${r.cases_passed}/${r.cases_total})` : r.trigger}</span></li>))}</ul>)}
              </div>
            </div>
            {calibration.length > 0 && (
              <div className="card" id="eval-set-calibration-card">
                <div className="card-header"><h5 className="card-title">How far JEV&apos;s checks can be trusted</h5></div>
                <div className="card-body p-0"><div className="table-responsive"><table className="table table-sm mb-0">
                  <thead className="thead-light"><tr><th>Check</th><th className="text-end">Pass</th><th className="text-end">Fail</th><th className="text-end">Unsure</th><th className="text-end">A person agreed</th></tr></thead>
                  <tbody>{calibration.map((k) => (
                    <tr key={k.check_id} id={`eval-calibration-${k.check_id}`}><td className="font-monospace fs-12">{k.check_id}</td>
                      <td className="text-end">{k.passes}</td><td className="text-end">{k.fails}</td><td className="text-end">{k.uncertain}</td>
                      <td className="text-end">{k.person_graded > 0 ? `${k.person_agreed} of ${k.person_graded}` : "—"}</td></tr>))}</tbody>
                </table></div>
                <p className="fs-11 text-muted px-3 py-2 mb-0">Counted over every trial JEV graded. Where people often disagree with a check, reword it or move its pass mark; where it is often unsure, it sends many cases to people.</p></div>
              </div>
            )}
          </div>
          <div className="col-lg-4">
            <div className="card" id="eval-set-facts-card">
              <div className="card-header d-flex align-items-center gap-2"><h5 className="card-title mb-0">Set</h5><span className="ms-auto"><StateBadge state={s.status} label={s.status_label} /></span></div>
              <div className="card-body">
                <dl className="row mb-0">
                  <dt className="col-5 text-muted fs-12">For</dt><dd className="col-7">{s.agent ? <Link href={withBack(`/agents/${s.agent.id}`, here)}>{s.agent.name ?? "Agent"}</Link> : `Role: ${s.role_key}`}</dd>
                  <dt className="col-5 text-muted fs-12">Department</dt><dd className="col-7">{s.department_id !== null ? <Link href={withBack(`/team/departments/${s.department_id}`, here)}>{s.department_name ?? `#${s.department_id}`}</Link> : s.department_name ?? "—"}</dd>
                  <dt className="col-5 text-muted fs-12">Pass at</dt><dd className="col-7">{Number(s.pass_threshold)}%</dd>
                </dl>
                {s.description && <p className="mt-2 mb-0" style={{ whiteSpace: "pre-wrap" }}>{s.description}</p>}
                {can.run && (
                  <ActionForm path="/ai/evals/run.php" className="mt-3" id="eval-set-run-form"><input type="hidden" name="eval_set" value={s.id ?? ""} />
                    <SubmitButton className="btn btn-light-brand" id="eval-set-run-btn"><i className="feather-play me-2"></i>Run now</SubmitButton></ActionForm>
                )}
              </div>
            </div>
            <div className="card" id="eval-set-schedules-card">
              <div className="card-header"><h5 className="card-title">Standing schedule</h5>{can.write && <Link href={`/ai/evals/${s.id}/schedule`} className="btn btn-sm btn-light-brand" id="eval-set-schedule-btn">Set one</Link>}</div>
              <div className="card-body">
                {schedules.length === 0 ? <p className="text-muted mb-0">Not on a schedule.</p> : (
                  <ul className="list-unstyled mb-0">{schedules.map((h) => (<li key={h.id} className="py-1">{h.cadence_label} — {h.kind_label.toLowerCase()}{h.sample_size ? ` (${h.sample_size})` : ""} {!h.active && <span className="badge bg-soft-secondary text-secondary">Off</span>}
                    <div className="fs-12 text-muted">Alert at a drop of {Number(h.regression_delta)} points · next run: {h.next_run_at ?? "never — no runner yet"}</div></li>))}</ul>)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
