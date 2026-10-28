import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import FilterCheckbox from "@/components/kit/FilterCheckbox";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import SubmitButton from "@/components/kit/SubmitButton";
import Who from "@/components/kit/Who";
import { getSession } from "@/lib/api";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";

import { formatTs } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { escalationsList } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Escalations" };

/** Screen `escalations`. Data: GET /agents/escalations (insider; the view narrows to the recipient or the agent's overseers). */
export default async function EscalationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["agent", "open", "page"] as const) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/agents/escalations?${new URLSearchParams(query)}`, escalationsList, (data) => {
    const { page: _page, ...filterQuery } = query;
    return (
      <>
        <PageHeader title="Escalations" crumbs={[{ label: "HR", href: "/agents" }, { label: "Escalations" }]} id="escalations" />

        <div className="main-content" data-screen="escalations">
          <div className="card stretch stretch-full" id="escalations-card">
            <div className="card-header">
              <h5 className="card-title">Raised by agents</h5>
              <div className="d-flex flex-wrap gap-2" id="escalations-filters">
                <FilterSelect id="escalations-filter-agent" name="agent" value={data.filters.agent}
                  options={[{ value: "", label: "Any agent" }, ...data.options.agents.map((a) => ({ value: String(a.id), label: a.name }))]} />
                <FilterCheckbox id="escalations-filter-open" name="open" checked={data.filters.open} label="Open only" />
              </div>
            </div>
            <div className="card-body custom-card-action p-0">
              <div id="escalations-list-results">
                <div className="table-responsive">
                  <table className="table table-hover mb-0" id="escalations-table">
                    <thead className="thead-light">
                      <tr><th>Agent</th><th>Reason</th><th>Summary</th><th>To</th><th>Raised</th><th>Status</th><th className="text-end">Actions</th></tr>
                    </thead>
                    <tbody>
                      {data.escalations.length === 0 ? (
                        <tr><td colSpan={7} className="text-center text-muted py-5">No escalations.</td></tr>
                      ) : data.escalations.map((e) => (
                        <tr id={`escalation-row-${e.id}`} key={e.id}>
                          <td><Link href={withBack(`/agents/${e.agent_member_id}`, here)}>{e.agent_name}</Link></td>
                          <td><span className="badge bg-soft-info text-info">{e.reason_label}</span></td>
                          <td className="fs-12">{e.summary}
                            {(e.entity_type !== null || e.approval_request_id !== null) && (
                              <div className="fs-11 text-muted">
                                {e.entity_type !== null && (recordHref(e.entity_type, e.entity_id)
                                  ? <Link href={withBack(recordHref(e.entity_type, e.entity_id) as string, here)}>about {e.entity_type.replace(/_/g, " ")} #{e.entity_id}</Link>
                                  : <>about {e.entity_type.replace(/_/g, " ")}{e.entity_id !== null && ` #${e.entity_id}`}</>)}
                                {e.approval_request_id !== null && <>{e.entity_type !== null && " · "}<Link href={withBack(`/approvals/${e.approval_request_id}`, here)}>approval #{e.approval_request_id}</Link></>}
                              </div>
                            )}</td>
                          <td className="text-muted fs-12">{e.to_member_id !== null ? <Who who={{ id: e.to_member_id, kind: e.to_member_kind }} name={e.to_member_name ?? `member #${e.to_member_id}`} here={here} /> : "—"}</td>
                          <td className="text-muted fs-12">{formatTs(e.created_at, timeZone)}</td>
                          <td>
                            {e.resolved
                              ? <span className="badge bg-soft-success text-success">Resolved</span>
                              : <span className="badge bg-soft-warning text-warning">Open</span>}
                          </td>
                          <td className="text-end">
                            {!e.resolved && (
                              <ActionForm path="/agents/escalation-resolve.php" className="d-flex gap-1 justify-content-end">
                                <input type="hidden" name="escalation" value={e.id} />
                                <input type="text" name="note" className="form-control form-control-sm" placeholder="Resolution note" style={{ maxWidth: "10rem" }} />
                                <SubmitButton className="btn btn-sm btn-light-brand" id={`escalation-resolve-${e.id}`}>Resolve</SubmitButton>
                              </ActionForm>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination id="escalations-pagination" pathname="/agents/escalations" query={filterQuery}
                            page={data.page} totalPages={data.total_pages} label="Escalation pages" maxPages={20} />
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
