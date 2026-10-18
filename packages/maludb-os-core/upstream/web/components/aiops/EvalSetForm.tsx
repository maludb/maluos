"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import JevChecksEditor from "./JevChecksEditor";
import type { JevCheck } from "@/lib/schemas/aiops";
import type { EvalSetFormData } from "@/lib/schemas/aiops";

/** Eval set form (screen `eval-set-add`, and the set's edit). A set is for ONE agent, or for a role any agent in it must pass. */
export default function EvalSetForm({ data, back = null }: { data: EvalSetFormData; back?: string | null }) {
  const s = data.set;
  const isEdit = s.id !== null;
  const record = isEdit ? `/ai/evals/${s.id}` : "/ai/evals";   // where Cancel and a save land without a trail (R5)
  const { state, pending, onSubmit } = useRecordForm("/ai/evals/save.php", back);
  return (
    <>
      <PageHeader title={isEdit ? `Edit ${s.name}` : "New eval set"} id="eval-set-form" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, ...(isEdit ? [{ label: s.name, href: record }, { label: "Edit" }] : [{ label: "New" }])]}
                  back={{ href: record, label: isEdit ? "the eval set" : "Evals" }}>
        <Link href={back ?? record} id="eval-set-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="eval-set-form" id="eval-set-form-save" className="btn btn-primary" disabled={pending}><i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span></button>
      </PageHeader>
      <div className="main-content" data-screen="eval-set-add" data-entity="eval_set" data-record-id={s.id ?? ""}>
        <ActionOutcome state={state} id="eval-set-form-errors" />
        <div className="row"><div className="col-lg-9"><div className="card stretch stretch-full"><div className="card-body">
          <form id="eval-set-form" onSubmit={onSubmit}>
            {isEdit && <input type="hidden" name="eval_set" value={s.id ?? ""} />}
            <FieldRow label="Name" htmlFor="eval-set-form-field-name"><input type="text" className="form-control" id="eval-set-form-field-name" name="name" defaultValue={s.name} maxLength={160} required placeholder="Bookkeeping basics" /></FieldRow>
            <FieldRow label="For agent" htmlFor="eval-set-form-field-agent">
              <select className="form-select" id="eval-set-form-field-agent" name="agent" defaultValue={s.agent?.id ?? ""}><option value="">No single agent — a role (below)</option>{data.options.agents.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}</select>
            </FieldRow>
            <FieldRow label="Or for role" htmlFor="eval-set-form-field-role"><input type="text" className="form-control" id="eval-set-form-field-role" name="role_key" defaultValue={s.role_key ?? ""} maxLength={80} placeholder="bookkeeper" />
              <div className="form-text">A set needs an agent or a role. A role&apos;s set is what any agent hired into that role is measured against.</div></FieldRow>
            <FieldRow label="Department" htmlFor="eval-set-form-field-department">
              <select className="form-select" id="eval-set-form-field-department" name="department" defaultValue={s.department_id ?? ""}><option value="">None</option>{data.options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}</select></FieldRow>
            <FieldRow label="Pass at" htmlFor="eval-set-form-field-threshold"><div className="input-group" style={{ maxWidth: 160 }}><input type="number" className="form-control" id="eval-set-form-field-threshold" name="pass_threshold" defaultValue={Number(s.pass_threshold)} min={0} max={100} step="0.5" required /><span className="input-group-text">%</span></div></FieldRow>
            <FieldRow label="Checks on real work" htmlFor="eval-case-jev-add">
              <JevChecksEditor initial={(s.trace_checks ?? null) as JevCheck[] | null} caseId={null} rubricFieldId={null} fieldName="trace_checks" allowEmpty />
              <div className="form-text">What the Auditor asks JEV about this agent&apos;s sampled REAL runs, on a trace-sampling schedule. None: it uses the standard four (task done, grounded, in scope, nothing unrequested).</div>
            </FieldRow>
            <FieldRow label="Status" htmlFor="eval-set-form-field-status"><select className="form-select" id="eval-set-form-field-status" name="status" defaultValue={s.status}>{data.options.statuses.map((x) => <option value={x.id} key={x.id}>{x.name}</option>)}</select></FieldRow>
            <FieldRow label="What it checks" htmlFor="eval-set-form-field-description"><textarea className="form-control" id="eval-set-form-field-description" name="description" rows={3} defaultValue={s.description ?? ""} maxLength={4000}></textarea></FieldRow>
          </form>
        </div></div></div></div>
      </div>
    </>
  );
}
