import type { Metadata } from "next";
import { notFound } from "next/navigation";
import EvalCaseForm from "@/components/aiops/EvalCaseForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { evalCaseFormData } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "New eval case · AI Ops" };

/** Screen `eval-case-add`. Data: GET /ai/evals/cases/new?eval_set={id}&from_ledger=&from_run= (mod:evals). */
export default async function NewEvalCasePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | undefined>> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const sp = await searchParams;
  const query = new URLSearchParams({ eval_set: id });
  for (const key of ["from_ledger", "from_run"]) if (/^\d+$/.test(sp[key] ?? "")) query.set(key, sp[key] as string);
  const back = isSafeBack(sp.back) ? sp.back : null;
  return renderScreen(`/ai/evals/cases/new?${query}`, evalCaseFormData, (data) => <EvalCaseForm data={data} back={back} />);
}
