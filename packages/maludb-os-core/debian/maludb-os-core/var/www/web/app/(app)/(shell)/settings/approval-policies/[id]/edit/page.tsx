import type { Metadata } from "next";
import { notFound } from "next/navigation";
import PolicyForm from "@/components/approvals/PolicyForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { approvalPolicyFormData } from "@/lib/schemas/approvals";

export const metadata: Metadata = { title: "Edit approval policy" };

/** Screen `approval-policy-edit`. Data: GET /settings/approval-policies/{id}/edit (super). */
export default async function EditApprovalPolicyPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/settings/approval-policies/${id}/edit`, approvalPolicyFormData, (data) => <PolicyForm data={data} back={back} />);
}
