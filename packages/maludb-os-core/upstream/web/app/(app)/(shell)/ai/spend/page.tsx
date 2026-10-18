import type { Metadata } from "next";
import AiOpsNav, { money, tokens } from "@/components/aiops/AiOpsNav";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { memberHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { aiSpendScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "AI spend · AI Ops" };

/** Where a grouping's row goes: the agent or person, the model, the department; a provider or a day has no page. */
function rowHref(groupBy: string, key: string | null, kind: string | null): string | null {
  if (key === null) return null;
  switch (groupBy) {
    case "agent": return memberHref({ id: key, kind });
    case "model": return `/settings/models/${key}/edit`;
    case "department": return `/team/departments/${key}`;
    default: return null;
  }
}

/** The prompt log filtered to what a row sums (R6): the agent or the person, the model, the provider, the department, or one day (owner, 2026-09-27). */
function callsHref(groupBy: string, key: string | null, kind: string | null, period: string): string | null {
  if (key === null) return null;
  const q = new URLSearchParams({ period });
  switch (groupBy) {
    case "agent": q.set(kind === "agent" ? "agent" : "acting", key); break;
    case "model": q.set("model", key); break;
    case "provider": q.set("provider", key); break;
    case "department": q.set("department", key); break;
    case "day": q.delete("period"); q.set("day", key); break;
    default: return null;
  }
  return `/ai/prompt-log?${q}`;
}

/** Screen `ai-spend` — cost, tokens, latency and what caching saved. Data: GET /ai/spend/?period=&group_by= (rows are what mcp_prompt_ledger shows this person). A row is a link to what it sums, carrying this page as `back` (click-around, step 0). */
export default async function AiSpendPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["period", "group_by"]) if (sp[key]) query.set(key, sp[key] as string);
  const here = await herePath();
  return renderScreen(`/ai/spend/?${query}`, aiSpendScreen, ({ period, group_by, rows, totals, sees_everything, options }) => {
    const top = Math.max(...rows.map((r) => Number(r.cost)), 0);
    return (
      <>
        <PageHeader title="AI spend" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Spend" }]} id="ai-spend" />
        <div className="main-content" data-screen="ai-spend">
          <AiOpsNav active="spend" />
          {!sees_everything && <p className="text-muted fs-12" id="ai-spend-scope">This is the spend you may see — your own calls and the agents you manage — not necessarily the whole business&apos;s.</p>}
          <div className="row g-3 mb-1">
            {[["Cost", money(totals.cost, totals.currency)], ["Calls", totals.calls.toLocaleString()], ["Tokens", tokens(totals.tokens)], ["Saved by caching", money(totals.cache_saving, totals.currency)]].map(([label, value]) => (
              <div className="col-6 col-lg-3" key={label}><div className="card mb-0"><div className="card-body py-3"><div className="text-muted fs-12">{label}</div><div className="fs-5 fw-bold">{value}</div></div></div></div>
            ))}
          </div>
          <div className="card stretch stretch-full mt-3" id="ai-spend-card">
            <div className="card-header"><h5 className="card-title">By {options.groups.find((g) => g.id === group_by)?.name.toLowerCase()}</h5>
              <div className="d-flex flex-wrap gap-2">
                <FilterSelect id="ai-spend-filter-period" name="period" value={period} options={options.periods.map((p) => ({ value: p.id, label: p.name }))} />
                <FilterSelect id="ai-spend-filter-group" name="group_by" value={group_by} options={options.groups.map((g) => ({ value: g.id, label: `By ${g.name.toLowerCase()}` }))} />
              </div></div>
            <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0" id="ai-spend-table">
              <thead className="thead-light"><tr><th>{options.groups.find((g) => g.id === group_by)?.name}</th><th style={{ minWidth: 160 }}>Share</th><th className="text-end">Calls</th><th className="text-end">Failed</th><th className="text-end">In / out</th><th className="text-end">Avg latency</th><th className="text-end">Saved</th><th className="text-end">Cost</th></tr></thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={8} className="text-center text-muted py-5">No model calls in this period that you may see.</td></tr>}
                {rows.map((r) => {
                  const href = rowHref(group_by, r.key, r.kind);
                  const calls = callsHref(group_by, r.key, r.kind, period);
                  return (
                  <tr key={r.key ?? r.label}><td>{href ? <Link href={withBack(href, here)} className="fw-semibold" id={`ai-spend-row-${r.key}`}>{r.label}</Link> : r.label}</td>
                    <td><div className="progress" style={{ height: 6 }} role="img" aria-label={`${top > 0 ? Math.round((Number(r.cost) / top) * 100) : 0}% of the largest`}><div className="progress-bar" style={{ width: `${top > 0 ? (Number(r.cost) / top) * 100 : 0}%` }}></div></div></td>
                    <td className="text-end">{calls ? <Link href={withBack(calls, here)} title="These calls in the prompt log">{r.calls.toLocaleString()}</Link> : r.calls.toLocaleString()}</td><td className={`text-end ${r.failed > 0 ? "text-danger" : "text-muted"}`}>{r.failed}</td>
                    <td className="text-end text-nowrap">{tokens(r.input_tokens)} / {tokens(r.output_tokens)}</td><td className="text-end text-nowrap">{r.avg_latency_ms !== null ? `${(r.avg_latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                    <td className="text-end text-nowrap text-muted">{money(r.cache_saving, r.currency)}</td><td className="text-end text-nowrap fw-semibold">{money(r.cost, r.currency)}</td></tr>
                  );
                })}
              </tbody></table></div></div>
          </div>
        </div>
      </>
    );
  });
}
