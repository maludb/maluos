import Link from "@/components/kit/Link";

/** "Make an eval case from this" — a link to the case form, prefilled from the trace (the form asks which set). */
export default function PromoteLink({ kind, id }: { kind: "ledger" | "run"; id: number }) {
  return <Link href={`/ai/evals?promote_${kind}=${id}`} className="btn btn-light-brand" id="promote-trace-btn"><i className="feather-check-square me-2"></i><span>Make an eval case</span></Link>;
}
