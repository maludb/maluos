import type { Metadata } from "next";
import { notFound } from "next/navigation";
import LocationForm from "@/components/estate/LocationForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { locationFormData } from "@/lib/schemas/estate";

export const metadata: Metadata = { title: "Edit location" };

/** Screen `location-edit`. Data: GET /locations/{id}/edit (the locations grant — PHP names it when refusing). */
export default async function EditLocationPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/locations/${id}/edit`, locationFormData, (data) => <LocationForm data={data} back={back} />);
}
