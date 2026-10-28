import type { Metadata } from "next";
import AiOpsNav, { NoRunner, StateBadge } from "@/components/aiops/AiOpsNav";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { evalSetsScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Evals · AI Ops" };

/**
 * Screen `eval-sets` — eval sets per agent or role. Data: GET /ai/evals/?agent=&status= (people only). Arriving with
 * ?promote_ledger= / ?promote_run= (from a call or a run) turns each set into "add the case here".
 */
export default async function EvalSetsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["agent", "status"]) if (sp[key]) query.set(key, sp[key] as string);
  const from = /^\d+$/.test(sp.promote_ledger ?? "") ? `from_ledger=${sp.promote_ledger}` : /^\d+$/.test(sp.promote_run ?? "") ? `from_run=${sp.promote_run}` : null;
  const here = await herePath();
  return renderScreen(`/ai/evals/?${query}`, evalSetsScreen, ({ sets, filters, runner_note, options, can }) => (
    <>
      <PageHeader title="Evals" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "Evals" }]} id="eval-sets">
        {can.write && <Link href={withBack("/ai/evals/new", here)} id="eval-sets-add-btn" className="btn btn-primary"><i className="feather-plus me-2"></i><span>New eval set</span></Link>}
      </PageHeader>
      <div className="main-content" data-screen="eval-sets">
        <AiOpsNav active="evals" />
        <NoRunner note={runner_note} />
        {from && <div className="alert alert-soft-primary-message" id="eval-sets-promote" role="status">Choose the set this real {from.startsWith("from_ledger") ? "call" : "run"} becomes a case of.</div>}
        <div className="card stretch stretch-full" id="eval-sets-card">
          <div className="card-header"><h5 className="card-title">Eval sets</h5>
            <div className="d-flex flex-wrap gap-2">
              <FilterSelect id="eval-sets-filter-agent" name="agent" value={filters.agent === null ? "" : String(filters.agent)} options={[{ value: "", label: "Any agent" }, ...options.agents.map((a) => ({ value: String(a.id), label: a.name }))]} />
              <FilterSelect id="eval-sets-filter-status" name="status" value={filters.status} options={[{ value: "", label: "Any status" }, { value: "active", label: "Active" }, { value: "draft", label: "Draft" }, { value: "retired", label: "Retired" }]} />
            </div></div>
          <div className="card-body p-0"><div className="table-responsive"><table className="table table-hover mb-0" id="eval-sets-table">
            <thead className="thead-light"><tr><th>Set</th><th>For</th><th className="text-end">Cases</th><th className="text-end">Pass at</th><th>Status</th>{from && <th className="text-end">Add here</th>}</tr></thead>
            <tbody>
              {sets.length === 0 && <tr><td colSpan={from ? 6 : 5} className="text-center text-muted py-5">No eval sets yet{can.write ? " — write the first one." : " that you may see."}</td></tr>}
              {sets.map((s) => (
                <tr key={s.id} id={`eval-set-row-${s.id}`}>
                  <td><Link href={withBack(`/ai/evals/${s.id}`, here)} className="fw-semibold">{s.name}</Link>{s.description && <div className="fs-12 text-muted text-truncate" style={{ maxWidth: 380 }}>{s.description}</div>}</td>
                  <td>{s.agent ? <Link href={withBack(`/agents/${s.agent.id}`, here)}>{s.agent.name ?? "An agent"}</Link> : `Role: ${s.role_key}`}{s.department_name && <div className="fs-12 text-muted">{s.department_id !== null ? <Link href={withBack(`/team/departments/${s.department_id}`, here)} className="text-muted">{s.department_name}</Link> : s.department_name}</div>}</td>
                  <td className="text-end">{s.active_case_count}{s.case_count !== s.active_case_count && <span className="text-muted"> / {s.case_count}</span>}</td>
                  <td className="text-end">{Number(s.pass_threshold)}%</td><td><StateBadge state={s.status} label={s.status_label} /></td>
                  {from && <td className="text-end">{can.write && <Link href={`/ai/evals/${s.id}/cases/new?${from}`} className="btn btn-sm btn-light-brand">Add the case here</Link>}</td>}
                </tr>
              ))}
            </tbody></table></div></div>
        </div>
      </div>
    </>
  ));
}
