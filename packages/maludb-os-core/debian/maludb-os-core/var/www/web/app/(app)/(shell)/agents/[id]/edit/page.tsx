import type { Metadata } from "next";
import { notFound } from "next/navigation";
import AgentForm from "@/components/agents/AgentForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentFormData } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Edit agent" };

/** Screen `agent-edit`. Data: GET /agents/{id}/edit (mod:hr). */
export default async function EditAgentPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/agents/${id}/edit`, agentFormData, (data) => <AgentForm data={data} back={back} />);
}
