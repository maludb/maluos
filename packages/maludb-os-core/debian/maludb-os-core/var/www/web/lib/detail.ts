import type { OrgGraph, OrgNode } from "./types";

export interface RelatedRef {
  id: string;
  name: string;
  title?: string | null;
}

function primaryDeptMap(graph: OrgGraph): Map<number, number> {
  const primary = new Map<number, number>();
  for (const edge of graph.edges) {
    if (edge.kind !== "has_member") continue;
    const deptId = Number(edge.source.split(":")[1]);
    const memberId = Number(edge.target.split(":")[1]);
    if (!primary.has(memberId)) primary.set(memberId, deptId);
  }
  return primary;
}

/**
 * The same manager rule the platform applies (app/features/orgchart/queries.php,
 * member_node_detail): an agent's manager is its own manager_member_id; a human's manager
 * is their primary department's manager. Computed here from the graph payload alone, so
 * the profile panel has an answer before any on-demand detail fetch resolves.
 */
export function computeManagerRef(graph: OrgGraph, node: OrgNode): RelatedRef | null {
  if (node.type === "department") {
    if (!node.manager) return null;
    return { id: node.manager.id, name: node.manager.name };
  }
  if (node.is_centre) return null;

  if (node.member_kind === "agent" && node.agent?.manager_member_id != null) {
    const managerId = `member:${node.agent.manager_member_id}`;
    const managerNode = graph.nodes.find((n) => n.id === managerId);
    if (managerNode) return { id: managerId, name: managerNode.name };
    if (graph.centre?.id === managerId) return { id: managerId, name: graph.centre.name };
  }

  const primary = primaryDeptMap(graph);
  const deptId = node.member_id != null ? primary.get(node.member_id) : undefined;
  if (deptId == null) return null;
  const dept = graph.nodes.find((n) => n.type === "department" && n.department_id === deptId);
  if (!dept?.manager || dept.manager.id === node.id) return null;
  return { id: dept.manager.id, name: dept.manager.name };
}

/** Everyone whose computed manager is this node (members), plus — for a department — its
 * member roster. Inverse of computeManagerRef, so the two never disagree. */
export function computeReports(graph: OrgGraph, node: OrgNode): RelatedRef[] {
  if (node.type === "department") {
    const primary = primaryDeptMap(graph);
    return graph.nodes
      .filter((n) => n.type === "member" && !n.is_centre && n.member_id != null && primary.get(n.member_id) === node.department_id)
      .map((n) => ({ id: n.id, name: n.name, title: n.title }));
  }

  const reports: RelatedRef[] = [];
  for (const n of graph.nodes) {
    if (n.id === node.id) continue;
    const mgr = computeManagerRef(graph, n);
    if (mgr?.id === node.id) reports.push({ id: n.id, name: n.name, title: n.type === "department" ? null : n.title });
  }
  return reports;
}

export function nodeById(graph: OrgGraph, id: string): OrgNode | undefined {
  return graph.nodes.find((n) => n.id === id);
}
