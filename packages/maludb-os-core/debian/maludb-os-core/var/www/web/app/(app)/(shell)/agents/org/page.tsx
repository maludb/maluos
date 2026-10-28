import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { renderScreen } from "@/lib/screen";
import { agentOrg, type AgentOrg } from "@/lib/schemas/assistants";

export const metadata: Metadata = { title: "Organisation" };

type Node = AgentOrg["nodes"][number];

/** One node and everything under it, as nested lists (the tree is at most five deep — db/154). */
function Branch({ node, byParent }: { node: Node; byParent: Map<number, Node[]> }) {
  const children = byParent.get(node.id) ?? [];
  return (
    <li className="mb-2" id={`org-node-${node.id}`}>
      <div className="d-flex flex-wrap align-items-center gap-2">
        <i className={node.principal_id !== null ? "feather-user-check text-primary" : node.kind === "orchestrator" ? "feather-git-merge text-muted" : "feather-cpu text-muted"}></i>
        <Link href={`/agents/${node.id}`} className="fw-semibold">{node.name}</Link>
        {node.principal_id !== null && <span className="badge bg-soft-primary text-primary">assistant of {node.principal_name}</span>}
        {node.principal_id === null && node.kind === "orchestrator" && <span className="badge bg-soft-secondary text-secondary">lead</span>}
        {node.departments && <span className="fs-12 text-muted">{node.departments}</span>}
      </div>
      {children.length > 0 && (
        <ul className="list-unstyled ms-4 mt-2 border-start ps-3">
          {children.map((c) => <Branch key={c.id} node={c} byParent={byParent} />)}
        </ul>
      )}
    </li>
  );
}

/**
 * Screen `agent-org` — the orchestrator tree (db/154): each personal assistant with the person it serves,
 * the department leads under it, their specialists; and the leads the OS proposes for departments that
 * have none (db/157), hired only when a super-admin confirms. Data: GET /agents/org.
 */
export default async function OrgPage() {
  return renderScreen("/agents/org", agentOrg, (data) => {
    const ids = new Set(data.nodes.map((n) => n.id));
    const byParent = new Map<number, Node[]>();
    for (const n of data.nodes) {
      if (n.parent_id !== null && ids.has(n.parent_id)) byParent.set(n.parent_id, [...(byParent.get(n.parent_id) ?? []), n]);
    }
    const roots = data.nodes.filter((n) => n.parent_id === null || !ids.has(n.parent_id));
    return (
      <>
        <PageHeader title="Organisation" id="agent-org" crumbs={[{ label: "Agent Workforce", href: "/agents" }, { label: "Organisation" }]}>
          {data.can.decide && (
            <ActionForm path="/agents/leads/propose.php">
              <SubmitButton className="btn btn-light-brand" id="agent-org-propose"><i className="feather-plus-circle me-2"></i>Propose leads</SubmitButton>
            </ActionForm>
          )}
        </PageHeader>
        <div className="main-content" data-screen="agent-org">
          <p className="text-muted fs-13">
            A person&rsquo;s assistant takes their directions and hands each to the lead of the department that owns it; a lead hands it to a
            specialist. Results and questions come back up the same lines, and only an assistant talks to its person.
          </p>
          {data.proposals.length > 0 && (
            <div className="row g-3 mb-3" id="agent-org-proposals">
              {data.proposals.map((p) => (
                <div className="col-xl-4 col-md-6" key={p.id} id={`agent-org-proposal-${p.id}`}>
                  <div className="card h-100 mb-0 border-dashed">
                    <div className="card-body d-flex flex-column gap-2">
                      <div className="d-flex align-items-center gap-2">
                        <span className="fw-bold">{p.name}</span><span className="badge bg-soft-warning text-warning">proposed</span>
                      </div>
                      <div className="fs-12 text-muted">
                        Leads <Link href={`/team/departments/${p.department_id}`}>{p.department_name}</Link>
                        {p.parent_name && <> · under {p.parent_name}</>}{p.model_name && <> · {p.model_name}</>}
                      </div>
                      <div className="fs-12">Roster: {p.roster.length === 0 ? <span className="text-muted">nobody yet — add specialists after hiring</span> : p.roster.map((r) => r.name).join(", ")}</div>
                      <details><summary className="fs-12">Job description</summary>
                        <div className="fs-12 text-muted mt-1" style={{ whiteSpace: "pre-wrap" }}>{p.job_description}</div></details>
                      {data.can.decide && (
                        <div className="d-flex gap-2 mt-auto">
                          <ActionForm path="/agents/leads/confirm.php" confirm={`Hire ${p.name}? It joins ${p.department_name} as its lead${p.parent_name ? ` under ${p.parent_name}` : ""}.`}>
                            <input type="hidden" name="proposal" value={p.id} />
                            <SubmitButton className="btn btn-sm btn-primary" id={`agent-org-confirm-${p.id}`}>Confirm and hire</SubmitButton>
                          </ActionForm>
                          <ActionForm path="/agents/leads/decline.php">
                            <input type="hidden" name="proposal" value={p.id} />
                            <SubmitButton className="btn btn-sm btn-light-brand" id={`agent-org-decline-${p.id}`}>Decline</SubmitButton>
                          </ActionForm>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="card" id="agent-org-tree">
            <div className="card-body">
              {roots.length === 0 ? <p className="text-muted mb-0">No orchestrators yet.</p> : (
                <ul className="list-unstyled mb-0">{roots.map((n) => <Branch key={n.id} node={n} byParent={byParent} />)}</ul>
              )}
            </div>
          </div>
        </div>
      </>
    );
  });
}
