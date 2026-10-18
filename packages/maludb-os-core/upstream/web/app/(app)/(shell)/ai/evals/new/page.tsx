import type { Metadata } from "next";
import EvalSetForm from "@/components/aiops/EvalSetForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { evalSetFormData } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "New eval set · AI Ops" };

/** Screen `eval-set-add`. Data: GET /ai/evals/new?agent=&role= (mod:evals, people only). */
export default async function NewEvalSetPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["agent", "role"]) if (sp[key]) query.set(key, sp[key] as string);
  const back = isSafeBack(sp.back) ? sp.back : null;
  return renderScreen(`/ai/evals/new${query.size > 0 ? `?${query}` : ""}`, evalSetFormData, (data) => <EvalSetForm data={data} back={back} />);
}
