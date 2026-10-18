"use client";

import { useState } from "react";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ActionOutcome } from "@/components/kit/ActionForm";
import { FieldRow } from "@/components/kit/FormFields";
import { useRecordForm } from "@/components/kit/useRecordForm";
import { ucfirst } from "@/lib/format";
import type { ModelFormData } from "@/lib/schemas/settings";

const PRICES: [keyof ModelFormData["model"], string][] = [
  ["price_input_per_mtok", "Input"], ["price_output_per_mtok", "Output"],
  ["price_cache_read_per_mtok", "Cache read"], ["price_cache_write_per_mtok", "Cache write"],
];

/**
 * Model form (screens `model-add` / `model-edit`) — app/views/settings/model-form.php.
 * Endpoint URL: mcp_model_registry hides the column, so the form payload — and only it — carries
 * the stored value from find_model_endpoint_url() (owner's decision 10).
 */
export default function ModelForm({ data, back = null }: { data: ModelFormData; back?: string | null }) {
  const { model: m, options } = data;
  // null when the runner could not be asked — then the form says nothing rather than guessing.
  const built = options.built_harnesses;
  const isEdit = m.id !== null;
  const list = "/settings/models";   // a model has no page of its own: Cancel and a save land on the list (R5)
  const { state, pending, onSubmit } = useRecordForm("/settings/models/save.php", back);
  // The Claude Max plan is offered only where it can work: an Anthropic model on the Claude Code harness (docs/build-specs/claude-subscription-auth.md).
  const [provider, setProvider] = useState(m.provider || options.providers[0]);
  const [harness, setHarness] = useState(m.harness || options.harnesses[0]);
  const [billsTo, setBillsTo] = useState<string>(m.auth_mode);
  const planEligible = provider === "anthropic" && harness === "claude_agent_sdk";
  const plan = billsTo === "claude_subscription" && planEligible;

  return (
    <>
      <PageHeader title={isEdit ? "Edit model" : "Register a model"} id="model-form"
                  crumbs={[{ label: "Settings", href: "/settings" }, { label: "Models", href: list }, { label: isEdit ? m.model_key : "New" }]}
                  back={{ href: list, label: "Models" }}>
        <Link href={back ?? list} id="model-form-cancel" className="btn btn-light-brand">Cancel</Link>
        <button type="submit" form="model-form" id="model-form-save" className="btn btn-primary" disabled={pending}>
          <i className="feather-check me-2"></i><span>{pending ? "Saving…" : "Save"}</span>
        </button>
      </PageHeader>

      <div className="main-content" data-screen={isEdit ? "model-edit" : "model-add"}>
        <ActionOutcome state={state} id="model-form-errors" />
        <div className="row">
          <div className="col-lg-8">
            <div className="card stretch stretch-full">
              <div className="card-body">
                <form id="model-form" onSubmit={onSubmit}>
                  {isEdit && <input type="hidden" name="model" value={m.id ?? ""} />}
                  <FieldRow label="Model key" htmlFor="model-form-field-model_key">
                    <input type="text" className="form-control" id="model-form-field-model_key" name="model_key" defaultValue={m.model_key}
                           maxLength={100} placeholder="claude-opus-5" required />
                  </FieldRow>
                  <FieldRow label="Display name" htmlFor="model-form-field-display_name">
                    <input type="text" className="form-control" id="model-form-field-display_name" name="display_name" defaultValue={m.display_name} required />
                  </FieldRow>
                  <FieldRow label="Provider" htmlFor="model-form-field-provider">
                    <select className="form-select" id="model-form-field-provider" name="provider" required value={provider} onChange={(e) => setProvider(e.target.value)}>
                      {options.providers.map((p) => <option value={p} key={p}>{ucfirst(p)}</option>)}
                    </select>
                  </FieldRow>
                  <FieldRow label="Provider model id" htmlFor="model-form-field-provider_model_id">
                    <input type="text" className="form-control" id="model-form-field-provider_model_id" name="provider_model_id" defaultValue={m.provider_model_id ?? ""}
                           placeholder="claude-opus-5-20260101" required />
                    <div className="form-text">Sent to the provider API.</div>
                  </FieldRow>
                  <FieldRow label="Harness" htmlFor="model-form-field-harness">
                    <select className="form-select" id="model-form-field-harness" name="harness" required value={harness} onChange={(e) => setHarness(e.target.value)}>
                      {options.harnesses.map((h) => (
                        <option value={h} key={h}>{h}{built && !built.includes(h) ? " — no harness built" : ""}</option>
                      ))}
                    </select>
                    {built !== null && built !== undefined && (
                      <div className="form-text">
                        Built and runnable today: {built.length ? built.join(", ") : "none"}. A model on any other
                        harness can be registered, but nobody can be hired onto it yet.
                      </div>
                    )}
                  </FieldRow>
                  <FieldRow label="Bills to" htmlFor="model-form-field-auth_mode">
                    <select className="form-select" id="model-form-field-auth_mode" name="auth_mode" value={planEligible ? billsTo : "api_key"}
                            onChange={(e) => setBillsTo(e.target.value)} disabled={!planEligible}>
                      <option value="api_key">An API key (paid per token)</option>
                      <option value="claude_subscription">The Claude Max plan (Claude Code only)</option>
                    </select>
                    {/* A disabled select is not submitted, and an ineligible model always bills to a key. */}
                    {!planEligible && <input type="hidden" name="auth_mode" value="api_key" />}
                    <div className="form-text" id="model-form-auth-help">
                      {planEligible
                        ? "The Claude Max plan is available for Anthropic models on the claude_agent_sdk harness (the official Claude Code CLI)."
                        : "Choose provider Anthropic and harness claude_agent_sdk to bill a model to the Claude Max plan."}
                      {isEdit && " How a model bills cannot change once agents use it — register a separate model for the other way."}
                    </div>
                    {plan && (
                      <div className="alert alert-warning fs-12 mt-2 mb-0" id="model-form-max-plan-warning" role="alert">
                        <strong>Read this first.</strong> Running autonomous agents on a Claude subscription may breach Anthropic&rsquo;s terms, can be throttled or
                        blocked at any time, and could put the whole Max account at risk. It is for this install only, the plan&rsquo;s rate limit is shared, so these
                        agents run one at a time, and the prices below are what the API <em>would</em> charge — recorded as notional cost, never as spend.{" "}
                        {options.subscription === false && <strong>Subscription use is switched off on this install, so an agent cannot be hired onto this model until it is switched on (docs/deploy/set-claude-subscription.sh).</strong>}
                        {options.subscription === true && <span>Subscription use is switched on.</span>}
                      </div>
                    )}
                  </FieldRow>
                  <FieldRow label="Endpoint URL" htmlFor="model-form-field-endpoint_url">
                    <input type="text" className="form-control" id="model-form-field-endpoint_url" name="endpoint_url" defaultValue={m.endpoint_url ?? ""}
                           placeholder="local / compatible endpoints only" />
                  </FieldRow>
                  <FieldRow label="Context window" htmlFor="model-form-field-context_window_tokens">
                    <input type="number" min={1} step={1} className="form-control" id="model-form-field-context_window_tokens"
                           name="context_window_tokens" defaultValue={m.context_window_tokens ?? ""} />
                  </FieldRow>
                  <FieldRow label="Prices per million tokens">
                    <div className="row g-2">
                      {PRICES.map(([name, label]) => (
                        <div className="col-6 col-md-3" key={name}>
                          <label className="form-label fs-11" htmlFor={`model-form-field-${name}`}>{label}</label>
                          <input type="number" step="0.000001" min={0} className="form-control form-control-sm" id={`model-form-field-${name}`}
                                 name={name} defaultValue={(m[name] as string | null) ?? ""} />
                        </div>
                      ))}
                    </div>
                  </FieldRow>
                  <FieldRow label="Currency" htmlFor="model-form-field-currency">
                    <input type="text" className="form-control" style={{ maxWidth: "8rem" }} id="model-form-field-currency" name="currency" defaultValue={m.currency} maxLength={3} />
                  </FieldRow>
                  <FieldRow label="Status" htmlFor="model-form-field-status">
                    <select className="form-select" id="model-form-field-status" name="status" defaultValue={m.status}>
                      {options.statuses.map((s) => <option value={s} key={s}>{ucfirst(s)}</option>)}
                    </select>
                  </FieldRow>
                  {plan ? (
                    <div className="alert alert-secondary fs-12 mb-0" id="model-form-no-key-note">
                      No API key is used: the ledger proxy signs this model in with the Max login, so an agent never holds it.
                    </div>
                  ) : (
                    <div className="alert alert-secondary fs-12 mb-0" id="model-form-no-key-note">
                      No API key is attached — a model without a key can be hired against and cannot be run
                      until the tenant secret store exists.
                    </div>
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
