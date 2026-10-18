import type { Metadata } from "next";
import NavItemForm from "@/components/navigation/NavItemForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { navigationItemScreen } from "@/lib/schemas/navigation";

export const metadata: Metadata = { title: "Add a menu entry" };

/** Screen `navigation-item-add`. Data: GET /settings/navigation/?new=1&group={id} (super-admin only). */
export default async function NewNavItemPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const { group, back: rawBack } = await searchParams;
  const query = group && /^\d+$/.test(group) ? `&group=${group}` : "";
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/settings/navigation/?new=1${query}`, navigationItemScreen, (data) => <NavItemForm data={data} back={back} />);
}
