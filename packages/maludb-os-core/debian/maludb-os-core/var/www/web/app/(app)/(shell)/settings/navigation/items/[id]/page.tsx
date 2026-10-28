import type { Metadata } from "next";
import { notFound } from "next/navigation";
import NavItemForm from "@/components/navigation/NavItemForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { navigationItemScreen } from "@/lib/schemas/navigation";

export const metadata: Metadata = { title: "Edit menu entry" };

/** Screen `navigation-item`. Data: GET /settings/navigation/?item={id} (super-admin only). */
export default async function EditNavItemPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ back?: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/settings/navigation/?item=${id}`, navigationItemScreen, (data) => <NavItemForm data={data} key={data.item?.id} back={back} />);
}
