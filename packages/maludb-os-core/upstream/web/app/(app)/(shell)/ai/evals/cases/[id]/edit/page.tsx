import type { Metadata } from "next";
import { notFound } from "next/navigation";
import EvalCaseForm from "@/components/aiops/EvalCaseForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { evalCaseFormData } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "Edit eval case · AI Ops" };

/** Screen `eval-case-edit`. Data: GET /ai/evals/cases/{id}/edit (mod:evals). */
export default async function EditEvalCasePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/ai/evals/cases/${id}/edit`, evalCaseFormData, (data) => <EvalCaseForm data={data} key={data.case.id} back={back} />);
}
