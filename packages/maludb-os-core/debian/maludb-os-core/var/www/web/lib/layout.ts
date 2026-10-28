import type { OrgGraph, OrgNode, ViewMode } from "./types";
import { DEMO_COLOR_GROUP } from "./demo-data";

// Fixed by the build handoff: viewBox="0 0 1000 680", centre at (500, 340), guide-ring
// radii 146 / 156 / 194 / 205 / 254 (outermost dotted). Department nodes sit on the inner
// pair of guide rings (closer to centre); members fan out onto the outer dotted ring.
export const STAGE_W = 1000;
export const STAGE_H = 680;
export const CENTRE_X = 500;
export const CENTRE_Y = 340;
export const GUIDE_RADII = [146, 156, 194, 205, 254] as const;
export const R_DEPARTMENT = 200;
export const R_MEMBER = 254;

export type ColorGroup = "cyan" | "gold";

export interface DeptLayout {
  node: OrgNode;
  deptId: number;
  x: number;
  y: number;
  angleDeg: number;
  color: ColorGroup;
}

export interface MemberLayout {
  node: OrgNode;
  memberId: number;
  x: number;
  y: number;
  angleDeg: number;
  primaryDeptId: number;
  color: ColorGroup;
  /** Set on a crowded ring of the focused view: the stage then draws the name without its sub-line. */
  crowded?: boolean;
}

export interface ExtraAffiliation {
  deptId: number;
  memberId: number;
}

