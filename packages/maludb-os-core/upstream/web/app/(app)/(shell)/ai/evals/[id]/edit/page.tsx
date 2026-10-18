import type { Metadata } from "next";
import { notFound } from "next/navigation";
import EvalSetForm from "@/components/aiops/EvalSetForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { evalSetFormData } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Edit eval set · AI Ops" };

/** The eval set's edit form (action `eval_set_save`). Data: GET /ai/evals/{id}/edit (mod:evals). */
export default async function EditEvalSetPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/ai/evals/${id}/edit`, evalSetFormData, (data) => <EvalSetForm data={data} key={data.set.id} back={back} />);
}
