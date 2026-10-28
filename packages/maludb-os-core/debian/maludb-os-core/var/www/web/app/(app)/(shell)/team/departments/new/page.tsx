import type { Metadata } from "next";
import DepartmentForm from "@/components/team/DepartmentForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { departmentFormData } from "@/lib/schemas/team";

export const metadata: Metadata = { title: "New department" };

/** Screen `department-add`. Data: GET /team/departments/new (super-admin only — PHP refuses anyone else, in words). */
export default async function NewDepartmentPage({ searchParams }: { searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen("/team/departments/new", departmentFormData, (data) => <DepartmentForm data={data} back={back} />);
}
