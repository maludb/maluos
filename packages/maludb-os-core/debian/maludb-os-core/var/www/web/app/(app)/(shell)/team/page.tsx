import type { Metadata } from "next";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import SearchInput from "@/components/kit/SearchInput";
import RoleBadge from "@/components/team/RoleBadge";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { memberHref, withBack } from "@/lib/routes";
import { teamList } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "People & access" };

/** Screen `team-list` — people and agents, and the door to each one's access. Data: GET /team/ (admin). */
export default async function TeamListPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["q", "kind", "role", "department", "page"]) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }

  const here = await herePath();
  return renderScreen(`/team/?${new URLSearchParams(query)}`, teamList, (data) => {
    const f = data.filters;
    const { page: _page, ...filterQuery } = query;
    return (
      <>
        <PageHeader title={f.kind === "human" ? "Human Workforce" : "People & access"} id="team-list"
                    crumbs={[{ label: "HR", href: "/agents" }, { label: f.kind === "human" ? "Human Workforce" : "People & access" }]}>
          <SearchInput id="team-list-search" value={f.q} placeholder="Search name or email" />
          <Link href="/team/invitations" id="team-invitations-btn" className="btn btn-primary">
            <i className="feather-user-plus me-2"></i><span>Invite</span>
          </Link>
          <Link href="/team/departments" id="team-departments-btn" className="btn btn-light-brand">
            <i className="feather-git-branch me-2"></i><span>Departments</span>
          </Link>
        </PageHeader>

        <div className="main-content" data-screen="team-list">
          <div className="row">
            <div className="col-lg-12">
              <div className="card stretch stretch-full" id="team-list-card">
                <div className="card-header">
                  <h5 className="card-title">{f.kind === "human" ? "The people who work here" : "People and agents"}</h5>
                  <div className="d-flex flex-wrap gap-2" id="team-list-filters">
                    <FilterSelect id="team-list-filter-kind" name="kind" value={f.kind === "both" ? "" : f.kind}
                      options={[{ value: "", label: "Everyone" }, { value: "human", label: "People" }, { value: "agent", label: "Agents" }]} />
                    <FilterSelect id="team-list-filter-role" name="role" value={f.role}
                      options={[{ value: "", label: "Any role" }, { value: "super_admin", label: "Super-admin" },
                                { value: "dept_admin", label: "Dept-admin" }, { value: "user", label: "User" }]} />
                    <FilterSelect id="team-list-filter-department" name="department" value={f.department}
                      options={[{ value: "", label: "Any department" }, ...data.options.departments.map((d) => ({ value: String(d.id), label: d.name }))]} />
                  </div>
                </div>
                <div className="card-body custom-card-action p-0">
                  <div id="team-list-results">
                    <div className="table-responsive">
                      <table className="table table-hover mb-0" id="team-list-table">
                        <thead className="thead-light">
                          <tr>
                            <th id="team-list-col-name">Name</th>
                            <th id="team-list-col-kind">Kind</th>
                            <th id="team-list-col-role">Role</th>
                            <th id="team-list-col-departments">Departments</th>
                            <th id="team-list-col-email">Email</th>
                            <th className="text-end">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.members.length === 0 ? (
                            <tr>
                              <td colSpan={6} className="text-center text-muted py-5">
                                <i className="feather-users fs-1 d-block mb-2 opacity-50"></i>
                                {f.q !== "" ? `Nobody matches “${f.q}”.` : "Nobody here yet."}
                              </td>
                            </tr>
                          ) : (
                            data.members.map((m) => (
                              <tr id={`team-row-${m.id}`} key={m.id}>
                                <td><Link href={withBack(memberHref({ id: m.id, kind: m.kind }) ?? `/team/${m.id}`, here)} className="fw-medium">{m.display_name}</Link></td>
                                <td>
                                  <span className={`badge bg-soft-${m.kind === "agent" ? "info text-info" : "secondary text-secondary"}`}>
                                    {m.kind === "agent" ? "Agent" : "Person"}
                                  </span>
                                </td>
                                <td><RoleBadge role={m.business_role} /></td>
                                <td className="text-muted">{m.department_links.length > 0
                                  ? m.department_links.map((d, i) => <span key={d.id}>{i > 0 && ", "}<Link href={withBack(`/team/departments/${d.id}`, here)}>{d.name}</Link></span>)
                                  : m.departments.length > 0 ? m.departments.join(", ") : "—"}</td>
                                <td className="text-muted">{m.email ?? "—"}</td>
                                <td className="text-end">
                                  <Link href={`/team/${m.id}/edit`} className="btn btn-sm btn-light-brand">Access</Link>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    <Pagination id="team-list-pagination" label="Team pages" pathname="/team" query={filterQuery}
                                page={data.pagination.page} totalPages={data.pagination.total_pages} />
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
