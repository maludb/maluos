import { ucfirst } from "@/lib/format";

const STATUS: Record<string, string> = { candidate: "warning", active: "success", suspended: "dark", offboarded: "secondary" };
const KIND_TONE: Record<string, string> = { orchestrator: "brand", subagent: "info", voice: "warning" };

export function AgentStatusBadge({ status }: { status: string }) {
  const c = STATUS[status] ?? "secondary";
  return <span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(status)}</span>;
}

/**
 * The kind badge — agent_kind_badge_html(). "roster", not "manages": the count is what an
 * orchestrator may delegate to, which is no longer the same set as whom it manages.
 */
export function AgentKindBadge({
  kind, label, rosterCount,
}: {
  kind: string;
  label: string;
  /** Shown after the label for an orchestrator; omit where the list prints it on its own line. */
  rosterCount?: number;
}) {
  const tone = KIND_TONE[kind] ?? "secondary";
  const count = rosterCount !== undefined && kind === "orchestrator" ? ` · roster ${rosterCount}` : "";
  return <span className={`badge bg-soft-${tone} text-${tone}`}>{label}{count}</span>;
}
