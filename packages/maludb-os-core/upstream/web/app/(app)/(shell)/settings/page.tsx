import type { Metadata } from "next";
import MySettings from "@/components/settings/MySettings";
import { getSession } from "@/lib/api";
import { renderScreen } from "@/lib/screen";
import { mySettings } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Settings" };

const SECTIONS = ["profile", "notifications", "security", "tokens", "calendar"];

/** Screen `settings` — the member's own settings; a section is a URL (?section=). Data: GET /settings/ (login). */
export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ section?: string }> }) {
  const { section } = await searchParams;
  const query = section && SECTIONS.includes(section) ? `?section=${section}` : "";
  const member = (await getSession()).member;
  const timeZone = member?.timezone ?? "UTC";
  return renderScreen(`/settings/${query}`, mySettings,
    (data) => <MySettings data={data} timeZone={timeZone} isSuperAdmin={member?.is_super_admin ?? false} key={data.section} />);
}
