import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import AgentView from "@/components/AgentView";
import { isFocusKind, loadFocusGraph } from "@/lib/focus-graph";

export const metadata: Metadata = { title: "MaluDb — Agent View" };

/**
 * The focused Agent View (build spec: docs/build-specs/agent-view-focus-graph.md): a record at
 * the centre, and around it exactly what its own day-to-day screen shows this person. A full
 * page, never a modal; opened by the Agent View button on that screen.
 */
export default async function FocusedAgentView({ params }: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await params;
  if (!isFocusKind(kind) || !/^[1-9]\d{0,17}$/.test(id)) notFound();

  const result = await loadFocusGraph(kind, Number(id));
  if (!result.ok) {
    if (result.reason === "signed_out") redirect(`/login?next=${encodeURIComponent(`/view/${kind}/${id}`)}`);
    notFound();
  }

  return <AgentView graph={result.graph} mode="live" focus={result.focus} />;
}
