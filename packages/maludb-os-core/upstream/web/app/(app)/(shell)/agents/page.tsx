import type { Metadata } from "next";
import AgentAvatarBadge from "@/components/agents/AgentAvatarBadge";
import { AgentKindBadge, AgentStatusBadge } from "@/components/agents/Badges";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import RecordCard, { CardFilters, CardSection, CardsEmpty, groupBy } from "@/components/kit/RecordCard";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentsList } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Agent HR" };

const FILTERS = ["status", "department", "kind", "page"] as const;
const STATUSES = [["", "Any status"], ["candidate", "Candidate"], ["active", "Active"], ["suspended", "Suspended"], ["offboarded", "Offboarded"]];

/** Screen `agents-list` — HR: the agents we employ. Data: GET /agents/ (any insider). */
export default async function AgentsListPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of FILTERS) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }
  const here = await herePath();

  return renderScreen(`/agents/?${new URLSearchParams(query)}`, agentsList, (data) => {
    const { page: _page, ...filterQuery } = query;
    return (
      <>
        <PageHeader title="HR" crumbs={[{ label: "HR", href: "/agents" }, { label: "Agents" }]} id="agents-list">
          {data.can.admin && (
            <Link href="/team" className="btn btn-light-brand" id="agents-list-people-btn">
              <i className="feather-user me-2"></i><span>People &amp; access</span>
            </Link>
          )}
          <Link href="/skills" className="btn btn-light-brand" id="agents-list-skills-btn">
            <i className="feather-book-open me-2"></i><span>Skills</span>
          </Link>
          <Link href="/memory" className="btn btn-light-brand" id="agents-list-memory-btn">
            <i className="feather-database me-2"></i><span>Memory</span>
          </Link>
          <Link href="/agents/escalations" className="btn btn-light-brand" id="agents-list-escalations-btn">
            <i className="feather-alert-triangle me-2"></i><span>Escalations</span>
          </Link>
          <Link href={withBack("/agents/new", here)} id="agents-list-add-btn" className="btn btn-primary">
            <i className="feather-plus me-2"></i><span>Hire an agent</span>
          </Link>
        </PageHeader>

        <div className="main-content" data-screen="agents-list">
          <CardFilters id="agents-list-card" title="Who we employ">
            <FilterSelect id="agents-list-filter-status" name="status" value={data.filters.status}
              options={STATUSES.map(([value, label]) => ({ value, label }))} />
            <FilterSelect id="agents-list-filter-department" name="department" value={data.filters.department}
              options={[{ value: "", label: "Any department" }, ...data.options.departments.map((d) => ({ value: String(d.id), label: d.name }))]} />
          </CardFilters>
          <div id="agents-list-results">
            {data.agents.length === 0 && (
              <CardsEmpty id="agents-list-empty" icon="feather-cpu">No agents yet. <Link href={withBack("/agents/new", here)}>Hire one</Link>.</CardsEmpty>
            )}
            {groupBy(data.agents, (a) => a.department_name, "No department").map(([department, rows], n) => (
              <CardSection key={department} id={`agents-department-${n}`} title={department} href={rows[0]?.department_id != null ? withBack(`/team/departments/${rows[0].department_id}`, here) : null}
                           note={`${rows.filter((a) => a.status === "active").length} of ${rows.length} active`}>
                {rows.map((a) => (
                  <RecordCard key={a.id} id={`agent-row-${a.id}`} href={withBack(`/agents/${a.id}`, here)} title={a.name} muted={a.status !== "active"}
                    avatar={<AgentAvatarBadge initials={a.avatar.initials} pictureUrl={a.avatar.picture_url} sizeClass="avatar-md flex-shrink-0" />}
                    badges={<AgentStatusBadge status={a.status} />}
                    description={a.description ?? a.job_title ?? "—"}
                    facts={[
                      ...(a.description && a.job_title ? [["Title", a.job_title] as [string, React.ReactNode]] : []),
                      ["Role", a.role_key ?? "—"],
                      ["Manager", a.manager_member_id !== null && a.manager_name ? <Who who={{ id: a.manager_member_id, name: a.manager_name }} here={here} /> : a.manager_name ?? "—"],
                      ["Model", a.model_id !== null && a.model_key ? <Link href={withBack(`/settings/models/${a.model_id}/edit`, here)}>{a.model_key}</Link> : a.model_key ?? "—"],
                    ]}
                    footer={<>
                      <AgentKindBadge kind={a.kind} label={a.kind_label} />
                      {a.kind === "orchestrator" && <span className="text-muted fs-11">roster {a.subagent_count}</span>}
                    </>} />
                ))}
              </CardSection>
            ))}
            <Pagination id="agents-list-pagination" pathname="/agents" query={filterQuery}
                        page={data.page} totalPages={data.total_pages} label="Agent pages" maxPages={20} />
          </div>
        </div>
      </>
    );
  });
}
