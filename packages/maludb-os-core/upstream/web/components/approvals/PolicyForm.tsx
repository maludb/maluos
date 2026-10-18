"use client";

import { useState } from "react";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { ApprovalPolicyFormData } from "@/lib/schemas/approvals";

/**
 * Approval policy form (screens `approval-policy-add` / `approval-policy-edit`) — super-admin.
 * "Applies to" decides which of the agent / department pickers is asked for; PHP checks the same
 * thing (the table's own CHECK constraints are the rule).
 */
export default function PolicyForm({ data, back = null }: { data: ApprovalPolicyFormData; back?: string | null }) {
  const { policy: p, options } = data;
  const isEdit = p.id !== null;
  const list = "/settings/approval-policies";   // a policy has no page of its own: Cancel and a save land on the list (R5)
  const [appliesTo, setAppliesTo] = useState(p.applies_to);
  const { state, pending, onSubmit } = useRecordForm("/settings/approval-policies/save.php", back);

  return (
    <>
      <PageHeader title={isEdit ? "Edit approval policy" : "New approval policy"} id="approval-policy-form"
                  crumbs={[{ label: "Settings", href: "/settings" }, { label: "Approval policies", href: list }, { label: isEdit ? p.name : "New" }]}
                  back={{ href: list, label: "Approval policies" }}>
        <Link href={back ?? list} id="approval-policy-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="approval-policy-form" id="approval-policy-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "approval-policy-edit" : "approval-policy-add"} data-entity="approval_policy" data-record-id={p.id ?? ""}>
        <ActionOutcome state={state} id="approval-policy-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="approval-policy-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="policy" value={p.id ?? ""} />}
                  <FieldRow label="Name" htmlFor="approval-policy-form-field-name">
                    <input type="text" className="form-control" id="approval-policy-form-field-name" name="name" defaultValue={p.name} maxLength={200} required />
                  </FieldRow>
                  <FieldRow label="Kind of action" htmlFor="approval-policy-form-field-category">
                    <select className="form-select" id="approval-policy-form-field-category" name="category" defaultValue={p.category}>
                      {options.categories.map((c) => <option value={c.id} key={c.id}>{c.name}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Action" htmlFor="approval-policy-form-field-action-pattern">
                    <input type="text" className="form-control" id="approval-policy-form-field-action-pattern" name="action_pattern"
                           defaultValue={p.action_pattern} maxLength={120} required placeholder="invoice.send" />
                    <div className="form-text">The event of the action: <code>invoice.send</code>, every action on a record <code>invoice.*</code>, or one verb everywhere <code>*.delete</code>.</div>
                  </FieldRow>
                  <FieldRow label="Applies to" htmlFor="approval-policy-form-field-applies-to">
                    <select className="form-select" id="approval-policy-form-field-applies-to" name="applies_to" value={appliesTo}
                            onChange={(e) => setAppliesTo(e.target.value)}>
                      {options.applies_to.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
                    </select>
                  </FieldRow>
                  {appliesTo === "agent" && (
                    <FieldRow label="Agent" htmlFor="approval-policy-form-field-agent">
                      <select className="form-select" id="approval-policy-form-field-agent" name="agent" defaultValue={p.agent_member_id ?? ""} required>
                        <option value="">Choose an agent…</option>
                        {options.agents.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
                      </select>
                    </FieldRow>
                  )}
                  {appliesTo === "department" && (
                    <FieldRow label="Department" htmlFor="approval-policy-form-field-department">
                      <select className="form-select" id="approval-policy-form-field-department" name="department" defaultValue={p.department_id ?? ""} required>
                        <option value="">Choose a department…</option>
                        {options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
                      </select>
                    </FieldRow>
                  )}
                  <FieldRow label="Only above" htmlFor="approval-policy-form-field-amount">
                    <div className="input-group">
                      <input type="number" step="0.01" min="0" className="form-control" id="approval-policy-form-field-amount" name="amount_threshold"
                             defaultValue={p.amount_threshold ?? ""} placeholder="Any amount" />
                      <input type="text" className="form-control" style={{ maxWidth: 90 }} id="approval-policy-form-field-currency" name="currency"
                             defaultValue={p.currency ?? data.base_currency} maxLength={3} aria-label="Currency" />
                    </div>
                    <div className="form-text">Blank means every such action needs approval, whatever its amount.</div>
                  </FieldRow>
                  <FieldRow label="Approver" htmlFor="approval-policy-form-field-approver">
                    <select className="form-select" id="approval-policy-form-field-approver" name="approver" defaultValue={p.approver_member_id ?? ""}>
                      <option value="">The requester’s manager</option>
                      {options.approvers.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
                    </select>
                    <div className="form-text">An agent never approves. Left blank, the request goes to the nearest human manager.</div>
                  </FieldRow>
                  <FieldRow label="Expires after" htmlFor="approval-policy-form-field-expires">
                    <div className="input-group" style={{ maxWidth: 220 }}>
                      <input type="number" min="1" max="2160" className="form-control" id="approval-policy-form-field-expires" name="expires_after_hours"
                             defaultValue={p.expires_after_hours} required />
                      <span className="input-group-text">hours</span>
                    </div>
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
