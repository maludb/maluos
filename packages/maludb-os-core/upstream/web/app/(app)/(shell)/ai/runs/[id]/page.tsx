import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StateBadge, money, tokens } from "@/components/aiops/AiOpsNav";
import PromoteLink from "@/components/aiops/PromoteForm";
import RunVerdict from "@/components/aiops/RunVerdict";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentRunScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Agent run · AI Ops" };

const PRE = { whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 420, overflow: "auto" } as const;

/** Screen `agent-run-view` — one run: what it was asked, what it answered, its model calls, what it did, what it cost. Data: GET /ai/runs/{id} (mcp_agent_runs, else 404). */
export default async function AgentRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();
  return renderScreen(`/ai/runs/${id}`, agentRunScreen, ({ run: r, calls, children, actions, events, verdicts, can }) => (
    <>
      <PageHeader title={`Run #${r.id} — ${r.agent.name ?? "agent"}`} id="agent-run" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Prompt log", href: "/ai/prompt-log" }, { label: `Run #${r.id}` }]}
                  back={r.agent.id !== null ? { href: `/agents/${r.agent.id}?tab=performance`, label: "the agent" } : { href: "/ai/prompt-log", label: "Prompt log" }}>
        <Link href={withBack(`/agents/${r.agent.id}`, here)} className="btn btn-light-brand" id="agent-run-agent-btn"><i className="feather-user me-2"></i><span>The agent</span></Link>
        {can.promote && r.instructions && <PromoteLink kind="run" id={r.id} />}
      </PageHeader>
      <div className="main-content" data-screen="agent-run-view" data-entity="agent_run" data-record-id={r.id}>
        <div className="row">
          <div className="col-lg-8">
            <div className="card" id="agent-run-asked-card"><div className="card-header"><h5 className="card-title">What it was asked</h5></div>
              <div className="card-body"><div style={PRE}>{r.instructions ?? <span className="text-muted">Nothing was recorded.</span>}</div></div></div>
            <div className="card" id="agent-run-result-card"><div className="card-header"><h5 className="card-title">What it answered</h5></div>
              <div className="card-body">{r.error && <p className="text-danger text-break">{r.error}</p>}<div style={PRE}>{r.result ?? <span className="text-muted">{r.status === "running" || r.status === "queued" ? "Still working." : "No answer was recorded."}</span>}</div></div></div>
            <div className="card" id="agent-run-calls-card">
              <div className="card-header"><h5 className="card-title">Model calls <span className="text-muted fs-12 fw-normal">({calls.length})</span></h5>
                <Link href={withBack(`/ai/prompt-log?run=${r.id}&period=all`, here)} className="fs-12" id="agent-run-calls-log">All calls of this run</Link></div>
              <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0">
                <thead className="thead-light"><tr><th>When</th><th>Model</th><th>Outcome</th><th className="text-end">In / out</th><th className="text-end">Cost</th></tr></thead>
                <tbody>
                  {calls.length === 0 && <tr><td colSpan={5} className="text-center text-muted py-4">No model call is recorded for this run.</td></tr>}
                  {calls.map((c) => (<tr key={c.id}><td className="text-nowrap"><Link href={withBack(`/ai/prompt-log/${c.id}`, here)}>{formatTs(c.occurred_at, timeZone, false)}</Link></td><td>{c.model_id !== null ? <Link href={withBack(`/settings/models/${c.model_id}/edit`, here)}>{c.model_name ?? c.provider_model_id}</Link> : c.model_name ?? c.provider_model_id}</td>
                    <td><StateBadge state={c.status} label={c.status_label} /></td><td className="text-end text-nowrap">{tokens(c.input_tokens)} / {tokens(c.output_tokens)}</td><td className="text-end text-nowrap">{money(c.cost, c.currency, 6)}</td></tr>))}
                </tbody></table></div></div>
            </div>
          </div>
          <div className="col-lg-4">
            <RunVerdict runId={r.id} verdicts={verdicts} can={can.verdict} timeZone={timeZone} here={here} />
            <div className="card" id="agent-run-facts-card">
              <div className="card-header d-flex align-items-center gap-2"><h5 className="card-title mb-0">Run</h5><span className="ms-auto"><StateBadge state={r.status} /></span></div>
              <div className="card-body"><dl className="row mb-0">
                <dt className="col-5 text-muted fs-12">Started by</dt><dd className="col-7">{r.requested_by ? <Who who={r.requested_by} name={r.requested_by.name ?? r.requested_by_name ?? `#${r.requested_by.id}`} here={here} /> : r.requested_by_name ?? r.trigger}</dd>
                <dt className="col-5 text-muted fs-12">Trigger</dt><dd className="col-7">{r.trigger}</dd>
                <dt className="col-5 text-muted fs-12">Started</dt><dd className="col-7">{formatTs(r.started_at, timeZone)}</dd>
                <dt className="col-5 text-muted fs-12">Finished</dt><dd className="col-7">{r.finished_at ? formatTs(r.finished_at, timeZone) : "—"}</dd>
                <dt className="col-5 text-muted fs-12">Model</dt><dd className="col-7">{r.model_id !== null ? <Link href={withBack(`/settings/models/${r.model_id}/edit`, here)}>{r.model_name ?? `#${r.model_id}`}</Link> : r.model_name ?? "—"}<div className="fs-12 text-muted">{r.harness}</div></dd>
                {r.application_id !== null && (<><dt className="col-5 text-muted fs-12">Application</dt><dd className="col-7"><Link href={withBack(`/applications/${r.application_id}`, here)}>#{r.application_id}</Link></dd></>)}
                <dt className="col-5 text-muted fs-12">Tokens</dt><dd className="col-7">{tokens(r.input_tokens)} in · {tokens(r.output_tokens)} out{r.cache_read_tokens > 0 && <div className="fs-12 text-muted">{tokens(r.cache_read_tokens)} cached</div>}</dd>
                <dt className="col-5 text-muted fs-12">Cost</dt><dd className="col-7 fw-bold">{money(r.cost, r.currency, 6)}</dd>
                {r.parent_run_id !== null && (<><dt className="col-5 text-muted fs-12">Delegated from</dt><dd className="col-7"><Link href={withBack(`/ai/runs/${r.parent_run_id}`, here)}>run #{r.parent_run_id}</Link></dd></>)}
                {r.approval_request_id !== null && (<><dt className="col-5 text-muted fs-12">Approval</dt><dd className="col-7"><Link href={withBack(`/approvals/${r.approval_request_id}`, here)}>#{r.approval_request_id}</Link></dd></>)}
              </dl></div>
            </div>
            {children.length > 0 && (
              <div className="card" id="agent-run-children-card"><div className="card-header"><h5 className="card-title">Runs it delegated</h5></div>
                <div className="card-body"><ul className="list-unstyled mb-0">{children.map((k) => (
                  <li key={k.id} className="d-flex flex-wrap gap-2 py-1"><Link href={withBack(`/ai/runs/${k.id}`, here)}>#{k.id}</Link>{k.agent_member_id !== null ? <Link href={withBack(`/agents/${k.agent_member_id}`, here)}>{k.agent_name ?? "agent"}</Link> : <span>{k.agent_name}</span>}<StateBadge state={k.status} /><span className="ms-auto text-muted fs-12">{money(k.cost, k.currency, 6)}</span></li>))}</ul></div></div>
            )}
            <div className="card" id="agent-run-events-card"><div className="card-header"><h5 className="card-title">What happened inside it</h5></div>
              <div className="card-body p-0">{events.length === 0
                ? <p className="text-muted fs-12 p-3 mb-0">No events were kept for this run. Runs before 2026-09-20 have none: the runner held them in memory and a restart lost them.</p>
                : <ul className="list-unstyled mb-0 p-3">{events.map((e) => (
                    <li key={e.seq} className="d-flex flex-wrap gap-2 py-1 border-bottom">
                      <span className="fs-12 text-muted">{e.seq}</span>
                      <span>{e.tool_name ?? e.event}</span>
                      {e.status && <span className={`badge ${e.status === "error" || e.status === "denied" ? "bg-danger" : "bg-light text-dark"}`}>{e.status}</span>}
                      {e.duration_ms !== null && <span className="text-muted fs-12">{e.duration_ms} ms</span>}
                      {e.error && <span className="text-danger fs-12 w-100">{e.error}</span>}
                    </li>))}</ul>}</div></div>
            <div className="card" id="agent-run-actions-card"><div className="card-header"><h5 className="card-title">What it did</h5></div>
              <div className="card-body">{actions.length === 0 ? <p className="text-muted mb-0">It changed nothing.</p> : (
                <ul className="list-unstyled mb-0">{actions.map((a) => (<li key={a.id} className="py-1 d-flex flex-wrap gap-2"><code className="fs-12">{a.action}</code>
                  <span className="text-muted fs-12">{(() => { const label = `${a.entity_type ?? ""}${a.entity_id !== null ? ` #${a.entity_id}` : ""}`; const href = recordHref(a.entity_type, a.entity_id); return href ? <Link href={withBack(href, here)}>{label}</Link> : label; })()}</span><span className="text-muted fs-12 ms-auto">{formatTs(a.occurred_at, timeZone, false)}</span></li>))}</ul>)}</div></div>
          </div>
        </div>
      </div>
    </>
  ));
}
