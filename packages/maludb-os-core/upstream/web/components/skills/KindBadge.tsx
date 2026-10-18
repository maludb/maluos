/** A runbook's badge — an application's generic skill (owner, 2026-09-27). A plain skill shows nothing. */
export default function KindBadge({ kind, className = "" }: { kind: string; className?: string }) {
  if (kind !== "runbook") return null;
  return <span className={`badge bg-soft-primary text-primary ${className}`.trim()} title="A runbook: an application's generic skill">Runbook</span>;
}
