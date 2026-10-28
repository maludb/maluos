import type { Metadata } from "next";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import RecordCard, { CardFilters, CardSection, CardsEmpty } from "@/components/kit/RecordCard";
import { renderScreen } from "@/lib/screen";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { departmentsList } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "Departments" };

/** Screen `departments-list`. Data: GET /team/departments (admin). */
export default async function DepartmentsPage() {
  const here = await herePath();
  return renderScreen("/team/departments", departmentsList, (data) => (
    <>
      <PageHeader title="Departments" id="departments-list" crumbs={[{ label: "People", href: "/team" }, { label: "Departments" }]}>
        <Link href={withBack("/team/departments/new", here)} id="departments-add-btn" className="btn btn-primary">
          <i className="feather-plus me-2"></i><span>New department</span>
        </Link>
      </PageHeader>
      <div className="main-content" data-screen="departments-list">
        <CardFilters id="departments-list-card" title={<>Departments <span className="text-muted fs-12 fw-normal">({data.departments.length})</span></>} />
        {data.departments.length === 0 && <CardsEmpty id="departments-list-empty" icon="feather-layers">No departments yet.</CardsEmpty>}
        {([["standing", "Standing departments", data.departments.filter((d) => d.is_system)],
           ["other", "Other departments", data.departments.filter((d) => !d.is_system)]] as const)
          .filter(([, , rows]) => rows.length > 0)
          .map(([key, title, rows]) => (
            <CardSection key={key} id={`departments-${key}`} title={title}
                         note={key === "standing" ? "In every business: renameable, never deleted" : undefined}>
              {rows.map((d) => (
                <RecordCard key={d.id} id={`department-row-${d.id}`} icon="feather-layers" href={withBack(`/team/departments/${d.id}`, here)} title={d.name}
                  badges={d.is_system && <span className="badge bg-soft-dark text-dark" title="Standing department: renameable, never deleted">Standing</span>}
                  description={d.description ?? undefined}
                  facts={[
                    ["Manager", d.manager_member_id !== null && d.manager_name ? <Link href={withBack(`/team/${d.manager_member_id}`, here)}>{d.manager_name}</Link> : d.manager_name ?? "—"],
                    ["Reports to", d.parent_id !== null && d.parent_name ? <Link href={withBack(`/team/departments/${d.parent_id}`, here)}>{d.parent_name}</Link> : d.parent_name ?? "—"],
                    ["Office", d.home_location_id !== null && d.home_location_name ? <Link href={withBack(`/locations/${d.home_location_id}`, here)}>{d.home_location_name}</Link> : d.home_location_name ?? "—"],
                    ["Members", d.member_count],
                    ["Budget", d.budget_display ?? "—"],
                  ]}
                  footer={<Link href={`/team/departments/${d.id}/edit`} id={`department-row-edit-${d.id}`} className="btn btn-sm btn-light-brand">
                    <i className="feather-edit-2 me-1"></i>Edit</Link>} />
              ))}
            </CardSection>
          ))}
      </div>
    </>
  ));
}
