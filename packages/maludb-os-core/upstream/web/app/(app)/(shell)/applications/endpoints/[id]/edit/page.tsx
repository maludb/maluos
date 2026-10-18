import type { Metadata } from "next";
import { notFound } from "next/navigation";
import EndpointForm from "@/components/applications/EndpointForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { endpointFormData } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "Edit endpoint" };

/** Screen `application-endpoint-edit`. Data: GET /applications/endpoints/{id}/edit (the applications grant). */
export default async function EditEndpointPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/applications/endpoints/${id}/edit`, endpointFormData, (data) => <EndpointForm data={data} back={back} />);
}
