import type { Metadata } from "next";
import { notFound } from "next/navigation";
import DepartmentForm from "@/components/team/DepartmentForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { departmentFormData } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "Edit department" };

/** Screen `department-edit`. Data: GET /team/departments/{id}/edit (admin of that department). */
export default async function EditDepartmentPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/team/departments/${id}/edit`, departmentFormData, (data) => <DepartmentForm data={data} back={back} />);
}
