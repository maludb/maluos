import type { Metadata } from "next";
import AgentForm from "@/components/agents/AgentForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentFormData } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Hire an agent" };

/** Screen `agent-hire`. Data: GET /agents/new (mod:hr; prefills: ?department_id=&job_title=). */
export default async function HireAgentPage({
  searchParams,
}: {
  searchParams: Promise<{ department_id?: string; job_title?: string; back?: string }>;
}) {
  const { department_id, job_title, back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  const qs = new URLSearchParams();
  if (department_id && /^\d+$/.test(department_id)) qs.set("department_id", department_id);
  if (job_title) qs.set("job_title", job_title);
  const query = qs.toString();
  return renderScreen(`/agents/new${query ? `?${query}` : ""}`, agentFormData, (data) => <AgentForm data={data} back={back} />);
}
