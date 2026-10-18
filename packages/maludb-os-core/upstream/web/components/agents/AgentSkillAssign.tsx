"use client";

import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";

/**
 * Give one skill to this agent alone (action `skill_assign`, scope agent) — the Skills tab's add box
 * (owner, 2026-09-27). The picker offers what the library has enabled and the agent does not already
 * carry; a pin is optional and, as everywhere, must resolve in MaluDB or PHP refuses it.
 */
export default function AgentSkillAssign({ agentId, assignable }: { agentId: number; assignable: { name: string; kind?: string; description: string }[] }) {
  const runbooks = assignable.filter((s) => s.kind === "runbook");
  const skills = assignable.filter((s) => s.kind !== "runbook");
  return (
    <ActionForm path="/skills/assign.php" resetOnSuccess>
      <input type="hidden" name="scope_kind" value="agent" />
      <input type="hidden" name="agent" value={agentId} />
      <div className="row g-2 align-items-end">
        <div className="col-md-5">
          <label className="form-label" htmlFor="agent-skill-assign-name">Give this agent a skill</label>
          <select className="form-select" name="skill_name" id="agent-skill-assign-name" required defaultValue="">
            <option value="" disabled>Choose from the library…</option>
            {runbooks.length > 0 && <optgroup label="Runbooks">{runbooks.map((s) => <option value={s.name} key={s.name} title={s.description}>{s.name}</option>)}</optgroup>}
            {skills.length > 0 && <optgroup label="Skills">{skills.map((s) => <option value={s.name} key={s.name} title={s.description}>{s.name}</option>)}</optgroup>}
          </select>
        </div>
        <div className="col-md-4">
          <label className="form-label" htmlFor="agent-skill-assign-pin">Pin to a version <span className="text-muted">(optional)</span></label>
          <input type="text" className="form-control" name="pinned_bundle_hash" id="agent-skill-assign-pin" pattern="[0-9a-f]{64}" placeholder="bundle hash" autoComplete="off" />
        </div>
        <div className="col-md-3">
          <SubmitButton className="btn btn-primary w-100" id="agent-skill-assign-btn"><i className="feather-plus me-2"></i>Assign</SubmitButton>
        </div>
      </div>
      <div className="form-text">Reaches this agent only, at its next run. To reach a department, a role, an application or everyone, use Skills.</div>
    </ActionForm>
  );
}
