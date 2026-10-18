import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ModelForm from "@/components/settings/ModelForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { modelFormData } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Edit model" };

/** Screen `model-edit`. Data: GET /settings/models/{id}/edit (super-admin only). */
export default async function EditModelPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/settings/models/${id}/edit`, modelFormData, (data) => <ModelForm data={data} back={back} />);
}
