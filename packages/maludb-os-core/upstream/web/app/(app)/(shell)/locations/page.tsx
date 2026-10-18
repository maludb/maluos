import type { Metadata } from "next";
import { PresenceBadge } from "@/components/estate/LocationBadges";
import FilterCheckbox from "@/components/kit/FilterCheckbox";
import FilterSelect from "@/components/kit/FilterSelect";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import PageHeader from "@/components/kit/PageHeader";
import Pagination from "@/components/kit/Pagination";
import RecordCard, { CardFilters, CardSection, CardsEmpty } from "@/components/kit/RecordCard";
import { ucfirst } from "@/lib/format";
import { renderScreen } from "@/lib/screen";
import { locationsList } from "@/lib/schemas/estate";

export const metadata: Metadata = { title: "Work Locations" };

/** The estate tree, top down: a building holds offices, an office holds desks. */
const KINDS: [string, string, string][] = [["building", "Buildings", "feather-home"], ["office", "Offices", "feather-server"], ["desk", "Desks", "feather-monitor"],
  // A site is a place the business trades from, not a machine (db/141).
  ["site", "Sites", "feather-map-pin"]];

/**
 * Screen `locations-list` — every building, office and desk. Data: GET /locations/ (insider;
 * changing the estate needs the locations grant, so Edit/Add appear only with it — nobody is
 * walked into a refusal by a button).
 */
export default async function LocationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query: Record<string, string> = {};
  for (const name of ["kind", "parent", "online", "status", "sort", "page"]) {
    const v = params[name];
    if (typeof v === "string" && v !== "") query[name] = v;
  }

  const here = await herePath();
  return renderScreen(`/locations/?${new URLSearchParams(query)}`, locationsList, (data) => {
    const canEdit = data.can.edit;
    const { page: _page, ...filterQuery } = query;
    return (
      <>
        <PageHeader title="Work Locations" id="locations-list" crumbs={[{ label: "Work Locations" }]}>
          {canEdit && (
            <Link href={withBack("/locations/new", here)} id="locations-list-add-btn" className="btn btn-primary">
              <i className="feather-plus me-2"></i><span>Add location</span>
            </Link>
          )}
        </PageHeader>

        <div className="main-content" data-screen="locations-list">
          <CardFilters id="locations-list-card" title="Every building, office, desk and site">
            <FilterSelect id="locations-list-filter-kind" name="kind" value={data.filters.kind}
              options={[{ value: "", label: "Any kind" }, { value: "building", label: "Building" },
                        { value: "office", label: "Office" }, { value: "desk", label: "Desk" },
                        { value: "site", label: "Site" }]} />
            <FilterCheckbox id="locations-list-filter-online" name="online" checked={data.filters.online} label="Online now" />
            <FilterCheckbox id="locations-list-filter-retired" name="status" valueOn="retired"
                            checked={data.filters.retired} label="Show retired" />
          </CardFilters>
          <div id="locations-list-results">
            {data.locations.length === 0 && (
              <CardsEmpty id="locations-list-empty" icon="feather-server">
                No locations yet — add the office this platform runs on.{" "}
                {canEdit && <Link href={withBack("/locations/new?kind=office", here)}>Add one</Link>}
              </CardsEmpty>
            )}
            {KINDS.map(([kind, title, icon]) => {
              const rows = data.locations.filter((loc) => loc.kind === kind);
              if (rows.length === 0) return null;
              return (
                <CardSection key={kind} id={`locations-kind-${kind}`} title={title}
                             note={kind === "site" ? `${rows.length} site${rows.length === 1 ? "" : "s"}`
                               : `${rows.filter((loc) => loc.presence === "online" && loc.status !== "retired").length} of ${rows.length} online`}>
                  {rows.map((loc) => {
                    const retired = loc.status === "retired";
                    const sitingColor = loc.siting === "onsite" ? "success" : "secondary";
                    if (kind === "site") {
                      return (
                        <RecordCard key={loc.id} id={`location-row-${loc.id}`} icon={icon} href={withBack(`/locations/${loc.id}`, here)} title={loc.name} muted={retired}
                          description={loc.address ?? undefined}
                          facts={[
                            ["Time zone", loc.timezone ?? "—"],
                            ["Residents", loc.resident_count],
                            ["Applications", loc.serving_application_count ?? 0],
                          ]}
                          footer={canEdit ? (
                            <Link href={`/locations/${loc.id}/edit`} className="btn btn-sm btn-light-brand" id={`location-row-edit-${loc.id}`}>
                              <i className="feather-edit-2 me-1"></i>Edit
                            </Link>
                          ) : undefined} />
                      );
                    }
                    return (
                      <RecordCard key={loc.id} id={`location-row-${loc.id}`} icon={icon} href={withBack(`/locations/${loc.id}`, here)} title={loc.name} muted={retired}
                        badges={<PresenceBadge presence={loc.presence} retired={retired} />}
                        description={loc.specs_summary ?? undefined}
                        facts={[
                          ["Inside", loc.parent_location_id !== null && loc.parent_name ? <Link href={withBack(`/locations/${loc.parent_location_id}`, here)}>{loc.parent_name}</Link> : loc.parent_name ?? "—"],
                          ["Owner", loc.owner_member_id !== null && loc.owner_name ? <Who who={{ id: loc.owner_member_id, name: loc.owner_name }} here={here} /> : loc.owner_name ?? "—"],
                          ["Residents", loc.resident_count],
                          ...(!retired && loc.presence !== "online" && loc.last_seen_at !== null
                            ? [["Last seen", loc.last_seen_at] as [string, React.ReactNode]] : []),
                        ]}
                        footer={<>
                          {loc.siting !== null && <span className={`badge bg-soft-${sitingColor} text-${sitingColor}`}>{ucfirst(loc.siting)}</span>}
                          {canEdit && (
                            <Link href={`/locations/${loc.id}/edit`} className="btn btn-sm btn-light-brand" id={`location-row-edit-${loc.id}`}>
                              <i className="feather-edit-2 me-1"></i>Edit
                            </Link>
                          )}
                        </>} />
                    );
                  })}
                </CardSection>
              );
            })}
            <Pagination id="locations-list-pagination" label="Location pages" pathname="/locations" query={filterQuery}
                        page={data.pagination.page} totalPages={data.pagination.total_pages} maxPages={20} />
          </div>
        </div>
      </>
    );
  });
}
