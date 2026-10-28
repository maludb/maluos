import type { Metadata } from "next";
import PolicyForm from "@/components/approvals/PolicyForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { approvalPolicyFormData } from "@/lib/schemas/approvals";

export const metadata: Metadata = { title: "New approval policy" };

/** Screen `approval-policy-add`. Data: GET /settings/approval-policies/new (super). */
export default async function NewApprovalPolicyPage({ searchParams }: { searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen("/settings/approval-policies/new", approvalPolicyFormData, (data) => <PolicyForm data={data} back={back} />);
}
