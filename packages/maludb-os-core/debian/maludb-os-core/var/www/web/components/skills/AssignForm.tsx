"use client";

import { useState } from "react";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import type { SkillAssignOptions } from "@/lib/schemas/skills";

/**
 * Assign a MaluDB skill (action `skill_assign`). The scope decides which one picker is asked for;
 * PHP keeps only the field the scope names and checks that the skill — and a pin — exists in
 * MaluDB. `anywhere` is PHP's answer: only HR may assign to the organisation or to a role.
 */
export default function AssignForm({ options, anywhere }: { options: SkillAssignOptions; anywhere: boolean }) {
  const [scope, setScope] = useState(anywhere ? "department" : "department");
  return (
    <ActionForm path="/skills/assign.php" resetOnSuccess>
      <div className="mb-3">
        <label className="form-label" htmlFor="skill-assign-field-name">Skill</label>
        <input type="text" className="form-control" name="skill_name" id="skill-assign-field-name" required
               pattern="[a-z0-9][a-z0-9\-]{1,63}" placeholder="file-a-vendor-bill" autoComplete="off" />
        <div className="form-text">Its name in MaluDB. It must exist there and be enabled.</div>
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="skill-assign-field-scope">Give it to</label>
        <select className="form-select" name="scope_kind" id="skill-assign-field-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          {anywhere && <option value="org">Everyone — the whole organisation</option>}
          <option value="department">A department</option>
          {anywhere && <option value="role">A role</option>}
          <option value="agent">One agent</option>
        </select>
      </div>
      {scope === "department" && (
        <div className="mb-3">
          <label className="form-label" htmlFor="skill-assign-field-department">Department</label>
          <select className="form-select" name="department" id="skill-assign-field-department" required defaultValue="">
            <option value="" disabled>Choose…</option>
            {options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
          </select>
        </div>
      )}
      {scope === "role" && (
        <div className="mb-3">
          <label className="form-label" htmlFor="skill-assign-field-role">Role</label>
          <select className="form-select" name="role_key" id="skill-assign-field-role" required defaultValue="">
            <option value="" disabled>Choose…</option>
            {options.roles.map((r) => <option value={r} key={r}>{r}</option>)}
          </select>
        </div>
      )}
      {scope === "agent" && (
        <div className="mb-3">
          <label className="form-label" htmlFor="skill-assign-field-agent">Agent</label>
          <select className="form-select" name="agent" id="skill-assign-field-agent" required defaultValue="">
            <option value="" disabled>Choose…</option>
            {options.agents.map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
          </select>
        </div>
      )}
      <div className="mb-3">
        <label className="form-label" htmlFor="skill-assign-field-pin">Pin to a version <span className="text-muted">(optional)</span></label>
        <input type="text" className="form-control" name="pinned_bundle_hash" id="skill-assign-field-pin" pattern="[0-9a-f]{64}"
               placeholder="bundle hash — leave empty to follow the newest version" autoComplete="off" />
      </div>
      <div className="mb-3">
        <label className="form-label" htmlFor="skill-assign-field-note">Note <span className="text-muted">(optional)</span></label>
        <input type="text" className="form-control" name="note" id="skill-assign-field-note" maxLength={300} />
      </div>
      <SubmitButton className="btn btn-primary" id="skill-assign-btn"><i className="feather-plus me-2"></i>Assign</SubmitButton>
    </ActionForm>
  );
}
