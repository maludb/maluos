import type { Metadata } from "next";
import BusinessForm from "@/components/settings/BusinessForm";
import { renderScreen } from "@/lib/screen";
import { businessSettings } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "Business settings" };

/** Screen `business-settings`. Data: GET /settings/business?saved= (super-admin only). */
export default async function BusinessSettingsPage({ searchParams }: { searchParams: Promise<{ saved?: string }> }) {
  const { saved } = await searchParams;
  return renderScreen(`/settings/business${saved === "1" ? "?saved=1" : ""}`, businessSettings, (data) => <BusinessForm data={data} />);
}
