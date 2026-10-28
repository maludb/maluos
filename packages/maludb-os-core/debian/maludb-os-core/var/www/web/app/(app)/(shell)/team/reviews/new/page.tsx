import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ReviewForm from "@/components/team/ReviewForm";
import { isSafeBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { reviewFormData } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Write a review" };

/** Screen `review-add`. Data: GET /team/reviews/new?member={id} (mod:hr, or the member's manager). */
export default async function NewReviewPage({ searchParams }: { searchParams: Promise<{ member?: string; back?: string }> }) {
  const { member, back: rawBack } = await searchParams;
  if (!member || !/^\d+$/.test(member)) notFound();
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen(`/team/reviews/new?member=${member}`, reviewFormData, (data) => <ReviewForm data={data} back={back} />);
}
