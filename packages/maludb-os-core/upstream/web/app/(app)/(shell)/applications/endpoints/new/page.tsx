import type { Metadata } from "next";
import { notFound } from "next/navigation";
import EndpointForm from "@/components/applications/EndpointForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { endpointFormData } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "Add endpoint" };

/** Screen `application-endpoint-add`. Data: GET /applications/endpoints/new?application={id}. */
export default async function NewEndpointPage({ searchParams }: { searchParams: Promise<{ application?: string; back?: string }> }) {
  const { application, back: rawBack } = await searchParams;
  if (!application || !/^\d+$/.test(application)) notFound();
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/applications/endpoints/new?application=${application}`, endpointFormData, (data) => <EndpointForm data={data} back={back} />);
}
