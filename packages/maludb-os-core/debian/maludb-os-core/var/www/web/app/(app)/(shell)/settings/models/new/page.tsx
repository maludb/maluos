import type { Metadata } from "next";
import ModelForm from "@/components/settings/ModelForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { modelFormData } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Register a model" };

/** Screen `model-add`. Data: GET /settings/models/new (super-admin only). */
export default async function NewModelPage({ searchParams }: { searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen("/settings/models/new", modelFormData, (data) => <ModelForm data={data} back={back} />);
}
