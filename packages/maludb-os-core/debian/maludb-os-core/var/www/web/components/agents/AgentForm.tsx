"use client";

import { useState } from "react";
import AgentAvatarBadge from "@/components/agents/AgentAvatarBadge";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import ActionForm, { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import type { AgentFormData } from "@/lib/schemas/agents";

const KIND_HELP = "A subagent does the work and never re-delegates; an orchestrator may hold a roster of "
  + "subagents and delegate to them; a voice agent answers inbound calls, and takes no part in delegation.";

/**
 * Hire / edit form (screens `agent-hire` / `agent-edit`) — app/views/agents/agent-form.php.
 * Hire posts to hire.php; edit posts to config-save.php and every save is a new configuration
 * version. Tools are edited live from the Tools tab and the manager from the agent's page.
 *
 * A chosen library prompt resolves server-side into the job description and the model
 * parameters, so the inline fields stay visible but disabled while one is selected
 * (agentFormTogglePrompt() in the template); Kind shows the starting roster or the phone row
 * (agentFormToggleKind()).
 *
 * The template nested the change-kind form inside the agent form, which HTML does not allow.
 * Here that form is an empty sibling and its three controls point at it with `form=`, so they
 * sit where they always sat and post on their own.
 */
export default function AgentForm({ data, back: carried = null }: { data: AgentFormData; back?: string | null }) {
  const { agent: a, version: v, duties, options } = data;
  const isEdit = a.id !== null;
  // Where the form was opened from (click-around R5), else the record on edit and the list on hire.
  const parent = isEdit ? `/agents/${a.id}` : "/agents";
  const back = carried ?? parent;
  const { state, pending, onSubmit } = useRecordForm(isEdit ? "/agents/config-save.php" : "/agents/hire.php", carried);

  const [kind, setKind] = useState(a.kind);
  const [promptId, setPromptId] = useState<string>(v?.system_prompt_id != null ? String(v.system_prompt_id) : "");
  const promptChosen = promptId !== "";
  const inline = v?.inline_parameters ?? { temperature: "", max_tokens: "", thinking_budget: "", extra_parameters: "" };
  const blankStart = isEdit ? duties.length : 0;
  const blankDuties = Array.from({ length: data.blank_rows.duties }, (_, n) => blankStart + n);
  const blankTools = Array.from({ length: data.blank_rows.tools }, (_, n) => n);

  return (
    <>
      <PageHeader title={isEdit ? "Edit agent" : "Hire an agent"} id="agent-form"
                  crumbs={[{ label: "HR", href: "/agents" }, ...(isEdit ? [{ label: a.name, href: parent }] : []), { label: isEdit ? "Edit" : "New" }]}
                  back={{ href: parent, label: isEdit ? "the agent" : "Agents" }}>
        <Link href={back} id="agent-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="agent-form" id="agent-form-save" className="btn btn-primary"
                disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : isEdit ? "Save (new version)" : "Hire"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "agent-edit" : "agent-hire"} data-entity="member" data-record-id={a.id ?? ""}>
        <ActionOutcome state={state} id="agent-form-errors" />
        {isEdit && (
          <ActionForm path="/agents/kind.php" id="agent-form-kind-form">
            <input type="hidden" name="agent" value={a.id ?? ""} />
          </ActionForm>
        )}

        {options.models.length === 0 && (
          <div className="alert alert-warning" role="alert" id="agent-form-no-models">
            Register a model first — <Link href="/settings/models/new">add one</Link>.
          </div>
        )}

        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="agent-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="agent" value={a.id ?? ""} />}

                  {!isEdit && (
                    <>
                      <FieldRow label="Name" htmlFor="agent-form-field-name">
                        <input type="text" className="form-control" id="agent-form-field-name" name="name" maxLength={200} required />
                      </FieldRow>
                      <FieldRow label="Email" htmlFor="agent-form-field-email">
                        <input type="email" className="form-control" id="agent-form-field-email" name="email" required />
                        <div className="form-text">The agent&rsquo;s identity for tokens — unique.</div>
                      </FieldRow>
                      <FieldRow label="Job title" htmlFor="agent-form-field-job_title">
                        <input type="text" className="form-control" id="agent-form-field-job_title" name="job_title"
                               defaultValue={a.job_title ?? ""} required />
                      </FieldRow>
                      <FieldRow label="Department" htmlFor="agent-form-field-department_id">
                        <select className="form-select" id="agent-form-field-department_id" name="department_id" required
                                defaultValue={a.department_id ?? ""}>
                          <option value="">— choose —</option>
                          {options.departments.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
                        </select>
                      </FieldRow>
                      <FieldRow label="Manager" htmlFor="agent-form-field-manager_member_id">
                        <select className="form-select" id="agent-form-field-manager_member_id" name="manager_member_id" required defaultValue="">
                          <option value="">— choose —</option>
                          {options.managers.map((m) => (
                            <option value={m.id} key={m.id}>{m.name}{m.kind === "agent" ? " (orchestrator)" : ""}</option>
                          ))}
                        </select>
                        <div className="form-text">A person, or an orchestrator agent — an orchestrator already
                          holds a roster, so managing what it delegates to is the same job. A subagent or a
                          voice agent manages nobody.</div>
                      </FieldRow>
                      <FieldRow label="Home location" htmlFor="agent-form-field-home_location_id">
                        <select className="form-select" id="agent-form-field-home_location_id" name="home_location_id" defaultValue="">
                          <option value="">— none yet —</option>
                          {options.locations.map((l) => <option value={l.id} key={l.id}>{l.name}</option>)}
                        </select>
                        <div className="form-text">Offices and desks. Where the agent works — it can be
                          changed later, and left blank until you know.</div>
                      </FieldRow>
                    </>
                  )}

                  <hr className="my-4" />
                  <h6 className="fw-bold mb-2">Kind</h6>
                  {!isEdit ? (
                    <>
                      <FieldRow label="Kind" htmlFor="agent-form-field-agent_kind">
                        <select className="form-select" id="agent-form-field-agent_kind" name="agent_kind" required
                                value={kind} onChange={(e) => setKind(e.target.value)}>
                          {Object.entries(options.kinds).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                        </select>
                        <div className="form-text">{KIND_HELP}</div>
                      </FieldRow>
                      <div className="row mb-3" id="agent-form-starting-roster-row" style={kind === "orchestrator" ? undefined : { display: "none" }}>
                        <label className="col-lg-4 col-form-label" htmlFor="agent-form-field-subagents">Starting roster (optional)</label>
                        <div className="col-lg-8">
                          <select className="form-select" name="subagents[]" multiple size={6} id="agent-form-field-subagents"
                                  disabled={kind !== "orchestrator"}>
                            {options.subagents.map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
                          </select>
                          <div className="form-text">Subagents this orchestrator may delegate to from day one —
                            more can be added later from its Roster tab.</div>
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      <FieldRow label="Current kind">
                        <span className="badge bg-soft-secondary text-secondary" id="agent-form-current-kind">{a.kind_label}</span>
                        <div className="form-text">{KIND_HELP}</div>
                      </FieldRow>
                      <FieldRow label="Change kind" htmlFor="agent-form-field-kind-change">
                        <div className="d-flex gap-2">
                          <select name="agent_kind" form="agent-form-kind-form" className="form-select form-select-sm"
                                  id="agent-form-field-kind-change" defaultValue={a.kind} key={a.kind}>
                            {Object.entries(options.kinds).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                          </select>
                          <button type="submit" form="agent-form-kind-form" className="btn btn-sm btn-light-brand" id="agent-form-kind-btn">Change</button>
                        </div>
                        <div className="form-text">Refused while a live roster depends on the current kind, or
                          if this agent is its location&rsquo;s office manager (which requires staying an
                          orchestrator) — the refusal names the reason.</div>
                      </FieldRow>
                    </>
                  )}

                  <hr className="my-4" />
                  <h6 className="fw-bold mb-2">Profile</h6>
                  <FieldRow label="Description" htmlFor="agent-form-field-description">
                    <input type="text" className="form-control" id="agent-form-field-description" name="description"
                           defaultValue={a.description ?? ""} placeholder="What this agent is for, in a sentence" />
                    <div className="form-text">In a person&rsquo;s words — distinct from the job description below,
                      which is the system prompt the model receives.</div>
                  </FieldRow>
                  <FieldRow label="Role" htmlFor="agent-form-field-role_key">
                    <input type="text" className="form-control" id="agent-form-field-role_key" name="role_key"
                           defaultValue={a.role_key ?? ""} placeholder="bookkeeper" maxLength={100} />
                    <div className="form-text">A functional role key, e.g. &ldquo;bookkeeper&rdquo; — pairs with eval sets
                      written for that role.</div>
                  </FieldRow>
                  <div className="row mb-3" id="agent-form-phone-row" style={kind === "voice" ? undefined : { display: "none" }}>
                    <label className="col-lg-4 col-form-label" htmlFor="agent-form-field-phone_number">Phone number</label>
                    <div className="col-lg-8">
                      <input type="tel" className="form-control" id="agent-form-field-phone_number" name="phone_number"
                             defaultValue={a.phone_number ?? ""} placeholder="+14155550123" />
                      <div className="form-text">The number this voice agent answers, in E.164 (a leading + and the
                        country code). It is how an inbound call finds this agent, and how its system prompt
                        reaches the call. Leave blank until the number is connected.</div>
                    </div>
                  </div>

                  <FieldRow label="Picture" htmlFor="agent-form-field-profile_photo">
                    {a.avatar.picture_url && (
                      <div className="d-flex align-items-center gap-3 mb-2" id="agent-form-current-photo">
                        <AgentAvatarBadge initials={a.avatar.initials} pictureUrl={a.avatar.picture_url} sizeClass="avatar-lg" />
                        <div className="form-check">
                          <input className="form-check-input" type="checkbox" value="1" name="remove_photo" id="agent-form-field-remove_photo" />
                          <label className="form-check-label fs-12" htmlFor="agent-form-field-remove_photo">Remove this picture</label>
                        </div>
                      </div>
                    )}
                    <input type="file" className="form-control" id="agent-form-field-profile_photo" name="profile_photo"
                           accept="image/jpeg,image/png,image/gif,image/webp" />
                    <div className="form-text">JPEG, PNG, GIF or WebP, up to 2 MB. The file is stored here and
                      served only to people who may see this agent{a.avatar.picture_url ? " — uploading a new one replaces it" : ""}.</div>
                  </FieldRow>

                  <FieldRow label="Model" htmlFor="agent-form-field-model_id">
                    <select className="form-select" id="agent-form-field-model_id" name="model_id" required defaultValue={v?.model_id ?? ""}>
                      <option value="">— choose —</option>
                      {options.models.map((m) => <option value={m.id} key={m.id}>{m.name}</option>)}
                    </select>
                  </FieldRow>

                  <hr className="my-4" />
                  <h6 className="fw-bold mb-2">System prompt</h6>
                  <FieldRow label="Library prompt" htmlFor="agent-form-field-system_prompt_id">
                    <select className="form-select" id="agent-form-field-system_prompt_id" name="system_prompt_id"
                            value={promptId} onChange={(e) => setPromptId(e.target.value)}>
                      <option value="">— write inline instead —</option>
                      {options.prompts.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}
                    </select>
                    <div className="form-text">Choosing one resolves that version&rsquo;s text and model settings in
                      on save — the fields below are then ignored. Leave unset to write a prompt for
                      this agent alone. <Link href="/settings/prompts">Manage the library</Link>.</div>
                  </FieldRow>

                  <FieldRow label="Job description" htmlFor="agent-form-field-job_description">
                    <textarea className="form-control" id="agent-form-field-job_description" name="job_description"
                              rows={6} disabled={promptChosen} defaultValue={v?.job_description ?? ""}></textarea>
                    <div className="form-text">The agent&rsquo;s system prompt — write one here, or choose a library prompt above.</div>
                  </FieldRow>

                  <FieldRow label="Model parameters">
                    <div id="agent-form-cited-params" className={`alert alert-secondary fs-12${promptChosen ? "" : " d-none"}`}>
                      From the chosen prompt version — not editable here; write a new library version to change them.
                      {v && v.system_prompt_id !== null && String(v.system_prompt_id) === promptId && v.cited_parameters.length > 0 && (
                        <dl className="row mb-0 mt-2">
                          {v.cited_parameters.map((p) => (
                            <div key={p.name} style={{ display: "contents" }}>
                              <dt className="col-5">{p.name}</dt><dd className="col-7">{p.value}</dd>
                            </div>
                          ))}
                        </dl>
                      )}
                    </div>
                    <div id="agent-form-inline-params" className={promptChosen ? "d-none" : ""}>
                      <div className="row g-2 mb-2">
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="agent-form-field-temperature">Temperature</label>
                          <input type="number" step="0.001" min={0} className="form-control form-control-sm" id="agent-form-field-temperature"
                                 name="temperature" defaultValue={inline.temperature} disabled={promptChosen} />
                        </div>
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="agent-form-field-max_tokens">Max tokens</label>
                          <input type="number" step={1} min={1} className="form-control form-control-sm" id="agent-form-field-max_tokens"
                                 name="max_tokens" defaultValue={inline.max_tokens} disabled={promptChosen} />
                        </div>
                        <div className="col-4">
                          <label className="form-label fs-11" htmlFor="agent-form-field-thinking_budget">Thinking budget</label>
                          <input type="number" step={1} min={0} className="form-control form-control-sm" id="agent-form-field-thinking_budget"
                                 name="thinking_budget" defaultValue={inline.thinking_budget} disabled={promptChosen} />
                        </div>
                      </div>
                      <label className="form-label fs-11" htmlFor="agent-form-field-extra_parameters">Other parameters (JSON object)</label>
                      <textarea className="form-control form-control-sm" id="agent-form-field-extra_parameters" name="extra_parameters"
                                rows={2} placeholder={'{"top_p": 0.9}'} defaultValue={inline.extra_parameters} disabled={promptChosen}></textarea>
                      <div className="form-text">Used only when writing inline (no library prompt chosen above).</div>
                    </div>
                  </FieldRow>

                  <div className="row mb-3">
                    <label className="col-lg-4 col-form-label" htmlFor="agent-form-field-monthly_budget_amount">Monthly budget</label>
                    <div className="col-lg-8 d-flex gap-2">
                      <input type="number" step="0.01" min={0} className="form-control" id="agent-form-field-monthly_budget_amount"
                             name="monthly_budget_amount" defaultValue={v?.monthly_budget_amount ?? ""} />
                      {!isEdit && (
                        <select className="form-select" style={{ maxWidth: "8rem" }} id="agent-form-field-budget_currency"
                                name="budget_currency" defaultValue="USD">
                          <option value="USD">USD</option><option value="EUR">EUR</option><option value="GBP">GBP</option>
                        </select>
                      )}
                    </div>
                  </div>

                  {isEdit && (
                    <FieldRow label="Run limits" htmlFor="agent-form-field-max_turns">
                      <div className="row g-2">
                        <div className="col-6">
                          <label className="form-label fs-11" htmlFor="agent-form-field-max_turns">Most turns in a run</label>
                          <input type="number" step={1} min={1} max={200} className="form-control form-control-sm"
                                 id="agent-form-field-max_turns" name="max_turns" defaultValue={v?.run_limits.max_turns ?? ""} />
                        </div>
                        <div className="col-6">
                          <label className="form-label fs-11" htmlFor="agent-form-field-run_timeout_seconds">Longest run (seconds)</label>
                          <input type="number" step={1} min={60} max={3600} className="form-control form-control-sm"
                                 id="agent-form-field-run_timeout_seconds" name="run_timeout_seconds"
                                 defaultValue={v?.run_limits.run_timeout_seconds ?? ""} />
                        </div>
                      </div>
                      <div className="form-text">Blank = the platform&rsquo;s default. A run that outlasts its time limit is stopped and recorded as failed.</div>
                    </FieldRow>
                  )}

                  {isEdit && (
                    <FieldRow label="Change note" htmlFor="agent-form-field-change_note">
                      <input type="text" className="form-control" id="agent-form-field-change_note" name="change_note"
                             placeholder="What changed and why" />
                    </FieldRow>
                  )}

                  <hr className="my-4" />
                  <h6 className="fw-bold mb-2">Duties</h6>
                  <p className="fs-12 text-muted">A duty&rsquo;s schedule is a 5-field cron expression, e.g. &ldquo;0 7 * * 1-5&rdquo;
                    (weekdays at 07:00). Blank rows are ignored.</p>
                  {isEdit && duties.map((d, i) => (
                    <div className="row g-2 align-items-end mb-2 border-bottom pb-2" key={d.id}>
                      <input type="hidden" name={`duties[${i}][duty_id]`} value={d.id} />
                      <div className="col-sm-3">
                        <label className="form-label fs-11">Name</label>
                        <input type="text" name={`duties[${i}][name]`} className="form-control form-control-sm" defaultValue={d.name} />
                      </div>
                      <div className="col-sm-4">
                        <label className="form-label fs-11">Instructions</label>
                        <input type="text" name={`duties[${i}][instructions]`} className="form-control form-control-sm" defaultValue={d.instructions} />
                      </div>
                      <div className="col-sm-2">
                        <label className="form-label fs-11">Cron</label>
                        <input type="text" name={`duties[${i}][schedule_cron]`} className="form-control form-control-sm" defaultValue={d.schedule_cron} />
                      </div>
                      <div className="col-sm-2">
                        <label className="form-label fs-11">Timezone</label>
                        <input type="text" name={`duties[${i}][timezone]`} className="form-control form-control-sm" defaultValue={d.timezone} />
                      </div>
                      <div className="col-sm-1 form-check">
                        <input className="form-check-input" type="checkbox" name={`duties[${i}][remove]`} value="1" id={`agent-form-duty-remove-${d.id}`} />
                        <label className="form-check-label fs-11" htmlFor={`agent-form-duty-remove-${d.id}`}>Remove</label>
                      </div>
                    </div>
                  ))}
                  {blankDuties.map((i) => (
                    <div className="row g-2 align-items-end mb-2" key={i}>
                      <div className="col-sm-3">
                        <label className="form-label fs-11">Name</label>
                        <input type="text" name={`duties[${i}][name]`} className="form-control form-control-sm" id={`agent-form-field-duty-name-${i}`} />
                      </div>
                      <div className="col-sm-4">
                        <label className="form-label fs-11">Instructions</label>
                        <input type="text" name={`duties[${i}][instructions]`} className="form-control form-control-sm" id={`agent-form-field-duty-instructions-${i}`} />
                      </div>
                      <div className="col-sm-3">
                        <label className="form-label fs-11">Cron</label>
                        <input type="text" name={`duties[${i}][schedule_cron]`} className="form-control form-control-sm"
                               placeholder="0 7 * * 1-5" id={`agent-form-field-duty-cron-${i}`} />
                      </div>
                      <div className="col-sm-2">
                        <label className="form-label fs-11">Timezone</label>
                        <input type="text" name={`duties[${i}][timezone]`} className="form-control form-control-sm"
                               placeholder="UTC" id={`agent-form-field-duty-tz-${i}`} />
                      </div>
                    </div>
                  ))}

                  {!isEdit && (
                    <>
                      <hr className="my-4" />
                      <h6 className="fw-bold mb-2">Tools (optional at hire — grant more later from the Tools tab)</h6>
                      {blankTools.map((i) => (
                        <div className="row g-2 align-items-end mb-2" key={i}>
                          <div className="col-sm-3">
                            <label className="form-label fs-11">Endpoint</label>
                            <select name={`tools[${i}][application_endpoint_id]`} className="form-select form-select-sm"
                                    id={`agent-form-field-tool-endpoint-${i}`} defaultValue="">
                              <option value="">—</option>
                              {options.tool_endpoints.map((e) => <option value={e.id} key={e.id}>{e.name}</option>)}
                            </select>
                          </div>
                          <div className="col-sm-4">
                            <label className="form-label fs-11">Tool name</label>
                            <input type="text" name={`tools[${i}][tool_name]`} className="form-control form-control-sm" id={`agent-form-field-tool-name-${i}`} />
                          </div>
                          <div className="col-sm-5">
                            <label className="form-label fs-11">Constraints (JSON)</label>
                            <input type="text" name={`tools[${i}][constraints]`} className="form-control form-control-sm"
                                   placeholder={'{"max_amount": 500}'} id={`agent-form-field-tool-constraints-${i}`} />
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
