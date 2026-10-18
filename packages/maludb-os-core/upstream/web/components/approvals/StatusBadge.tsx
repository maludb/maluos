const TONE: Record<string, string> = {
  pending: "warning", approved: "info", executed: "success", rejected: "danger",
  cancelled: "secondary", expired: "secondary", execution_failed: "danger",
};
const LABEL: Record<string, string> = { execution_failed: "Approved — the action failed", executed: "Approved and done" };

/** An approval request's status, in the theme's soft badges. */
export default function ApprovalStatusBadge({ status }: { status: string }) {
  const tone = TONE[status] ?? "secondary";
  const label = LABEL[status] ?? status.charAt(0).toUpperCase() + status.slice(1);
  return <span className={`badge bg-soft-${tone} text-${tone}`}>{label}</span>;
}
