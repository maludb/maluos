import type { Metadata } from "next";

import ApplicationForm from "@/components/applications/ApplicationForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { applicationFormData } from "@/lib/schemas/applications";

export const metadata: Metadata = { title: "New application" };

/** Screen `application-add`. Data: GET /applications/new (prefills: ?catalog=&category=&location=&department=). */
export default async function NewApplicationPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const p = await searchParams;
  const back = isSafeBack(p.back) ? p.back : null;
  const qs = new URLSearchParams();
  if (p.catalog && /^[a-z][a-z0-9_]*$/.test(p.catalog)) qs.set("catalog", p.catalog);
  if (p.category) qs.set("category", p.category);
  if (p.location && /^\d+$/.test(p.location)) qs.set("location", p.location);
  if (p.department && /^\d+$/.test(p.department)) qs.set("department", p.department);
  const query = qs.toString();
  return renderScreen(`/applications/new${query ? `?${query}` : ""}`, applicationFormData, (data) => <ApplicationForm data={data} back={back} />);
}
