import type { OrgGraph } from "./types";

// The handoff's fictional roster, reproduced exactly (docs/agent-build-handoff.md,
// "Sample organization and graph semantics"): Olivia Rhye is CEO/centre, six department
// heads report to her, each with one contributor. 13 people, six teams, three levels.
// Shaped as an OrgGraph so the same layout/rendering code serves demo and live data.

// Self-contained initials avatar (inline SVG data URI) — demo mode makes no network call
// at all, not even to a third-party avatar service, so it renders identically offline.
function initialsAvatar(name: string, fg: string): string {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" rx="48" fill="#0b1420"/><circle cx="48" cy="48" r="47" fill="none" stroke="${fg}" stroke-opacity="0.45" stroke-width="1.5"/><text x="48" y="48" text-anchor="middle" dominant-baseline="central" font-family="'Space Grotesk',sans-serif" font-size="34" fill="${fg}">${initials}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

interface DemoHead {
  deptId: number;
  team: string;
  head: { id: number; name: string; role: string };
  report: { id: number; name: string; role: string };
  colorGroup: "cyan" | "gold";
}

// Strategy, Finance and Operations read cyan; Engineering, Design and Marketing (and the
// CEO) read gold — the handoff's exact palette assignment for this fixed roster.
const HEADS: DemoHead[] = [
  { deptId: 1, team: "Strategy", head: { id: 2, name: "Alex Morgan", role: "Head of Strategy" }, report: { id: 8, name: "Sam Rivera", role: "Strategy Associate" }, colorGroup: "cyan" },
  { deptId: 2, team: "Finance", head: { id: 3, name: "Jordan Lee", role: "Head of Finance" }, report: { id: 9, name: "Taylor Kim", role: "Finance Analyst" }, colorGroup: "cyan" },
  { deptId: 3, team: "Operations", head: { id: 4, name: "Avery Chen", role: "Head of Operations" }, report: { id: 10, name: "Natali Craig", role: "Operations Coordinator" }, colorGroup: "cyan" },
  { deptId: 4, team: "Engineering", head: { id: 5, name: "Phoenix Baker", role: "Head of Engineering" }, report: { id: 11, name: "Drew Cano", role: "Software Engineer" }, colorGroup: "gold" },
  { deptId: 5, team: "Design", head: { id: 6, name: "Lana Steiner", role: "Head of Design" }, report: { id: 12, name: "Orlando Diggs", role: "Product Designer" }, colorGroup: "gold" },
  { deptId: 6, team: "Marketing", head: { id: 7, name: "Demi Wilkinson", role: "Head of Marketing" }, report: { id: 13, name: "Kate Morrison", role: "Marketing Manager" }, colorGroup: "gold" },
];

export function buildDemoGraph(): OrgGraph {
  const nodes: OrgGraph["nodes"] = [];
  const edges: OrgGraph["edges"] = [];

  nodes.push({
    id: "member:1",
    type: "member",
    level: 0,
    member_id: 1,
    name: "Olivia Rhye",
    title: "Chief Executive Officer",
    member_kind: "human",
    avatar_url: initialsAvatar("Olivia Rhye", "#f2ca71"),
    is_centre: true,
  });

  for (const h of HEADS) {
    const groupColor = h.colorGroup === "cyan" ? "#35dff5" : "#f2ca71";
    nodes.push({
      id: `department:${h.deptId}`,
      type: "department",
      level: 1,
      department_id: h.deptId,
      name: h.team,
      parent_department_id: null,
      manager: { id: `member:${h.head.id}`, name: h.head.name },
      member_count: 2,
      agent_count: 0,
    });
    edges.push({ source: "member:1", target: `department:${h.deptId}`, kind: "centre_of" });

    nodes.push({
      id: `member:${h.head.id}`,
      type: "member",
      level: 2,
      member_id: h.head.id,
      name: h.head.name,
      title: h.head.role,
      member_kind: "human",
      avatar_url: initialsAvatar(h.head.name, groupColor),
    });
    edges.push({ source: `department:${h.deptId}`, target: `member:${h.head.id}`, kind: "has_member" });

    nodes.push({
      id: `member:${h.report.id}`,
      type: "member",
      level: 2,
      member_id: h.report.id,
      name: h.report.name,
      title: h.report.role,
      member_kind: "human",
      avatar_url: initialsAvatar(h.report.name, groupColor),
    });
    edges.push({ source: `department:${h.deptId}`, target: `member:${h.report.id}`, kind: "has_member" });
  }

  return {
    generated_at: new Date().toISOString(),
    centre: {
      id: "member:1",
      member_id: 1,
      name: "Olivia Rhye",
      title: "Chief Executive Officer",
      member_kind: "human",
      avatar_url: initialsAvatar("Olivia Rhye", "#f2ca71"),
    },
    summary: { people: 13, agents: 0, teams: 6, levels: 3 },
    teams: HEADS.map((h) => ({
      department_id: h.deptId,
      name: h.team,
      member_count: 2,
      agent_count: 0,
    })),
    nodes,
    edges,
  };
}

// Fixed department -> palette-group assignment for the demo roster only. Live data has no
// such curated grouping, so the layout falls back to an alternating rule there.
export const DEMO_COLOR_GROUP: Record<number, "cyan" | "gold"> = Object.fromEntries(
  HEADS.map((h) => [h.deptId, h.colorGroup])
);
