"use client";

import DeleteDepartment from "./DeleteDepartment";
import { DeleteBlockers } from "./DepartmentTies";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { DepartmentFormData } from "@/lib/schemas/team";

/**
 * Department form (screens `department-add` / `department-edit`) — app/views/team/
 * department-form.php. The defaults PHP works out (reports to the Front Office; a new department
 * starts at an onsite office — db/074) arrive as selected_parent_id / selected_location_id.
 */
export default function DepartmentForm({ data, back: carried = null }: { data: DepartmentFormData; back?: string | null }) {
  const { department: d, options } = data;
  const isEdit = d.id !== null;
  const isFrontOffice = d.system_key === "front_office";
  // Where the form was opened from (click-around R5), else the department on edit and the list on create.
  const parent = isEdit ? `/team/departments/${d.id}` : "/team/departments";
  const back = carried ?? parent;
  const { state, pending, onSubmit } = useRecordForm("/team/departments/save.php", carried);

  return (
    <>
      <PageHeader title={isEdit ? "Edit department" : "New department"} id="department-form"
                  crumbs={[{ label: "Departments", href: "/team/departments" }, ...(isEdit ? [{ label: d.name, href: parent }] : []), { label: isEdit ? "Edit" : "New" }]}
                  back={{ href: parent, label: isEdit ? "the department" : "Departments" }}>
        <Link href={back} id="department-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="department-form" id="department-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
        {isEdit && data.can.delete && <DeleteDepartment departmentId={d.id as number} blockers={data.delete_blockers} buttonId="department-form-delete" />}
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "department-edit" : "department-add"} data-entity="department" data-record-id={d.id ?? ""}>
        <ActionOutcome state={state} id="department-form-errors" />
        {isEdit && data.can.delete && <DeleteBlockers ties={data.ties} />}
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="department-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="department" value={d.id ?? ""} />}
                  <FieldRow label="Name" htmlFor="department-form-field-name">
                    <input type="text" className="form-control" id="department-form-field-name" name="name"
                           defaultValue={d.name} maxLength={120} required />
                    {d.is_system && (
                      <div className="form-text">A standing department can be renamed; its duty (<code>{d.system_key}</code>) stays.</div>
                    )}
                  </FieldRow>
                  <FieldRow label="Description" htmlFor="department-form-field-description">
                    <textarea className="form-control" id="department-form-field-description" name="description" rows={2}
                              maxLength={2000} defaultValue={d.description ?? ""}></textarea>
                  </FieldRow>
                  <FieldRow label="Handbook" htmlFor="department-form-field-handbook">
                    <textarea className="form-control font-monospace" id="department-form-field-handbook" name="handbook_markdown" rows={10}
                              maxLength={60000} defaultValue={d.handbook_markdown ?? ""}></textarea>
                    <div className="form-text">How this department works, in Markdown. Every agent in it reads the first 12,000 characters at the start of each run.</div>
                  </FieldRow>
                  <FieldRow label="Manager" htmlFor="department-form-field-manager">
                    <select className="form-select" id="department-form-field-manager" name="manager_member_id"
                            defaultValue={d.manager_member_id ?? ""}>
                      <option value="">No manager</option>
                      {options.members.map((m) => <option value={m.id} key={m.id}>{m.name}{m.kind === "agent" ? " (agent)" : ""}</option>)}
                    </select>
                    <div className="form-text">The manager administers this department, and approves what its agents pause on.</div>
                  </FieldRow>
                  <FieldRow label="Reports to" htmlFor="department-form-field-parent">
                    {isFrontOffice ? (
                      <div className="form-control-plaintext" id="department-form-field-parent">Nobody — this is the top of the organisation.</div>
                    ) : (
                      <>
                        <select className="form-select" id="department-form-field-parent" name="parent_id"
                                defaultValue={data.selected_parent_id ?? ""}>
                          {options.departments.filter((o) => o.id !== d.id).map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
                        </select>
                        <div className="form-text">Every department reports to the Front Office, directly or through the department named here.</div>
                      </>
                    )}
                  </FieldRow>
                  <FieldRow label="Works at" htmlFor="department-form-field-location">
                    <select className="form-select" id="department-form-field-location" name="home_location_id"
                            defaultValue={data.selected_location_id ?? ""}>
                      <option value="">Unassigned</option>
                      {options.locations.map((l) => (
                        <option value={l.id} key={l.id}>{l.name} ({l.kind}{l.siting !== null ? ` · ${l.siting}` : ""})</option>
                      ))}
                    </select>
                    <div className="form-text">
                      The office this department works in — where its agents run. Any location will do; the default is an
                      onsite office, on a machine we run.
                    </div>
                  </FieldRow>
                  <FieldRow label="Monthly budget" htmlFor="department-form-field-budget">
                    <div className="input-group">
                      <span className="input-group-text"><i className="feather-dollar-sign"></i></span>
                      <input type="number" step="0.01" min={0} className="form-control" id="department-form-field-budget"
                             name="monthly_budget_amount" defaultValue={d.monthly_budget_amount ?? ""} />
                      <input type="text" className="form-control" id="department-form-field-currency" name="budget_currency"
                             defaultValue={d.budget_currency ?? "USD"} maxLength={3} size={3} aria-label="Currency" />
                    </div>
                    <div className="form-text">Leave blank for no budget. AI spend by this department&rsquo;s agents counts against it.</div>
                  </FieldRow>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
