import type { Metadata } from "next";
import AiOpsNav, { NoRunner, StateBadge } from "@/components/aiops/AiOpsNav";
import FilterCheckbox from "@/components/kit/FilterCheckbox";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { gradedTracesScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Graded traces · AI Ops" };

/** Screen `graded-traces` — real runs graded by continuous evals. Data: GET /ai/evals/traces?agent=&failed=. Nothing grades traces until the runner exists. */
export default async function GradedTracesPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["agent", "eval_set", "failed"]) if (sp[key]) query.set(key, sp[key] as string);
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();
  return renderScreen(`/ai/evals/traces?${query}`, gradedTracesScreen, ({ traces, filters, options }) => (
    <>
      <PageHeader title="Graded traces" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: "Graded traces" }]} id="graded-traces" />
      <div className="main-content" data-screen="graded-traces">
        <AiOpsNav active="traces" />
        <NoRunner note="Trace sampling is part of the eval runner, which is not built — so no real work has been graded, and this list is empty because nothing is looking, not because everything passed." />
        <div className="card stretch stretch-full" id="graded-traces-card">
          <div className="card-header"><h5 className="card-title">Graded runs</h5>
            <div className="d-flex flex-wrap gap-2 align-items-center">
              <FilterSelect id="graded-traces-filter-agent" name="agent" value={filters.agent === null ? "" : String(filters.agent)} options={[{ value: "", label: "Any agent" }, ...options.agents.map((a) => ({ value: String(a.id), label: a.name }))]} />
              <FilterSelect id="graded-traces-filter-set" name="eval_set" value={filters.eval_set === null ? "" : String(filters.eval_set)} options={[{ value: "", label: "Any eval set" }, ...options.sets.map((s) => ({ value: String(s.id), label: s.name }))]} />
              <FilterCheckbox id="graded-traces-filter-failed" name="failed" checked={filters.failed} label="Failed only" />
            </div></div>
          <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0">
            <thead className="thead-light"><tr><th>Run</th><th>Agent</th><th>Eval set</th><th>Result</th><th className="text-end">Score</th><th>Graded</th></tr></thead>
            <tbody>
              {traces.length === 0 && <tr><td colSpan={6} className="text-center text-muted py-5">No graded traces.</td></tr>}
              {traces.map((t) => (<tr key={t.id}><td><Link href={withBack(`/ai/runs/${t.agent_run_id}`, here)}>Run #{t.agent_run_id}</Link></td>
                <td>{t.agent_member_id !== null ? <Link href={withBack(`/agents/${t.agent_member_id}`, here)}>{t.agent_name ?? `#${t.agent_member_id}`}</Link> : t.agent_name ?? "—"}</td>
                <td>{t.eval_set_id !== null ? <Link href={withBack(`/ai/evals/${t.eval_set_id}`, here)}>{t.eval_set_name ?? `#${t.eval_set_id}`}</Link> : "—"}</td>
                <td>{t.passed === null ? "—" : <StateBadge state={t.passed ? "passed" : "failed"} />}</td><td className="text-end">{t.score !== null ? Number(t.score) : "—"}</td><td className="text-muted fs-12">{formatTs(t.graded_at, timeZone, false)}</td></tr>))}
            </tbody></table></div></div>
        </div>
      </div>
    </>
  ));
}
