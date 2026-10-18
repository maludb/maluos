import type { Metadata } from "next";
import AiOpsNav, { money, tokens, StateBadge } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { aiStatementsScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Statements · AI Ops" };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");

/**
 * Screen `ai-statements` (A5) — the ledger's period statements: one row per month with its status,
 * what the ledger holds and what the statement says; the chosen month's lines, per provider, model,
 * department, agent, application and currency. Roll up an open month, close a past one, download it
 * as CSV or JSON (the document os.ledger-period/1 — what the accountant receives).
 */
export default async function AiStatementsPage({ searchParams }: { searchParams: Promise<{ period?: string }> }) {
  const { period } = await searchParams;
  const here = await herePath();
  return renderScreen(`/ai/spend/statements.php${period ? `?period=${encodeURIComponent(period)}` : ""}`, aiStatementsScreen, ({ months, selected, lines, can }) => (
    <>
      <PageHeader title="Period statements" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Statements" }]} id="ai-statements">
        <a href={`/api/download?src=${encodeURIComponent(`/ai/spend/export.php?period=${selected.period}&format=csv`)}`} className="btn btn-light-brand" id="ai-statements-download-csv">
          <i className="feather-download me-2"></i><span>CSV</span>
        </a>
        <a href={`/api/download?src=${encodeURIComponent(`/ai/spend/export.php?period=${selected.period}&format=json`)}`} className="btn btn-light-brand" id="ai-statements-download-json">
          <i className="feather-download me-2"></i><span>JSON</span>
        </a>
      </PageHeader>
      <div className="main-content" data-screen="ai-statements">
        <AiOpsNav active="statements" />
        <p className="text-muted fs-12" id="ai-statements-intro">The kernel keeps token accounting only. Each month rolls up into one statement, closed by a super-admin and handed to the accounting system as a file or through its own feed; nothing is posted here.</p>
        <div className="row g-3">
          <div className="col-lg-4">
            <div className="card mb-0" id="ai-statements-months">
              <div className="card-header"><h5 className="card-title">Months</h5></div>
              <div className="list-group list-group-flush">
                {months.length === 0 && <div className="list-group-item text-muted fs-12">No model calls yet.</div>}
                {months.map((m) => (
                  <Link href={`/ai/spend/statements?period=${m.period}`} key={m.period} id={`ai-statements-month-${m.period}`}
                        className={`list-group-item list-group-item-action d-flex justify-content-between align-items-center ${m.period === selected.period ? "active" : ""}`}>
                    <span><span className="fw-semibold">{m.period}</span> <span className={`fs-11 ${m.period === selected.period ? "" : "text-muted"}`}>{m.ledger_calls} calls · {m.ledger_cost} {m.currencies || ""}</span></span>
                    <StateBadge state={m.status} />
                  </Link>
                ))}
              </div>
            </div>
          </div>
          <div className="col-lg-8">
            <div className="card mb-3" id="ai-statements-selected">
              <div className="card-body d-flex flex-wrap justify-content-between align-items-center gap-3">
                <div>
                  <div className="fs-16 fw-bold">{selected.period} <StateBadge state={selected.status} /></div>
                  <div className="fs-12 text-muted">
                    {selected.status === "closed" ? <>Closed {when(selected.closed_at)}{selected.closed_by_name ? <> by <Who who={{ id: selected.closed_by, name: selected.closed_by_name }} here={here} /></> : ""}</> : `Open · last rolled up ${when(selected.rolled_up_at)}`}
                    {selected.note && <> · {selected.note}</>}
                  </div>
                </div>
                <div className="d-flex gap-2">
                  {can.rollup && (
                    <ActionForm path="/ai/spend/rollup.php">
                      <input type="hidden" name="period" value={selected.period} />
                      <SubmitButton className="btn btn-sm btn-light-brand" id="ai-statements-rollup-btn"><i className="feather-refresh-cw me-1"></i>Roll up from the ledger</SubmitButton>
                    </ActionForm>
                  )}
                  {can.close && (
                    <ActionForm path="/ai/spend/close.php" confirm={`Close ${selected.period}? Its statement will never change again; a call that arrives for it later lands in the open month as a late call.`}>
                      <input type="hidden" name="period" value={selected.period} />
                      <SubmitButton className="btn btn-sm btn-primary" id="ai-statements-close-btn"><i className="feather-lock me-1"></i>Close the month</SubmitButton>
                    </ActionForm>
                  )}
                </div>
              </div>
            </div>
            <div className="card mb-0" id="ai-statements-lines-card">
              <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0" id="ai-statements-table">
                <thead className="thead-light"><tr><th>Provider</th><th>Model</th><th>Department</th><th>Agent</th><th>Application</th><th className="text-end">Calls</th><th className="text-end">In / out</th><th className="text-end">Amount</th></tr></thead>
                <tbody>
                  {lines.length === 0 && <tr><td colSpan={8} className="text-center text-muted py-5">No statement lines yet — roll the month up from the ledger.</td></tr>}
                  {lines.map((l) => (
                    <tr key={l.id} id={`ai-statement-line-${l.id}`}>
                      <td>{l.provider}</td><td>{l.model_id !== null ? <Link href={withBack(`/settings/models/${l.model_id}/edit`, here)}>{l.model ?? `#${l.model_id}`}</Link> : l.model ?? "—"}</td><td>{l.department_id !== null ? <Link href={withBack(`/team/departments/${l.department_id}`, here)}>{l.department ?? `#${l.department_id}`}</Link> : l.department ?? "—"}</td><td>{l.agent_id !== null ? <Link href={withBack(`/agents/${l.agent_id}`, here)}>{l.agent ?? `#${l.agent_id}`}</Link> : l.agent ?? "—"}</td><td>{l.application_id !== null ? <Link href={withBack(`/applications/${l.application_id}`, here)}>{l.application ?? `#${l.application_id}`}</Link> : l.application ?? "—"}</td>
                      <td className="text-end">{(() => {
                        const q = new URLSearchParams({ month: selected.period });
                        if (l.model_id !== null) q.set("model", String(l.model_id)); else if (l.provider) q.set("provider", l.provider);
                        if (l.department_id !== null) q.set("department", String(l.department_id));
                        if (l.agent_id !== null) q.set("agent", String(l.agent_id));
                        if (l.application_id !== null) q.set("application", String(l.application_id));
                        return <Link href={withBack(`/ai/prompt-log?${q}`, here)} title="These calls in the prompt log">{l.calls.toLocaleString()}</Link>;
                      })()}{l.late_calls > 0 && <span className="badge bg-soft-warning text-warning ms-1" title={l.note ?? ""}>{l.late_calls} late</span>}</td>
                      <td className="text-end text-nowrap">{tokens(l.input_tokens)} / {tokens(l.output_tokens)}</td>
                      <td className="text-end text-nowrap fw-semibold">{money(l.amount, l.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div></div>
            </div>
          </div>
        </div>
      </div>
    </>
  ));
}
