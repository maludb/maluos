"use client";

import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";

/** New prompt (screen `system-prompt-add`) — app/views/settings/prompt-form.php. Saves the prompt and its version 1. */
export default function PromptForm({ back = null }: { back?: string | null } = {}) {
  const list = "/settings/prompts";   // PHP lands on the new prompt; Cancel returns to the list (R5)
  const { state, pending, onSubmit } = useRecordForm("/settings/prompts/save.php", back);
  return (
    <>
      <PageHeader title="New prompt" crumbs={[{ label: "Settings", href: "/settings" }, { label: "Prompt library", href: list }, { label: "New" }]} id="prompt-form"
                  back={{ href: list, label: "Prompt library" }}>
        <Link href={back ?? list} id="prompt-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="prompt-form" id="prompt-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen="system-prompt-add">
        <ActionOutcome state={state} id="prompt-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="prompt-form" onSubmit={onSubmit}>
                  <FieldRow label="Key" htmlFor="prompt-form-field-prompt_key">
                    <input type="text" className="form-control" id="prompt-form-field-prompt_key" name="prompt_key" maxLength={100} placeholder="bookkeeper" required />
                    <div className="form-text">Short and unique — how other screens refer to this prompt.</div>
                  </FieldRow>
                  <FieldRow label="Name" htmlFor="prompt-form-field-name">
                    <input type="text" className="form-control" id="prompt-form-field-name" name="name" required />
                  </FieldRow>
                  <FieldRow label="Description" htmlFor="prompt-form-field-description">
                    <input type="text" className="form-control" id="prompt-form-field-description" name="description" placeholder="What this prompt is for" />
                  </FieldRow>
                  <FieldRow label="Role" htmlFor="prompt-form-field-role_key">
                    <input type="text" className="form-control" id="prompt-form-field-role_key" name="role_key" maxLength={100} placeholder="bookkeeper" />
                    <div className="form-text">Pairs with eval sets written for this role.</div>
                  </FieldRow>
                  <FieldRow label="Version 1 text" htmlFor="prompt-form-field-system_prompt">
                    <textarea className="form-control" id="prompt-form-field-system_prompt" name="system_prompt" rows={8} required></textarea>
                    <div className="form-text">The text the model receives. Immutable once saved — a later
                      change is a new version, from this prompt&rsquo;s own page.</div>
                  </FieldRow>

                  <h6 className="fw-bold mb-2">Model parameters (optional)</h6>
                  <div className="row g-2 mb-2">
                    <div className="col-4">
                      <label className="form-label fs-11" htmlFor="prompt-form-field-temperature">Temperature</label>
                      <input type="number" step="0.001" min={0} className="form-control form-control-sm" id="prompt-form-field-temperature" name="temperature" />
                    </div>
                    <div className="col-4">
                      <label className="form-label fs-11" htmlFor="prompt-form-field-max_tokens">Max tokens</label>
                      <input type="number" step={1} min={1} className="form-control form-control-sm" id="prompt-form-field-max_tokens" name="max_tokens" />
                    </div>
                    <div className="col-4">
                      <label className="form-label fs-11" htmlFor="prompt-form-field-thinking_budget">Thinking budget</label>
                      <input type="number" step={1} min={0} className="form-control form-control-sm" id="prompt-form-field-thinking_budget" name="thinking_budget" />
                    </div>
                  </div>
                  <label className="form-label fs-11" htmlFor="prompt-form-field-extra_parameters">Other parameters (JSON object)</label>
                  <textarea className="form-control form-control-sm" id="prompt-form-field-extra_parameters" name="extra_parameters" rows={2}
                            placeholder={'{"top_p": 0.9}'}></textarea>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
