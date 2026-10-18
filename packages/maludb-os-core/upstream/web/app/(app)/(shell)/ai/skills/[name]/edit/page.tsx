import type { Metadata } from "next";
import { notFound } from "next/navigation";
import SkillForm from "@/components/skills/SkillForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { skillLibraryView } from "@/lib/schemas/skillLibrary";

export const metadata: Metadata = { title: "New version of a skill" };

/** Screen `skills-library-form` (a new version), prefilled from the version agents get. Data: GET /ai/skills/view.php?name= (super). */
export default async function EditSkillPage({ params, searchParams }: { params: Promise<{ name: string }>; searchParams: Promise<{ back?: string }> }) {
  const { name } = await params;
  const skillName = decodeURIComponent(name);
  if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(skillName)) notFound();
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;

  return renderScreen(`/ai/skills/view.php?name=${encodeURIComponent(skillName)}`, skillLibraryView, (data) => (
    <SkillForm initial={{
      name: data.skill.name, kind: data.skill.kind, description: data.skill.chosen.description, body: data.skill.body,
      files: data.skill.files.map((f) => ({ path: f.path, content: f.content ?? "" })),
    }} back={back} />
  ));
}
