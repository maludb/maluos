"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useState } from "react";
import { useRecordForm } from "@/components/kit/useRecordForm";
import JevChecksEditor from "./JevChecksEditor";
import type { EvalCaseFormData } from "@/lib/schemas/aiops";
import { recordHref } from "@/lib/routes";

/**
 * Eval case form (screens `eval-case-add` / `eval-case-edit`). Arriving from a real call or run, the input and expected answer are
 * prefilled from it and saving goes through `eval_case_promote_trace`, which re-reads the trace server-side (the text here is only
 * what the person sees) and keeps the case's source.
 */
export default function EvalCaseForm({ data, back = null }: { data: EvalCaseFormData; back?: string | null }) {
  const c = data.case;
  const isEdit = c.id !== null;
  const promoting = !isEdit && data.from !== null;
  const record = `/ai/evals/${data.set.id}`;   // a case lives on its set's page: Cancel and a save land there without a trail (R5)
  const { state, pending, onSubmit } = useRecordForm(promoting ? "/ai/evals/promote.php" : "/ai/evals/case-save.php", back);
  const [grader, setGrader] = useState(c.grader);
  return (
    <>
      <PageHeader title={isEdit ? `Edit case — ${c.title}` : promoting ? "Make a case from real work" : "Write a case"} id="eval-case-form"
                  crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: data.set.name, href: record }, { label: isEdit ? "Edit case" : "New case" }]}
                  back={{ href: record, label: "the eval set" }}>
        <Link href={back ?? record} id="eval-case-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="eval-case-form" id="eval-case-form-save" className="btn btn-primary" disabled={pending}><i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span></button>
      </PageHeader>
      <div className="main-content" data-screen={isEdit ? "eval-case-edit" : "eval-case-add"} data-entity="eval_case" data-record-id={c.id ?? ""}>
        <ActionOutcome state={state} id="eval-case-form-errors" />
        <div className="row"><div className="col-lg-9"><div className="card stretch stretch-full"><div className="card-body">
          <form id="eval-case-form" onSubmit={onSubmit}>
            <input type="hidden" name="eval_set" value={data.set.id ?? ""} />
            {isEdit && <input type="hidden" name="eval_case" value={c.id ?? ""} />}
            {promoting && data.from && <input type="hidden" name={data.from.kind === "ledger" ? "ledger_entry" : "agent_run"} value={data.from.id} />}
            {promoting && data.from && (
              <p className="fs-12 text-muted" id="eval-case-form-source">Promoted from <Link href={recordHref(data.from.kind, data.from.id) ?? "#"}>{data.from.kind === "ledger" ? "call" : "run"} #{data.from.id}</Link>.</p>
            )}
            {isEdit && c.origin === "promoted_trace" && (c.source_run_id !== null || c.source_ledger_id !== null) && (
              <p className="fs-12 text-muted" id="eval-case-form-source">From real work: {c.source_run_id !== null
                ? <Link href={`/ai/runs/${c.source_run_id}`}>run #{c.source_run_id}</Link>
                : <Link href={`/ai/prompt-log/${c.source_ledger_id}`}>call #{c.source_ledger_id}</Link>}.</p>
            )}
            <FieldRow label="Title" htmlFor="eval-case-form-field-title"><input type="text" className="form-control" id="eval-case-form-field-title" name="title" defaultValue={c.title} maxLength={200} required /></FieldRow>
            <FieldRow label="What the agent is given" htmlFor="eval-case-form-field-input">
              <textarea className="form-control font-monospace" id="eval-case-form-field-input" name="input" rows={promoting ? 10 : 6} defaultValue={c.input} readOnly={promoting} required style={{ fontSize: 12 }}></textarea>
              <div className="form-text">{promoting ? "Exactly what the model was given — taken from the trace when you save, not from this box." : "Plain words, or JSON if the agent is given structured input."}</div>
            </FieldRow>
            <FieldRow label="A good answer" htmlFor="eval-case-form-field-expected">
              <textarea className="form-control font-monospace" id="eval-case-form-field-expected" name="expected" rows={4} defaultValue={c.expected ?? ""} readOnly={promoting} style={{ fontSize: 12 }}></textarea>
              {promoting && <div className="form-text">What it actually answered. Edit the case afterwards if that answer was not a good one.</div>}
            </FieldRow>
            <FieldRow label="Rubric" htmlFor="eval-case-form-field-rubric"><textarea className="form-control" id="eval-case-form-field-rubric" name="rubric" rows={3} defaultValue={c.rubric ?? ""} maxLength={8000} placeholder="Names the right expense category and says why"></textarea></FieldRow>
            {!promoting && (<>
              <FieldRow label="Graded by" htmlFor="eval-case-form-field-grader"><select className="form-select" id="eval-case-form-field-grader" name="grader" value={grader} onChange={(e) => setGrader(e.target.value)}>{data.options.graders.map((g) => <option value={g.id} key={g.id}>{g.name}</option>)}</select></FieldRow>
              {grader === "jev" && (
                <FieldRow label="JEV checks" htmlFor="eval-case-jev-add">
                  <JevChecksEditor initial={c.checks} caseId={c.id} rubricFieldId="eval-case-form-field-rubric" />
                </FieldRow>
              )}
              <FieldRow label="Weight" htmlFor="eval-case-form-field-weight"><input type="number" className="form-control" style={{ maxWidth: 120 }} id="eval-case-form-field-weight" name="weight" defaultValue={Number(c.weight)} min={0.1} max={100} step="0.1" /></FieldRow>
            </>)}
          </form>
        </div></div></div></div>
      </div>
    </>
  );
}
