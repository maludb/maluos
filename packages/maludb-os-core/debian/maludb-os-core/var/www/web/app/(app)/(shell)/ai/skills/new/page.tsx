import type { Metadata } from "next";
import SkillForm from "@/components/skills/SkillForm";
import { isSafeBack } from "@/lib/routes";

export const metadata: Metadata = { title: "New skill" };

/** Screen `skills-library-form` (new). Saving is the super-admin's (skill_save); PHP refuses anyone else. */
export default async function NewSkillPage({ searchParams }: { searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return <SkillForm initial={null} back={back} />;
}
