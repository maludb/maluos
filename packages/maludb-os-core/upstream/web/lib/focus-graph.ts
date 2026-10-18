import { cookies } from "next/headers";
import { ApiError, apiGet } from "./api";
import type { FocusContext, FocusGraph, FocusKind, OrgGraph, OrgNode } from "./types";

export const FOCUS_KINDS: readonly FocusKind[] = ["department", "agent", "project", "location", "organization"];

export function isFocusKind(kind: string): kind is FocusKind {
  return (FOCUS_KINDS as readonly string[]).includes(kind);
}

export type FocusLoad =
  | { ok: true; graph: OrgGraph; focus: FocusContext }
  | { ok: false; reason: "signed_out" | "not_found" };

/**
 * Loads a focused graph for the current request — server-side only, forwarding the visitor's
 * session cookie through lib/api.ts like every other screen (the browser never talks to PHP).
 * An open is a screen view, so it is marked as one unless the quiet cookie says this render is
 * the re-read after a write — the same rule renderScreen() applies.
 */
export async function loadFocusGraph(kind: FocusKind, id: number): Promise<FocusLoad> {
  let payload: FocusGraph;
  try {
    const quiet = (await cookies()).has("bos_quiet");
    payload = await apiGet<FocusGraph>(`/api/v1/graph?focus=${kind}:${id}`, { screenView: !quiet });
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (err.status === 401) return { ok: false, reason: "signed_out" };
    // 404 is "does not exist, or you may not see it" — indistinguishable on purpose. A 400 can
    // only come from a URL this page built wrongly; it is not the visitor's to fix either.
    if (err.status === 404 || err.status === 400) return { ok: false, reason: "not_found" };
    throw err;
  }
  return { ok: true, ...adaptFocusGraph(payload) };
}

/**
 * The focused payload, in the shape the Agent View already draws. "A group node lays out where
 * a department does" (build spec): each ring becomes a department-typed node and each record on
 * it a member-typed node, so lib/layout.ts and the stage draw it with the code that draws the
 * organisation — the home view is not touched. The layout keys nodes by number, so ids here are
 * positions (ring 1…n, record 1…n); what a node really is — its own id, type, screen and, for a
 * person or an agent, its real member id — rides along in `focus`.
 */
export function adaptFocusGraph(payload: FocusGraph): { graph: OrgGraph; focus: FocusContext } {
  const drawnId = new Map<string, string>();
  const nodes: OrgNode[] = [];
  let ring = 0;
  let record = 0;

  const shownInRing = new Map<string, number>();
  for (const e of payload.edges) {
    if (e.kind === "has_member") shownInRing.set(e.source, (shownInRing.get(e.source) ?? 0) + 1);
  }

  for (const n of payload.nodes) {
    const realMemberId = n.type === "member" ? Number(n.id.split(":")[1]) : undefined;
    const ref = { id: n.id, type: n.type, href: n.href ?? null, member_id: realMemberId };

    if (n.level === 1) {
      ring += 1;
      const id = `department:${ring}`;
      drawnId.set(n.id, id);
      nodes.push({
        id, type: "department", level: 1, department_id: ring, name: n.name, manager: null,
        member_count: n.member_count ?? 0, agent_count: 0,
        focus: { ...ref, shown: shownInRing.get(n.id) ?? 0, truncated: n.truncated ?? false },
      });
      continue;
    }

    // The centre keeps position 0; records count up from 1.
    const position = n.level === 0 ? 0 : (record += 1);
    const id = `member:${position}`;
    drawnId.set(n.id, id);
    nodes.push({
      id, type: "member", level: n.level, member_id: position, name: n.name, title: n.title ?? null,
      member_kind: n.member_kind, avatar_url: n.avatar_url ?? undefined,
      ...(n.is_centre ? { is_centre: true } : {}),
      focus: ref,
    });
  }

  const centre = nodes.find((n) => n.is_centre) ?? null;
  const graph: OrgGraph = {
    generated_at: payload.generated_at,
    centre: centre
      ? {
          id: centre.id, member_id: 0, name: centre.name, title: centre.title ?? null,
          member_kind: centre.member_kind ?? "human", avatar_url: centre.avatar_url ?? "",
        }
      : null,
    summary: { people: 0, agents: 0, teams: payload.summary.groups, levels: 3 },
    teams: nodes
      .filter((n) => n.type === "department")
      .map((n) => ({ department_id: n.department_id!, name: n.name, member_count: n.member_count ?? 0, agent_count: 0 })),
    nodes,
    edges: payload.edges
      .filter((e) => drawnId.has(e.source) && drawnId.has(e.target))
      .map((e) => ({ source: drawnId.get(e.source)!, target: drawnId.get(e.target)!, kind: e.kind })),
  };

  return {
    graph,
    focus: {
      kind: payload.focus.kind,
      name: payload.centre.name,
      title: payload.centre.title,
      href: payload.centre.href,
      groups: payload.summary.groups,
      records: payload.nodes.filter((n) => n.level === 2).length,
    },
  };
}
