import type { Metadata } from "next";
import AiOpsNav, { StateBadge, money, tokens } from "@/components/aiops/AiOpsNav";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { promptLogScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Prompt log · AI Ops" };

/**
 * Screen `prompt-log` — every model call. Data: GET /ai/prompt-log/?agent=&status=&request_id=&run=&period=&page=
 * (any insider; mcp_prompt_ledger decides the rows). The list never carries a prompt — open a call for that.
 */
export default async function PromptLogPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["agent", "status", "request_id", "run", "period", "page", "acting", "model", "provider", "department", "application", "month", "day"] as const) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/ai/prompt-log/?${new URLSearchParams(query)}`, promptLogScreen, (data) => {
    const { calls, filters, filter_labels: labels, options, totals, can } = data;
    const { page: _page, ...filterQuery } = query;
    // The filters a deep link arrives with (step 4): named in the header, each one clearable on its own.
    const pointed: [string, string, string | null][] = [
      ["run", filters.run !== null ? `run #${filters.run}` : "", `/ai/runs/${filters.run}`],
      ["request_id", filters.request_id ? `request ${filters.request_id}` : "", null],
      ["acting", labels.acting ? `for ${labels.acting}` : filters.acting !== null ? `for member #${filters.acting}` : "", `/team/${filters.acting}`],
      ["model", labels.model ?? (filters.model !== null ? `model #${filters.model}` : ""), `/settings/models/${filters.model}/edit`],
      ["provider", filters.provider, null],
      ["department", labels.department ?? (filters.department !== null ? `department #${filters.department}` : ""), `/team/departments/${filters.department}`],
      ["application", labels.application ?? (filters.application !== null ? `application #${filters.application}` : ""), `/applications/${filters.application}`],
      ["month", labels.month ?? filters.month, null],
      ["day", labels.day ?? filters.day, null],
    ];
    const active = pointed.filter(([, label]) => label !== "");
    const without = (name: string) => { const q = { ...filterQuery }; delete q[name]; const qs = new URLSearchParams(q).toString(); return qs === "" ? "/ai/prompt-log" : `/ai/prompt-log?${qs}`; };
    return (
      <>
        <PageHeader title="Prompt log" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Prompt log" }]} id="prompt-log" />
        <div className="main-content" data-screen="prompt-log">
          <AiOpsNav active="log" />
          <div className="row g-3 mb-1">
            {[["Calls", String(data.total)], ["Cost", money(totals.cost, calls[0]?.currency ?? "USD")], ["Tokens", tokens(totals.tokens)], ["Failed", String(totals.failed)]].map(([label, value]) => (
              <div className="col-6 col-lg-3" key={label}><div className="card mb-0"><div className="card-body py-3"><div className="text-muted fs-12">{label}</div><div className="fs-5 fw-bold">{value}</div></div></div></div>
            ))}
          </div>
          <div className="card stretch stretch-full mt-3" id="prompt-log-card">
            <div className="card-header">
              <h5 className="card-title">Model calls{active.length > 0 && <span className="fw-normal fs-12 ms-2" id="prompt-log-pointed">
                {active.map(([name, label, href]) => (
                  <span className="badge bg-soft-secondary text-dark me-1" key={name} id={`prompt-log-pointed-${name}`}>
                    {href ? <Link href={withBack(href, here)} className="text-dark">{label}</Link> : label}
                    {" "}<Link href={without(name)} className="text-muted" aria-label={`Clear ${name}`} title="Clear">×</Link>
                  </span>
                ))}
              </span>}</h5>
              <div className="d-flex flex-wrap gap-2" id="prompt-log-filters">
                <FilterSelect id="prompt-log-filter-period" name="period" value={filters.period} options={options.periods.map((p) => ({ value: p.id, label: p.name }))} />
                <FilterSelect id="prompt-log-filter-agent" name="agent" value={filters.agent === null ? "" : String(filters.agent)}
                  options={[{ value: "", label: "Anyone" }, ...options.agents.map((a) => ({ value: String(a.id), label: a.name }))]} />
                <FilterSelect id="prompt-log-filter-status" name="status" value={filters.status}
                  options={[{ value: "", label: "Any outcome" }, { value: "failed", label: "Anything that failed" }, ...options.statuses.map((s) => ({ value: s.id, label: s.name }))]} />
              </div>
            </div>
            <div className="card-body custom-card-action p-0">
              <div className="table-responsive">
                <table className="table table-hover mb-0" id="prompt-log-table">
                  <thead className="thead-light"><tr><th>When</th><th>Who</th><th>Model</th><th>Outcome</th><th className="text-end">In / out</th><th className="text-end">Latency</th><th className="text-end">Cost</th></tr></thead>
                  <tbody>
                    {calls.length === 0 && <tr><td colSpan={7} className="text-center text-muted py-5">No model calls here that you may see.</td></tr>}
                    {calls.map((c) => (
                      <tr key={c.id} id={`ledger-call-row-${c.id}`}>
                        <td className="text-nowrap"><Link href={withBack(`/ai/prompt-log/${c.id}`, here)} className="fw-semibold">{formatTs(c.occurred_at, timeZone, false)}</Link>
                          {c.run_id !== null && <div><Link href={withBack(`/ai/runs/${c.run_id}`, here)} className="fs-12 text-muted">run #{c.run_id}</Link></div>}</td>
                        <td>{c.agent ? <Link href={withBack(`/agents/${c.agent.id}`, here)}>{c.agent.name ?? "Agent"}</Link> : <Who who={c.acting} name={c.acting.name ?? "Someone"} here={here} />}{c.agent && <div className="fs-12 text-muted">for <Who who={c.acting} name={c.acting.name ?? "someone"} here={here} /></div>}</td>
                        <td>{c.model_id !== null ? <Link href={withBack(`/settings/models/${c.model_id}/edit`, here)}>{c.model_name ?? c.provider_model_id}</Link> : c.model_name ?? c.provider_model_id}<div className="fs-12 text-muted">{c.provider} · {c.harness}</div></td>
                        <td><StateBadge state={c.status} label={c.status_label} />{c.error_code && <div className="fs-12 text-danger">{c.error_code}</div>}</td>
                        <td className="text-end text-nowrap">{tokens(c.input_tokens)} / {tokens(c.output_tokens)}{c.cache_read_tokens > 0 && <div className="fs-12 text-muted">{tokens(c.cache_read_tokens)} cached</div>}</td>
                        <td className="text-end text-nowrap">{c.latency_ms !== null ? `${(c.latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                        <td className="text-end text-nowrap">{money(c.cost, c.currency, 6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination id="prompt-log-pagination" pathname="/ai/prompt-log" query={filterQuery} page={data.page}
                          totalPages={Math.max(1, Math.ceil(data.total / data.page_size))} label="Prompt log pages" maxPages={20} />
            </div>
          </div>
        </div>
      </>
    );
  });
}
