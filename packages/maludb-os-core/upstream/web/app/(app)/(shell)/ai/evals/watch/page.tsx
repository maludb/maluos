import type { Metadata } from "next";
import AiOpsNav, { NoRunner, StateBadge } from "@/components/aiops/AiOpsNav";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { evalWatchScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Eval watch · AI Ops" };

/** Screen `eval-watch` — the Audit department's watch: standing schedules and open degradation alerts. Data: GET /ai/evals/watch?agent=&severity=&status=. */
export default async function EvalWatchPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["agent", "eval_set", "severity", "status"]) if (sp[key]) query.set(key, sp[key] as string);
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();
  return renderScreen(`/ai/evals/watch?${query}`, evalWatchScreen, ({ schedules, alerts, filters, options }) => (
    <>
      <PageHeader title="Eval watch" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals", href: "/ai/evals" }, { label: "Watch" }]} id="eval-watch" />
      <div className="main-content" data-screen="eval-watch">
        <AiOpsNav active="watch" />
        <NoRunner note="No alerts does not mean no degradation: alerts are raised by the eval runner, which is not built. The schedules below are saved and waiting for it." />
        <div className="row">
          <div className="col-lg-7"><div className="card" id="eval-watch-alerts-card">
            <div className="card-header"><h5 className="card-title">Alerts</h5>
              <div className="d-flex flex-wrap gap-2">
                <FilterSelect id="eval-watch-filter-agent" name="agent" value={filters.agent === null ? "" : String(filters.agent)} options={[{ value: "", label: "Any agent" }, ...options.agents.map((a) => ({ value: String(a.id), label: a.name }))]} />
                <FilterSelect id="eval-watch-filter-set" name="eval_set" value={filters.eval_set === null ? "" : String(filters.eval_set)} options={[{ value: "", label: "Any eval set" }, ...options.sets.map((s) => ({ value: String(s.id), label: s.name }))]} />
                <FilterSelect id="eval-watch-filter-status" name="status" value={filters.status} options={[{ value: "", label: "Open and acknowledged" }, { value: "open", label: "Open" }, { value: "acknowledged", label: "Acknowledged" }, { value: "resolved", label: "Resolved" }, { value: "all", label: "All" }]} />
                <FilterSelect id="eval-watch-filter-severity" name="severity" value={filters.severity} options={[{ value: "", label: "Any severity" }, { value: "critical", label: "Critical" }, { value: "warning", label: "Warning" }, { value: "info", label: "Info" }]} />
              </div></div>
            <div className="card-body">
              {alerts.length === 0 ? <p className="text-muted mb-0" id="eval-watch-no-alerts">No alerts — and nothing is able to raise one yet.</p> : alerts.map((a) => (
                <div key={a.id} className="border rounded p-3 mb-2"><div className="d-flex flex-wrap gap-2 align-items-center"><Link href={withBack(`/ai/evals/alerts/${a.id}`, here)} className="fw-semibold">Alert #{a.id}</Link>
                  <Link href={withBack(`/ai/evals/${a.eval_set_id}`, here)}>{a.eval_set_name}</Link>{a.agent && <Link href={withBack(`/agents/${a.agent.id}`, here)} className="text-muted">{a.agent.name ?? "Agent"}</Link>}
                  <StateBadge state={a.status} /><span className={`badge bg-soft-${a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : "info"} text-${a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : "info"}`}>{a.severity}</span>
                  <span className="text-muted fs-12 ms-auto">{formatTs(a.opened_at, timeZone, false)}</span></div><div className="fs-12 mt-1">{a.detail}</div></div>))}
            </div></div></div>
          <div className="col-lg-5"><div className="card" id="eval-watch-schedules-card"><div className="card-header"><h5 className="card-title">Standing schedules</h5></div>
            <div className="card-body">
              {schedules.length === 0 ? <p className="text-muted mb-0">No eval set is on a schedule.</p> : (
                <ul className="list-unstyled mb-0">{schedules.map((h) => (<li key={h.id} className="py-2 border-bottom"><Link href={withBack(`/ai/evals/${h.eval_set_id}`, here)} className="fw-semibold">{h.eval_set_name}</Link> {!h.active && <span className="badge bg-soft-secondary text-secondary">Off</span>}
                  <div className="fs-12 text-muted">{h.cadence_label} · {h.kind_label.toLowerCase()}{h.agent_name ? <> · {h.agent_member_id !== null ? <Link href={withBack(`/agents/${h.agent_member_id}`, here)}>{h.agent_name}</Link> : h.agent_name}</> : ""} · next run: {h.next_run_at ? formatTs(h.next_run_at, timeZone, false) : "never — no runner yet"}
                    {h.last_eval_run_id !== null && <> · last: <Link href={withBack(`/ai/evals/runs/${h.last_eval_run_id}`, here)}>run #{h.last_eval_run_id}</Link></>}</div></li>))}</ul>)}
            </div></div></div>
        </div>
      </div>
    </>
  ));
}
