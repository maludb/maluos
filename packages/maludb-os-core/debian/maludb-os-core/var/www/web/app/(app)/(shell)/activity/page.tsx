import type { Metadata } from "next";
import FilterCheckbox from "@/components/kit/FilterCheckbox";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { activityTrail } from "@/lib/schemas/activity";

export const metadata: Metadata = { title: "Activity" };

const PERIODS: [string, string][] = [["today", "Today"], ["this_week", "This week"], ["this_month", "This month"],
  ["last_30_days", "Last 30 days"], ["all", "Everything"]];
const SOURCES: [string, string][] = [["", "Anywhere"], ["web", "A person on screen"], ["assistant", "The assistant"],
  ["agent", "An agent"], ["mcp", "An MCP client"], ["cron", "A scheduled job"], ["portal", "The portal"], ["webhook", "A webhook"]];
const SOURCE_BADGE: Record<string, string> = { assistant: "info", agent: "warning", mcp: "secondary", cron: "secondary", portal: "dark", webhook: "dark" };

/** Screen `activity` — the trail of what happened, filterable to one record's history. Data: GET /activity. */
export default async function ActivityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["period", "source", "member", "entity_type", "entity_id", "views", "page"]) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }
  const timeZone = (await getSession()).member?.timezone ?? "UTC";
  const here = await herePath();

  return renderScreen(`/activity?${new URLSearchParams(query)}`, activityTrail, (data) => {
    const f = data.filters;
    const { page: _page, ...filterQuery } = query;
    // Filtered to one record's history (a record's "history" link brings people here): name it, link it, offer the way out.
    const { entity_type: _et, entity_id: _ei, ...withoutEntity } = filterQuery;
    const focus = f.entity_type !== "" && f.entity_id !== "" ? { label: `${f.entity_type} #${f.entity_id}`, href: recordHref(f.entity_type, f.entity_id) } : null;
    const everythingQs = new URLSearchParams(withoutEntity).toString();
    return (
      <>
        <PageHeader title="Activity" crumbs={[{ label: "Activity" }]} id="activity">
          <FilterSelect id="activity-filter-period" name="period" value={f.period}
            options={PERIODS.map(([value, label]) => ({ value, label }))} />
          <FilterSelect id="activity-filter-source" name="source" value={f.source}
            options={SOURCES.map(([value, label]) => ({ value, label }))} />
          <FilterSelect id="activity-filter-member" name="member" value={f.member}
            options={[{ value: "", label: "Anyone" }, ...data.options.actors.map((a) => ({ value: String(a.id), label: a.name }))]} />
          {data.options.entity_types.length > 0 && (
            <FilterSelect id="activity-filter-entity-type" name="entity_type" value={f.entity_type}
              options={[{ value: "", label: "Any record" }, ...data.options.entity_types.map((t) => ({ value: t, label: t }))]} />
          )}
          <FilterCheckbox id="activity-filter-views" name="views" checked={f.views} label="Include screen views" />
        </PageHeader>

        <div className="main-content" data-screen="activity">
          <div className="row">
            <div className="col-lg-12">
              <div className="card stretch stretch-full" id="activity-card">
                <div className="card-header">
                  <h5 className="card-title">What has happened</h5>
                  <span className="fs-11 text-muted">every action, by a person, the assistant or an agent</span>
                </div>
                <div className="card-body custom-card-action p-0">
                  {focus && (
                    <p className="fs-12 text-muted px-3 pt-3 mb-0" id="activity-focus">
                      Showing the trail of {focus.href ? <Link href={withBack(focus.href, here)} id="activity-focus-record">{focus.label}</Link> : focus.label}.{" "}
                      <Link href={everythingQs === "" ? "/activity" : `/activity?${everythingQs}`} id="activity-focus-clear">Show everything</Link>
                    </p>
                  )}
                  <div id="activity-results">
                    <div className="table-responsive">
                      <table className="table table-hover mb-0" id="activity-table">
                        <thead className="thead-light">
                          <tr>
                            <th id="activity-col-when">When</th>
                            <th id="activity-col-who">Who</th>
                            <th id="activity-col-what">What</th>
                            <th id="activity-col-record">Record</th>
                            <th id="activity-col-where">Through</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.rows.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="text-center text-muted py-5">
                                <i className="feather-activity fs-1 d-block mb-2 opacity-50"></i>
                                Nothing in that window.
                              </td>
                            </tr>
                          ) : (
                            data.rows.map((row) => {
                              const url = recordHref(row.entity_type, row.entity_id);
                              const color = SOURCE_BADGE[row.source];
                              const record = row.entity_label
                                ? <>{row.entity_label} <span className="text-muted fs-11">{row.entity_type}</span></>
                                : `${row.entity_type} #${row.entity_id}`;
                              return (
                                <tr id={`activity-row-${row.id}`} key={row.id}>
                                  <td className="text-muted fs-12 text-nowrap">{formatTs(row.occurred_at, timeZone, false)}</td>
                                  <td>
                                    {row.actor_member_id !== null
                                      ? <Who who={{ id: row.actor_member_id, name: row.actor_name ?? "system", kind: row.actor_is_agent ? "agent" : "human" }} here={here} />
                                      : row.actor_name ?? "system"}{" "}
                                    {row.actor_is_agent && <span className="badge bg-soft-warning text-warning">agent</span>}
                                  </td>
                                  <td><code className="fs-12">{row.action}</code></td>
                                  <td className="text-muted fs-12">
                                    {row.entity_type === null ? "—" : url ? <Link href={withBack(url, here)}>{record}</Link> : record}
                                  </td>
                                  <td>
                                    {color ? <span className={`badge bg-soft-${color} text-${color}`}>{row.source}</span>
                                           : <span className="text-muted fs-12">{row.source}</span>}
                                  </td>
                                </tr>
                              );
                            })
                          )}
                        </tbody>
                      </table>
                    </div>
                    <Pagination id="activity-pagination" label="Activity pages" pathname="/activity" query={filterQuery}
                                page={data.pagination.page} totalPages={data.pagination.total_pages} maxPages={20} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
