import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ApplicationForm from "@/components/applications/ApplicationForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { applicationFormData } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "Edit application" };

/** Screen `application-edit`. Data: GET /applications/{id}/edit (the applications grant). */
export default async function EditApplicationPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/applications/${id}/edit`, applicationFormData, (data) => <ApplicationForm data={data} back={back} />);
}
