import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StateBadge, money } from "@/components/aiops/AiOpsNav";
import PromoteLink from "@/components/aiops/PromoteForm";
import RunVerdict from "@/components/aiops/RunVerdict";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { promptCallScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Model call · AI Ops" };

const PRE = { whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 560, overflow: "auto", fontSize: 12 } as const;

/**
 * Screen `prompt-log-view` — one call: what the model was given, what it answered, tokens, latency, cost, and what it led to.
 * Data: GET /ai/prompt-log/{id}. The prompt is shown as plain pre-wrapped text — never as HTML — and only to who
 * mcp_prompt_payloads admits; a payload past retention says so.
 */
export default async function PromptCallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();
  return renderScreen(`/ai/prompt-log/${id}`, promptCallScreen, ({ call: c, payload_state, context, response, actions, verdicts, can }) => (
    <>
      <PageHeader title={`Call #${c.id}`} id="prompt-call" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Prompt log", href: "/ai/prompt-log" }, { label: `#${c.id}` }]} back={{ href: "/ai/prompt-log", label: "Prompt log" }}>
        {can.promote && payload_state === "shown" && <PromoteLink kind="ledger" id={c.id} />}
      </PageHeader>
      <div className="main-content" data-screen="prompt-log-view" data-entity="prompt_ledger" data-record-id={c.id}>
        <div className="row">
          <div className="col-lg-8">
            {payload_state !== "shown" ? (
              <div className="card" id="prompt-call-payload-missing"><div className="card-body text-muted">
                {payload_state === "expired" ? "Payload expired — the prompt and response passed the retention period and were removed. The ledger row (tokens, cost, outcome) is kept."
                  : "The prompt and response are not available to you for this call, or none was stored."}
              </div></div>
            ) : (
              <>
                <div className="card" id="prompt-call-context-card">
                  <div className="card-header"><h5 className="card-title">What the model was given <span className="text-muted fs-12 fw-normal">{context ? `${Math.round(context.bytes / 1024)} KB` : ""}</span></h5></div>
                  <div className="card-body"><pre className="mb-0" id="prompt-call-context" style={PRE}>{context?.text ?? ""}</pre>{context?.truncated && <p className="text-muted fs-12 mt-2 mb-0">Cut at 400 KB.</p>}</div>
                </div>
                <div className="card" id="prompt-call-response-card">
                  <div className="card-header"><h5 className="card-title">What it answered</h5></div>
                  <div className="card-body"><pre className="mb-0" id="prompt-call-response" style={PRE}>{response?.text ?? ""}</pre>{response?.truncated && <p className="text-muted fs-12 mt-2 mb-0">Cut at 400 KB.</p>}</div>
                </div>
              </>
            )}
          </div>
          <div className="col-lg-4">
            <RunVerdict callId={c.id} verdicts={verdicts} can={can.verdict} timeZone={timeZone} />
            <div className="card" id="prompt-call-facts-card">
              <div className="card-header d-flex align-items-center gap-2"><h5 className="card-title mb-0">Call</h5><span className="ms-auto"><StateBadge state={c.status} label={c.status_label} /></span></div>
              <div className="card-body">
                <dl className="row mb-0">
                  <dt className="col-5 text-muted fs-12">When</dt><dd className="col-7">{formatTs(c.occurred_at, timeZone)}</dd>
                  <dt className="col-5 text-muted fs-12">Agent</dt><dd className="col-7">{c.agent ? <Link href={withBack(`/agents/${c.agent.id}`, here)}>{c.agent.name ?? "Agent"}</Link> : "—"}</dd>
                  <dt className="col-5 text-muted fs-12">On behalf of</dt><dd className="col-7"><Who who={c.acting} name={c.acting.name ?? "Someone"} here={here} /></dd>
                  <dt className="col-5 text-muted fs-12">Run</dt><dd className="col-7">{c.run_id !== null ? <Link href={withBack(`/ai/runs/${c.run_id}`, here)}>#{c.run_id}</Link> : "—"}</dd>
                  <dt className="col-5 text-muted fs-12">Model</dt><dd className="col-7 text-break">{c.model_id !== null ? <Link href={withBack(`/settings/models/${c.model_id}/edit`, here)}>{c.model_name ?? c.provider_model_id}</Link> : c.model_name ?? c.provider_model_id}<div className="fs-12 text-muted">{c.provider} · {c.harness} · {c.call_kind}</div></dd>
                  {c.application_id !== null && (<><dt className="col-5 text-muted fs-12">Application</dt><dd className="col-7"><Link href={withBack(`/applications/${c.application_id}`, here)}>#{c.application_id}</Link></dd></>)}
                  <dt className="col-5 text-muted fs-12">Tokens</dt><dd className="col-7">{c.input_tokens.toLocaleString()} in · {c.output_tokens.toLocaleString()} out
                    {(c.cache_read_tokens > 0 || c.cache_write_tokens > 0) && <div className="fs-12 text-muted">{c.cache_read_tokens.toLocaleString()} read from cache · {c.cache_write_tokens.toLocaleString()} written</div>}</dd>
                  <dt className="col-5 text-muted fs-12">Latency</dt><dd className="col-7">{c.latency_ms !== null ? `${(c.latency_ms / 1000).toFixed(2)} s` : "—"}</dd>
                  <dt className="col-5 text-muted fs-12">Cost</dt><dd className="col-7">{money(c.cost, c.currency, 6)}</dd>
                  <dt className="col-5 text-muted fs-12">Request</dt><dd className="col-7 text-break fs-12"><Link href={withBack(`/ai/prompt-log?request_id=${encodeURIComponent(c.request_id)}&period=all`, here)} title="Every call of this request">{c.request_id}</Link></dd>
                  {c.error_message && (<><dt className="col-5 text-muted fs-12">Error</dt><dd className="col-7 text-danger text-break">{c.error_code ? `${c.error_code}: ` : ""}{c.error_message}</dd></>)}
                </dl>
              </div>
            </div>
            <div className="card" id="prompt-call-actions-card">
              <div className="card-header"><h5 className="card-title">What this request did</h5></div>
              <div className="card-body">
                {actions.length === 0 ? <p className="text-muted mb-0">Nothing in the activity trail shares this request.</p> : (
                  <ul className="list-unstyled mb-0">{actions.map((a) => (
                    <li key={a.id} className="py-1 d-flex flex-wrap gap-2"><code className="fs-12">{a.action}</code>{(() => { const h = recordHref(a.entity_type, a.entity_id); const t = `${a.entity_type ?? ""}${a.entity_id !== null ? ` #${a.entity_id}` : ""}`; return h ? <Link href={withBack(h, here)} className="fs-12">{t}</Link> : <span className="text-muted fs-12">{t}</span>; })()}
                      <span className="text-muted fs-12 ms-auto">{formatTs(a.occurred_at, timeZone, false)}</span></li>))}</ul>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
