import type { Metadata } from "next";
import ApplicationCard from "@/components/applications/ApplicationCard";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import FilterCheckbox from "@/components/kit/FilterCheckbox";
import FilterSelect from "@/components/kit/FilterSelect";
import SearchInput from "@/components/kit/SearchInput";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { renderScreen } from "@/lib/screen";
import { applicationsList } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "Applications" };

/**
 * Screen `applications-list` — the inventory: what runs first, by name and highlighted (with a switch to
 * show nothing else); then everything the business could run, by business area. A search (?q=) over
 * name, description, vendor and area. Data: GET /applications/ (insider).
 */
export default async function ApplicationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["q", "area", "department", "health", "gaps", "active", "retired"]) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }

  const here = await herePath();
  return renderScreen(`/applications/?${new URLSearchParams({ ...query, layout: "running" })}`, applicationsList, (data) => {
    const f = data.filters;
    return (
      <>
        <PageHeader title="Applications" id="applications-list" crumbs={[{ label: "Applications" }]}>
          {data.can.edit && (
            <Link href={withBack("/applications/new", here)} id="applications-list-add-btn" className="btn btn-primary">
              <i className="feather-plus me-2"></i><span>Register application</span>
            </Link>
          )}
        </PageHeader>

        <div className="main-content" data-screen="applications-list">
          <div className="card" id="applications-list-card">
            <div className="card-body d-flex flex-column gap-3">
              <div className="d-flex flex-wrap align-items-center gap-3">
                <div className="flex-grow-1" style={{ minWidth: "14rem", maxWidth: "28rem" }}>
                  <SearchInput id="applications-list-search" value={f.q} placeholder="Search applications" />
                </div>
                <FilterCheckbox id="applications-list-filter-active" name="active" checked={f.active} label="Active only" variant="switch" />
                <span className="ms-auto fs-12 text-muted" id="applications-list-count">
                  {data.counts.active} active{f.active ? "" : ` · ${data.counts.total} shown`}
                </span>
              </div>
              <div className="d-flex flex-wrap align-items-center gap-2" id="applications-list-filters">
                <FilterSelect id="applications-list-filter-area" name="area" value={f.area}
                  options={[{ value: "", label: "Every business area" }, ...data.options.areas.map((a) => ({ value: String(a.id), label: a.name }))]} />
                <FilterSelect id="applications-list-filter-department" name="department" value={f.department}
                  options={[{ value: "", label: "Any department" }, ...data.options.departments.map((d) => ({ value: String(d.id), label: d.name }))]} />
                <FilterSelect id="applications-list-filter-health" name="health" value={f.health}
                  options={[{ value: "", label: "Any health" }, { value: "up", label: "Up" }, { value: "degraded", label: "Degraded" },
                            { value: "down", label: "Down" }, { value: "unknown", label: "Unknown" }]} />
                <FilterCheckbox id="applications-list-filter-gaps" name="gaps" checked={f.gaps} label="Gaps only" />
                <FilterCheckbox id="applications-list-filter-retired" name="retired" checked={f.retired} label="Show retired" />
              </div>
            </div>
          </div>

          {data.running.length === 0 && data.areas.length === 0 ? (
            <div className="card" id="applications-list-empty">
              <div className="card-body text-center text-muted py-5">
                <i className="feather-grid fs-1 d-block mb-2 opacity-50"></i>
                {f.q !== "" ? `Nothing matches “${f.q}”.` : "Nothing matches yet."}
              </div>
            </div>
          ) : (
            <>
              {data.running.length > 0 && (
                <section id="applications-running" className="mb-4">
                  <div className="d-flex align-items-baseline justify-content-between gap-2 mb-3">
                    <h6 className="fw-bold mb-0"><i className="feather-activity text-success me-2"></i>Running now</h6>
                    <span className="fs-12 text-muted">{data.running.length} active</span>
                  </div>
                  <div className="row g-3">
                    {data.running.map((card) => <ApplicationCard key={card.key} card={card} can={data.can} here={here} showArea />)}
                  </div>
                </section>
              )}
              {data.areas.length > 0 && (
                <h6 className="fw-bold text-muted mb-3" id="applications-others-title">Not running — available, planned or turned off</h6>
              )}
              {data.areas.map((area) => (
                <section key={area.id ?? "other"} id={`applications-area-${area.id ?? "other"}`} className="mb-4">
                  <div className="d-flex align-items-baseline justify-content-between gap-2 mb-2">
                    <span className="fs-12 fw-semibold text-uppercase text-muted">{area.name}</span>
                    <span className="fs-12 text-muted">{area.applications.length}</span>
                  </div>
                  <div className="row g-3">
                    {area.applications.map((card) => <ApplicationCard key={card.key} card={card} can={data.can} here={here} />)}
                  </div>
                </section>
              ))}
            </>
          )}
        </div>
      </>
    );
  });
}
