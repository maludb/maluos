const LOOK: Record<string, string> = {
  proposed: "bg-soft-warning text-warning",
  approved: "bg-soft-success text-success",
  rejected: "bg-soft-danger text-danger",
  withdrawn: "bg-soft-secondary text-secondary",
};

/** A skill proposal's state. "proposed" reads as what it means to the person looking: it waits for them. */
export default function ProposalBadge({ status }: { status: string }) {
  return <span className={`badge ${LOOK[status] ?? "bg-soft-secondary text-secondary"}`}>{status === "proposed" ? "waiting for review" : status}</span>;
}
