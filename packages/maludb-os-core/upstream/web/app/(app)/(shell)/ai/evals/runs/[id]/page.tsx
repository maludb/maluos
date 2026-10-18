import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StateBadge, money } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import SubmitButton from "@/components/kit/SubmitButton";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { evalRunScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Eval run · AI Ops" };

/**
 * Screen `eval-run-view` — one eval run's per-case results. Data: GET /ai/evals/runs/{id}.
 * The score counts only what has been graded, so the card says what it covers; a case that
 * changed against the baseline is marked, because "regressed" is what a reader is looking for.
 */
export default async function EvalRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const here = await herePath();
  return renderScreen(`/ai/evals/runs/${id}`, evalRunScreen, ({ run: r, results, coverage, can }) => (
    <>
      <PageHeader title={`Eval run #${r.id}`} id="eval-run" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: r.eval_set_name, href: `/ai/evals/${r.eval_set_id}` }, { label: `Run #${r.id}` }]}
                  back={{ href: `/ai/evals/${r.eval_set_id}`, label: "the eval set" }} />
      <div className="main-content" data-screen="eval-run-view" data-entity="eval_run" data-record-id={r.id}>
        <div className="card" id="eval-run-card">
          <div className="card-header d-flex flex-wrap align-items-center gap-2"><h5 className="card-title mb-0">{r.score !== null ? `${Number(r.score)}% — ${r.cases_passed} of ${r.cases_total} passed` : "No score yet"}</h5>
            <span className="ms-auto d-flex gap-2 align-items-center"><span className="text-muted fs-12">pass at {Number(r.pass_threshold)}% · {r.trigger} · {money(r.cost, r.currency)}</span><StateBadge state={r.status} /></span></div>
          <div className="px-3 py-2 fs-12 border-bottom d-flex flex-wrap gap-3" id="eval-run-facts">
            <span>Agent: {r.agent_member_id !== null ? <Link href={withBack(`/agents/${r.agent_member_id}`, here)}>{r.agent_name ?? `#${r.agent_member_id}`}</Link> : "—"}</span>
            <span>Model: {r.model_id !== null ? <Link href={withBack(`/settings/models/${r.model_id}/edit`, here)}>{r.model_name ?? `#${r.model_id}`}</Link> : r.model_name ?? "—"}</span>
            {r.config_version_id !== null && r.agent_member_id !== null && <span>Config: <Link href={withBack(`/agents/versions?agent=${r.agent_member_id}`, here)}>version #{r.config_version_id}</Link></span>}
            {r.baseline_run_id !== null && <span>Against: <Link href={withBack(`/ai/evals/runs/${r.baseline_run_id}`, here)}>run #{r.baseline_run_id}</Link></span>}
            <span>Started by: {r.started_by ? <Who who={r.started_by} name={r.started_by.name ?? `#${r.started_by.id}`} here={here} /> : r.trigger}</span>
          </div>
          <div className={`px-3 py-2 fs-12 border-bottom ${coverage.awaiting > 0 ? "text-warning-emphasis bg-warning-subtle" : "text-muted"}`} id="eval-run-coverage">
            {coverage.graded} of {coverage.total} case(s) graded. {coverage.note}
          </div>
          <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0">
            <thead className="thead-light"><tr><th>Case</th><th>Result</th><th className="text-end">Score</th><th>Grader&apos;s notes</th></tr></thead>
            <tbody>
              {results.length === 0 && <tr><td colSpan={4} className="text-center text-muted py-5">No results.</td></tr>}
              {results.map((x) => (<tr key={x.id}><td>{x.case_title}
                {x.change === "regressed" && <span className="badge bg-danger ms-2">regressed</span>}
                {x.change === "fixed" && <span className="badge bg-success ms-2">fixed</span>}
                {x.change === "new" && <span className="badge bg-secondary ms-2">new case</span>}
                {x.agent_run_id !== null && <div><Link href={withBack(`/ai/runs/${x.agent_run_id}`, here)} className="fs-12 text-muted">agent run #{x.agent_run_id}</Link></div>}</td>
                <td>{x.is_graded
                  ? <StateBadge state={x.passed ? "passed" : "failed"} />
                  : <span className="badge bg-light text-dark" title="A person grades this case; until they do it is in neither column.">awaiting a person</span>}</td>
                <td className="text-end">{x.is_graded && x.score !== null ? Number(x.score) : "—"}</td>
                <td style={{ overflowWrap: "anywhere" }}>
                  {x.jev ? <JevDetail jev={x.jev} /> : <div style={{ whiteSpace: "pre-wrap" }}>{x.grader_notes ?? ""}</div>}
                  {x.graded_by_person && <div className="fs-11 text-muted mt-1">Graded by a person{x.jev ? " — JEV's own answers are kept above" : ""}.</div>}
                  {can.grade && (x.grader === "human" || x.grader === "jev") && (
                    <div className="d-flex flex-wrap gap-2 mt-2 align-items-center" id={`eval-result-grade-${x.id}`}>
                      <span className="fs-11 text-muted">{x.awaiting_person ? "Your grade:" : x.grader === "jev" ? "Spot-check:" : "Grade:"}</span>
                      <ActionForm path="/ai/evals/grade.php"><input type="hidden" name="eval_result" value={x.id} /><input type="hidden" name="passed" value="1" /><input type="hidden" name="score" value="100" />
                        <SubmitButton className="btn btn-sm btn-light-brand" id={`eval-result-pass-${x.id}`}>Passed</SubmitButton></ActionForm>
                      <ActionForm path="/ai/evals/grade.php"><input type="hidden" name="eval_result" value={x.id} /><input type="hidden" name="passed" value="0" /><input type="hidden" name="score" value="0" />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger" id={`eval-result-fail-${x.id}`}>Failed</SubmitButton></ActionForm>
                    </div>
                  )}
                </td></tr>))}
            </tbody></table></div></div>
        </div>
      </div>
    </>
  ));
}

type Jev = NonNullable<import("@/lib/schemas/aiops").EvalRunScreen["results"][number]["jev"]>;
const OUTCOME: Record<string, string> = { pass: "success", fail: "danger", uncertain: "warning" };

/** What JEV answered, per trial and check (db/144): outcome, what it said, and how sure it was. */
function JevDetail({ jev }: { jev: Jev }) {
  return (
    <div className="fs-12">
      {jev.trials.map((t) => (
        <div key={t.trial} className="mb-2">
          <div className="fw-semibold">Trial {t.trial}: {t.verdict === "awaiting" ? "unsure — a person decides" : t.verdict}
            {t.guard !== null && t.guard >= 0.5 && <span className="badge bg-soft-warning text-warning ms-1">the transcript addressed the grader ({t.guard.toFixed(2)})</span>}
          </div>
          {t.error && <div className="text-muted">{t.error}</div>}
          <div className="d-flex flex-wrap gap-1 mt-1">
            {t.checks.map((ch) => (
              <span key={ch.id} className={`badge bg-soft-${OUTCOME[ch.outcome] ?? "secondary"} text-${OUTCOME[ch.outcome] ?? "secondary"}`}
                    title={ch.confidence !== null ? `confidence ${ch.confidence}` : undefined}>
                {ch.id}: {ch.value !== null ? ch.value.toFixed(2) : ch.choice ?? (ch.level !== null ? `level ${ch.level}` : "—")}
                {ch.confidence !== null ? ` · ${ch.confidence.toFixed(2)}` : ""}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
