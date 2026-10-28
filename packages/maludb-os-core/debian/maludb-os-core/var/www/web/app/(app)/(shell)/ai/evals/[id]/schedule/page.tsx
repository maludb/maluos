import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NoRunner } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { evalScheduleScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Eval schedule · AI Ops" };

/** Screen `eval-schedule-add` — put a set on a standing schedule. Data: GET /ai/evals/schedule?eval_set={id} (mod:evals). Saved and listed; nothing executes it yet. */
export default async function EvalSchedulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return renderScreen(`/ai/evals/schedule?eval_set=${id}`, evalScheduleScreen, ({ set, schedules, options }) => (
    <>
      <PageHeader title={`Schedule — ${set.name}`} id="eval-schedule" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: set.name, href: `/ai/evals/${set.id}` }, { label: "Schedule" }]}>
        <Link href={`/ai/evals/${set.id}`} className="btn btn-light-brand" id="eval-schedule-back">Back to the set</Link>
      </PageHeader>
      <div className="main-content" data-screen="eval-schedule-add" data-entity="eval_set" data-record-id={set.id ?? ""}>
        <NoRunner note="A schedule is saved and shown on the Audit watch, but nothing will run it until the eval runner is built — its next run stays empty." />
        <div className="row">
          <div className="col-lg-6"><div className="card" id="eval-schedule-form-card"><div className="card-header"><h5 className="card-title">Add a schedule</h5></div><div className="card-body">
            <ActionForm path="/ai/evals/schedule-save.php" id="eval-schedule-form" resetOnSuccess>
              <input type="hidden" name="eval_set" value={set.id ?? ""} />
              <div className="mb-3"><label className="form-label" htmlFor="eval-schedule-field-kind">What happens</label>
                <select className="form-select" id="eval-schedule-field-kind" name="kind" defaultValue="scheduled_run">{options.kinds.map((k) => <option value={k.id} key={k.id}>{k.name}</option>)}</select></div>
              <div className="mb-3"><label className="form-label" htmlFor="eval-schedule-field-cadence">How often</label>
                <select className="form-select" id="eval-schedule-field-cadence" name="cadence" defaultValue="weekly">{options.cadences.map((k) => <option value={k.id} key={k.id}>{k.name}</option>)}</select></div>
              <div className="mb-3"><label className="form-label" htmlFor="eval-schedule-field-sample">Sample size</label>
                <input type="number" className="form-control" style={{ maxWidth: 160 }} id="eval-schedule-field-sample" name="sample_size" min={1} max={1000} />
                <div className="form-text">Needed when grading a sample of real work: how many runs each time.</div></div>
              <div className="mb-3"><label className="form-label" htmlFor="eval-schedule-field-delta">Alert when the score drops by</label>
                <div className="input-group" style={{ maxWidth: 180 }}><input type="number" className="form-control" id="eval-schedule-field-delta" name="regression_delta" defaultValue={5} min={0} max={100} step="0.5" /><span className="input-group-text">points</span></div></div>
              <SubmitButton className="btn btn-primary" id="eval-schedule-save-btn">Save schedule</SubmitButton>
            </ActionForm>
          </div></div></div>
          <div className="col-lg-6"><div className="card" id="eval-schedule-list-card"><div className="card-header"><h5 className="card-title">On this set</h5></div><div className="card-body">
            {schedules.length === 0 ? <p className="text-muted mb-0">No schedule yet.</p> : schedules.map((h) => (
              <div key={h.id} id={`eval-schedule-${h.id}`} className="border rounded p-3 mb-2 d-flex flex-wrap gap-2 align-items-center">
                <div className="flex-grow-1"><div className="fw-semibold">{h.cadence_label} — {h.kind_label.toLowerCase()}{h.sample_size ? ` (${h.sample_size})` : ""}</div>
                  <div className="fs-12 text-muted">Alert at a drop of {Number(h.regression_delta)} points · {h.active ? "on" : "off"}</div></div>
                <ActionForm path="/ai/evals/schedule-save.php"><input type="hidden" name="eval_set" value={set.id ?? ""} /><input type="hidden" name="schedule" value={h.id} />
                  <input type="hidden" name="kind" value={h.kind} /><input type="hidden" name="cadence" value={h.cadence} /><input type="hidden" name="sample_size" value={h.sample_size ?? ""} />
                  <input type="hidden" name="regression_delta" value={h.regression_delta} /><input type="hidden" name="active" value={h.active ? "0" : "1"} />
                  <SubmitButton className="btn btn-sm btn-light-brand">{h.active ? "Switch off" : "Switch on"}</SubmitButton></ActionForm>
              </div>))}
          </div></div></div>
        </div>
      </div>
    </>
  ));
}
