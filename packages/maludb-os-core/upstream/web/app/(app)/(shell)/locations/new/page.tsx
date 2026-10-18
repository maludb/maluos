import type { Metadata } from "next";
import LocationForm from "@/components/estate/LocationForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { locationFormData } from "@/lib/schemas/estate";

export const metadata: Metadata = { title: "New location" };

/** Screen `location-add`. Data: GET /locations/new (prefills: ?kind=&parent= — "add a desk to this office"). */
export default async function NewLocationPage({ searchParams }: { searchParams: Promise<{ kind?: string; parent?: string; back?: string }> }) {
  const { kind, parent, back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  const qs = new URLSearchParams();
  if (kind && ["building", "office", "desk", "site"].includes(kind)) qs.set("kind", kind);
  if (parent && /^\d+$/.test(parent)) qs.set("parent", parent);
  const query = qs.toString();
  return renderScreen(`/locations/new${query ? `?${query}` : ""}`, locationFormData, (data) => <LocationForm data={data} back={back} />);
}
