import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { getSession } from "@/lib/api";
import { formatTs } from "@/lib/format";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentVersions } from "@/lib/schemas/agents";

export const metadata: Metadata = { title: "Config history" };

/** Screen `agent-versions`. Data: GET /agents/versions?agent={id} (insider). */
export default async function AgentVersionsPage({ searchParams }: { searchParams: Promise<{ agent?: string }> }) {
  const { agent: rawId } = await searchParams;
  if (!rawId || !/^\d+$/.test(rawId)) notFound();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  const here = await herePath();
  return renderScreen(`/agents/versions?agent=${rawId}`, agentVersions, (data) => {
    const { agent: a, versions, can } = data;
    const id = a.id as number;
    return (
      <>
        <PageHeader title={`Config history · ${a.name}`} id="agent-versions"
                    crumbs={[{ label: "HR", href: "/agents" }, { label: a.name, href: `/agents/${id}` }, { label: "Versions" }]} back={{ href: `/agents/${id}`, label: "the agent" }} />

        <div className="main-content" data-screen="agent-versions" data-entity="member" data-record-id={id}>
          <div className="card stretch stretch-full" id="agent-versions-card">
            <div className="card-header"><h5 className="card-title">Every configuration version — immutable, never edited</h5></div>
            <div className="card-body p-0">
              <div className="table-responsive">
                <table className="table table-hover mb-0" id="agent-versions-table">
                  <thead className="thead-light">
                    <tr>
                      <th>Version</th><th>Created</th><th>Prompt</th><th>Parameters</th><th>Change note</th>
                      <th>Activated</th><th>Eval gate</th>
                      {can.edit && <th className="text-end">Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {versions.length === 0 ? (
                      <tr><td colSpan={can.edit ? 8 : 7} className="text-center text-muted py-5">No versions yet.</td></tr>
                    ) : versions.map((v) => (
                      <tr id={`agent-version-row-${v.id}`} key={v.id}>
                        <td className="fw-medium">v{v.version_no}</td>
                        <td className="text-muted fs-12">{formatTs(v.created_at, timeZone)}</td>
                        <td className="fs-12">
                          {v.system_prompt
                            ? <><Link href={withBack(`/settings/prompts/${v.system_prompt.id}`, here)}>{v.system_prompt.name}</Link> <span className="text-muted">v{v.system_prompt.version}</span></>
                            : <span className="text-muted">Written inline</span>}
                          {v.model_id !== null && <div className="text-muted">{v.model_name ? <Link href={withBack(`/settings/models/${v.model_id}/edit`, here)}>{v.model_name}</Link> : <Link href={withBack(`/settings/models/${v.model_id}/edit`, here)}>Model #{v.model_id}</Link>}</div>}
                        </td>
                        <td className="fs-12 text-muted">{v.parameters_summary || "—"}</td>
                        <td className="fs-12">{v.change_note ?? "—"}</td>
                        <td>
                          {v.activated_at
                            ? <span className="badge bg-soft-success text-success">Activated {formatTs(v.activated_at, timeZone)}</span>
                            : <span className="badge bg-soft-warning text-warning">Not activated</span>}
                        </td>
                        <td className="fs-12">
                          {!v.activated_at ? "—" : v.gated
                            ? (v.gating_eval_run_id !== null
                                ? <Link href={withBack(`/ai/evals/runs/${v.gating_eval_run_id}`, here)} className="badge bg-soft-success text-success">Passed a gating eval run</Link>
                                : <span className="badge bg-soft-success text-success">Passed a gating eval run</span>)
                            : <span className="badge bg-soft-secondary text-secondary">No gate — none existed</span>}
                        </td>
                        {can.edit && (
                          <td className="text-end">
                            {!v.activated_at && (
                              <ActionForm path="/agents/config-activate.php" confirm={`Activate version ${v.version_no}?`}>
                                <input type="hidden" name="agent" value={id} />
                                <input type="hidden" name="version" value={v.id} />
                                <SubmitButton className="btn btn-sm btn-light-brand" id={`agent-version-activate-${v.id}`}>Activate</SubmitButton>
                              </ActionForm>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