export interface GraphLayout {
  departments: DeptLayout[];
  members: MemberLayout[];
  byId: Map<string, DeptLayout | MemberLayout>;
  extra: ExtraAffiliation[];
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

function deptColor(mode: ViewMode, deptId: number, index: number): ColorGroup {
  if (mode === "demo" && DEMO_COLOR_GROUP[deptId]) return DEMO_COLOR_GROUP[deptId];
  return index % 2 === 0 ? "cyan" : "gold";
}

/**
 * Pure radial layout: departments spaced evenly around the centre, each department's
 * members fanned across a sub-arc of its sector. Stays legible from one department to a
 * dozen, and from an empty department to a crowded one — nothing here assumes the demo's
 * fixed 13-person shape.
 */
/**
 * `weighted` is the focused view's layout (/view/<kind>/<id>): an organisation's departments are
 * peers and get equal sectors, but a record's rings are not — a location has one desk inside it
 * and twenty-five applications — so each ring's sector is sized by what it holds, and a crowded
 * ring is staggered into rows instead of pushed ever further out. Off (the default), this is the
 * home view's layout exactly as it was.
 */
export function computeLayout(graph: OrgGraph, mode: ViewMode, opts: { weighted?: boolean } = {}): GraphLayout {
  if (opts.weighted) return computeWeightedLayout(graph, mode);
  return computeEvenLayout(graph, mode);
}

const ROW_GAP = 44;
const R_MEMBER_WEIGHTED = 246;

function computeWeightedLayout(graph: OrgGraph, mode: ViewMode): GraphLayout {
  const departmentNodes = graph.nodes.filter((n) => n.type === "department");
  const nodeByMemberId = new Map<number, OrgNode>();
  for (const n of graph.nodes) {
    if (n.type === "member" && !n.is_centre && n.member_id != null) nodeByMemberId.set(n.member_id, n);
  }
  const idsByDept = new Map<number, number[]>();
  for (const edge of graph.edges) {
    if (edge.kind !== "has_member") continue;
    const deptId = Number(edge.source.split(":")[1]);
    const memberId = Number(edge.target.split(":")[1]);
    if (!nodeByMemberId.has(memberId)) continue;
    if (!idsByDept.has(deptId)) idsByDept.set(deptId, []);
    idsByDept.get(deptId)!.push(memberId);
  }

  // A ring's share of the circle: what it holds, plus a floor so an empty ring still has room
  // for its own label.
  const weights = departmentNodes.map((n) => 3 + (idsByDept.get(n.department_id!)?.length ?? 0));
  const total = weights.reduce((a, b) => a + b, 0) || 1;

  const departments: DeptLayout[] = [];
  const members: MemberLayout[] = [];
  let cursor = -90 - (360 * weights[0]) / total / 2; // the first ring is centred on the top

  departmentNodes.forEach((node, i) => {
    const sector = (360 * weights[i]) / total;
    const angleDeg = cursor + sector / 2;
    cursor += sector;
    const rad = toRad(angleDeg);
    const dept: DeptLayout = {
      node, deptId: node.department_id!, angleDeg, color: deptColor(mode, node.department_id!, i),
      x: CENTRE_X + R_DEPARTMENT * Math.cos(rad), y: CENTRE_Y + R_DEPARTMENT * Math.sin(rad),
    };
    departments.push(dept);

    const ids = idsByDept.get(dept.deptId) ?? [];
    const count = ids.length;
    // Labels run horizontally, so records crowd long before their circles touch: past five on a
    // ring they alternate between rows, and then carry a name only (no sub-line).
    const rows = count > 14 ? 3 : count > 5 ? 2 : 1;
    // Well inside the sector, so the ends of neighbouring rings never meet. (A ring's own label is
    // drawn on the inward side of its node — NetworkStage — where no record can land.)
    const arcSpan = Math.min(sector * 0.8, 300);
    ids.forEach((memberId, j) => {
      const offset = count === 1 ? 0 : -arcSpan / 2 + (arcSpan * j) / (count - 1);
      const a = angleDeg + offset;
      const r = R_MEMBER_WEIGHTED + (j % rows) * ROW_GAP;
      members.push({
        node: nodeByMemberId.get(memberId)!, memberId, angleDeg: a, primaryDeptId: dept.deptId, color: dept.color,
        x: CENTRE_X + r * Math.cos(toRad(a)), y: CENTRE_Y + r * Math.sin(toRad(a)),
        crowded: rows > 1,
      });
    });
  });

  const byId = new Map<string, DeptLayout | MemberLayout>();
  for (const d of departments) byId.set(d.node.id, d);
  for (const m of members) byId.set(m.node.id, m);
  return { departments, members, byId, extra: [] };
}

function computeEvenLayout(graph: OrgGraph, mode: ViewMode): GraphLayout {
  const departmentNodes = graph.nodes.filter((n) => n.type === "department");
  const memberNodesById = new Map<number, OrgNode>();
  for (const n of graph.nodes) {
    if (n.type === "member" && !n.is_centre && n.member_id != null) {
      memberNodesById.set(n.member_id, n);
    }
  }

  const deptCount = Math.max(departmentNodes.length, 1);
  const angleStep = 360 / deptCount;
  const startAngle = -90; // top, clockwise

  const departments: DeptLayout[] = departmentNodes.map((node, i) => {
    const angleDeg = startAngle + i * angleStep;
    const rad = toRad(angleDeg);
    return {
      node,
      deptId: node.department_id!,
      x: CENTRE_X + R_DEPARTMENT * Math.cos(rad),
      y: CENTRE_Y + R_DEPARTMENT * Math.sin(rad),
      angleDeg,
      color: deptColor(mode, node.department_id!, i),
    };
  });
  const deptByI = new Map(departments.map((d) => [d.deptId, d]));

  // Primary department per member: the first has_member edge that targets them, in the
  // order the API already returns edges (grouped by department id). Any further
  // has_member edge for the same member is an extra affiliation, not a second node.
  const primaryDept = new Map<number, number>();
  const extra: ExtraAffiliation[] = [];
  const membersByDept = new Map<number, number[]>();

  for (const edge of graph.edges) {
    if (edge.kind !== "has_member") continue;
    const deptId = Number(edge.source.split(":")[1]);
    const memberId = Number(edge.target.split(":")[1]);
    if (!memberNodesById.has(memberId)) continue;
    if (!primaryDept.has(memberId)) {
      primaryDept.set(memberId, deptId);
      if (!membersByDept.has(deptId)) membersByDept.set(deptId, []);
      membersByDept.get(deptId)!.push(memberId);
    } else if (primaryDept.get(memberId) !== deptId) {
      extra.push({ deptId, memberId });
    }
  }

  const members: MemberLayout[] = [];
  for (const dept of departments) {
    const ids = membersByDept.get(dept.deptId) ?? [];
    const count = ids.length;
    if (count === 0) continue;
    // Fan across most of the sector, leaving a gap so neighbouring sectors never touch.
    const arcSpan = angleStep * 0.82;
    const memberRadius = R_MEMBER + Math.max(0, count - 6) * 8;
    ids.forEach((memberId, j) => {
      const offset = count === 1 ? 0 : -arcSpan / 2 + (arcSpan * j) / (count - 1);
      const angleDeg = dept.angleDeg + offset;
      const rad = toRad(angleDeg);
      members.push({
        node: memberNodesById.get(memberId)!,
        memberId,
        x: CENTRE_X + memberRadius * Math.cos(rad),
        y: CENTRE_Y + memberRadius * Math.sin(rad),
        angleDeg,
        primaryDeptId: dept.deptId,
        color: dept.color,
      });
    });
  }

  const byId = new Map<string, DeptLayout | MemberLayout>();
  for (const d of departments) byId.set(d.node.id, d);
  for (const m of members) byId.set(m.node.id, m);

  return { departments, members, byId, extra };
}

/** Quadratic-bezier path between two points, bowed away from the centre for legibility. */
export function curvedPath(x1: number, y1: number, x2: number, y2: number, bow = 0.18): string {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const cx = mx - dy * bow;
  const cy = my + dx * bow;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
}
