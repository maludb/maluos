"use client";

import { useState } from "react";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import type { MemoryDepartments } from "@/lib/schemas/memory";

/**
 * Remember something (action `memory_remember`). PHP resolves where it lands from the signed-in
 * member and the scope — a department is asked for only when the person belongs to several; the
 * organisation is offered only when PHP said this person may speak for it.
 */
export default function RememberForm({ departments, canOrg }: { departments: MemoryDepartments; canOrg: boolean }) {
  const [scope, setScope] = useState("self");
  return (
    <ActionForm path="/memory/remember.php" resetOnSuccess>
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-remember-field-text">What should be remembered</label>
        <textarea className="form-control" name="text" id="memory-remember-field-text" rows={4} required maxLength={8000}
                  placeholder="Northwind pays on the last Friday of the month, never before."></textarea>
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-remember-field-subject">What it is about</label>
        <input type="text" className="form-control" name="subject" id="memory-remember-field-subject" required maxLength={200}
               placeholder="Northwind" autoComplete="off" />
        <div className="form-text">Memory is filed by subject — a customer, a vendor, a process. Naming it the same way each time is what makes it findable.</div>
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="memory-remember-field-scope">Who should know it</label>
        <select className="form-select" name="scope" id="memory-remember-field-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="self">Only me</option>
          {departments.length > 0 && <option value="department">My department</option>}
          {canOrg && <option value="org">Everyone — the whole organisation</option>}
        </select>
      </div>
      {scope === "department" && departments.length > 1 && (
        <div className="mb-3">
          <label className="form-label" htmlFor="memory-remember-field-department">Department</label>
          <select className="form-select" name="department" id="memory-remember-field-department" required defaultValue="">
            <option value="" disabled>Choose…</option>
            {departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
          </select>
        </div>
      )}
      <SubmitButton className="btn btn-primary" id="memory-remember-btn"><i className="feather-plus me-2"></i>Remember</SubmitButton>
    </ActionForm>
  );
}
