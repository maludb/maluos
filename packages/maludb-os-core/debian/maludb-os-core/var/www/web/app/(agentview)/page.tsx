import { loadOrgGraph } from "@/lib/org-graph";
import AgentView from "@/components/AgentView";
import SignedOut from "@/components/SignedOut";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const demo = params.demo === "1";

  const result = await loadOrgGraph(demo);

  if (!result.ok) {
    // The landing page (owner, 2026-09-19): a visitor who is not signed in sees the Agent View
    // itself — the fictional sample workspace, which needs no session and makes no call to the
    // platform — with a Log in button. The plain card remains for a deployment whose sign-in
    // address was never configured, where there is nowhere to send them.
    if (result.loginUrl === null) return <SignedOut loginUrl={null} />;
    const sample = await loadOrgGraph(true);
    if (!sample.ok) return <SignedOut loginUrl={result.loginUrl} />;
    return <AgentView graph={sample.graph} mode="demo" loginUrl={result.loginUrl} />;
  }

  return <AgentView graph={result.graph} mode={result.mode} />;
}
