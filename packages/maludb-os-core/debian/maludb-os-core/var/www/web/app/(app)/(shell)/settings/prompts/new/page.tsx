import type { Metadata } from "next";
import PromptForm from "@/components/settings/PromptForm";
import { renderScreen } from "@/lib/screen";
import { isSafeBack } from "@/lib/routes";
import { promptFormData } from "@/lib/schemas/settings";

export const metadata: Metadata = { title: "New prompt" };

/** Screen `system-prompt-add`. Data: GET /settings/prompts/new (mod:hr) — the read is the gate; the form starts blank. */
export default async function NewPromptPage({ searchParams }: { searchParams: Promise<{ back?: string }> }) {
  const { back: rawBack } = await searchParams;
  const back = isSafeBack(rawBack) ? rawBack : null;
  return renderScreen("/settings/prompts/new", promptFormData, () => <PromptForm back={back} />);
}
