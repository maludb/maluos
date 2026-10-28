import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StateBadge } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { evalAlertScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Eval alert · AI Ops" };

/** Screen `eval-alert-view` — one alert: scores against baseline, the run behind it, what was done. Data: GET /ai/evals/alerts/{id}. */
export default async function EvalAlertPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();
  return renderScreen(`/ai/evals/alerts/${id}`, evalAlertScreen, ({ alert: a, can }) => (
    <>
      <PageHeader title={`Alert — ${a.eval_set_name}`} id="eval-alert" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Watch", href: "/ai/evals/watch" }, { label: `Alert #${a.id}` }]} back={{ href: "/ai/evals/watch", label: "Watch" }}>
        <Link href={withBack(`/ai/evals/${a.eval_set_id}`, here)} className="btn btn-light-brand" id="eval-alert-set-btn"><i className="feather-list me-2"></i><span>The eval set</span></Link>
      </PageHeader>
      <div className="main-content" data-screen="eval-alert-view" data-entity="eval_alert" data-record-id={a.id}>
        <div className="card" id="eval-alert-card">
          <div className="card-header d-flex flex-wrap gap-2 align-items-center"><h5 className="card-title mb-0">{a.kind.replace(/_/g, " ")}</h5><span className="ms-auto d-flex gap-2"><span className="badge bg-soft-warning text-warning">{a.severity}</span><StateBadge state={a.status} /></span></div>
          <div className="card-body">
            <p style={{ whiteSpace: "pre-wrap" }}>{a.detail}</p>
            <dl className="row mb-0">
              <dt className="col-sm-3 text-muted fs-12">Agent</dt><dd className="col-sm-9">{a.agent ? <Link href={withBack(`/agents/${a.agent.id}`, here)}>{a.agent.name ?? "Agent"}</Link> : "—"}</dd>
              <dt className="col-sm-3 text-muted fs-12">Score / baseline</dt><dd className="col-sm-9">{a.score !== null ? Number(a.score) : "—"} / {a.baseline_score !== null ? Number(a.baseline_score) : "—"}</dd>
              <dt className="col-sm-3 text-muted fs-12">Run</dt><dd className="col-sm-9">{a.eval_run_id !== null ? <Link href={withBack(`/ai/evals/runs/${a.eval_run_id}`, here)}>Eval run #{a.eval_run_id}</Link> : "—"}</dd>
              <dt className="col-sm-3 text-muted fs-12">Opened</dt><dd className="col-sm-9">{formatTs(a.opened_at, timeZone)}</dd>
              {a.acknowledged_at && (<><dt className="col-sm-3 text-muted fs-12">Acknowledged</dt><dd className="col-sm-9">{formatTs(a.acknowledged_at, timeZone)}{a.acknowledged_by && <> by <Who who={a.acknowledged_by} name={a.acknowledged_by.name ?? `#${a.acknowledged_by.id}`} here={here} /></>}</dd></>)}
              {a.resolution && (<><dt className="col-sm-3 text-muted fs-12">What was done</dt><dd className="col-sm-9" style={{ whiteSpace: "pre-wrap" }}>{a.resolution}</dd></>)}
            </dl>
            {can.act && a.status !== "resolved" && (
              <div className="d-flex flex-column gap-3 mt-3 border-top pt-3">
                {a.status === "open" && <ActionForm path="/ai/evals/alert-ack.php"><input type="hidden" name="eval_alert" value={a.id} /><SubmitButton className="btn btn-light-brand" id="eval-alert-ack-btn">Acknowledge</SubmitButton></ActionForm>}
                <ActionForm path="/ai/evals/alert-resolve.php" id="eval-alert-resolve-form"><input type="hidden" name="eval_alert" value={a.id} />
                  <textarea name="resolution" className="form-control mb-2" rows={2} placeholder="What was done about it" aria-label="Resolution" maxLength={2000} required></textarea>
                  <SubmitButton className="btn btn-primary" id="eval-alert-resolve-btn">Resolve</SubmitButton></ActionForm>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  ));
}
