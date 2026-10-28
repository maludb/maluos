// Shapes mirror /api/v1/org-graph, /api/v1/me and /api/v1/members exactly — see
// app/features/orgchart/queries.php on the platform for the source of truth. Do not
// invent fields here; if the API adds one, read it there first.

export type MemberKind = "human" | "agent";

// Three values, never a pair — orchestrator | subagent | voice.
export type AgentKind = "orchestrator" | "subagent" | "voice";

export interface NodeAgentInfo {
  status: string;
  agent_kind: AgentKind;
  role_key: string | null;
  manager_member_id: number | null;
  is_office_manager: boolean | null;
}

export interface DepartmentManagerRef {
  id: string;
  name: string;
}

export interface OrgNode {
  id: string; // "member:7" | "department:3"
  type: "member" | "department";
  level: 0 | 1 | 2;
  member_id?: number;
  department_id?: number;
  name: string;
  title?: string | null;
  member_kind?: MemberKind;
  avatar_url?: string;
  is_centre?: boolean;
  parent_department_id?: number | null;
  manager?: DepartmentManagerRef | null;
  member_count?: number;
  agent_count?: number;
  agent?: NodeAgentInfo;
  // Set only by the focused view's adapter (lib/focus-graph.ts) — what this node really is.
  // The home view's nodes never carry it.
  focus?: FocusRef;
}

// ---- The focused Agent View: /api/v1/graph?focus=<kind>:<id> --------------------------------
// Shapes mirror app/features/orgchart/present.php exactly.

export type FocusKind = "department" | "agent" | "project" | "location" | "organization";

export type FocusNodeType =
  | "member" | "department" | "group" | "project" | "task" | "milestone" | "location"
  | "application" | "organization" | "contact" | "deal" | "tool" | "duty";

export interface FocusNode {
  id: string; // "project:6" | "group:team" | "member:6"
  type: FocusNodeType;
  level: 0 | 1 | 2;
  name: string;
  title?: string | null;
  href?: string | null;
  is_centre?: boolean;
  member_kind?: MemberKind;
  avatar_url?: string | null;
  member_count?: number; // a group's true size
  truncated?: boolean; // a group that shows fewer than that
}

export interface FocusGraph {
  generated_at: string;
  focus: { kind: FocusKind; id: number };
  centre: { id: string; name: string; title: string | null; href: string | null };
  summary: { groups: number; nodes: number };
  nodes: FocusNode[];
  edges: OrgEdge[];
}

/** What an adapted node really is: its own id, type and day-to-day screen. */
export interface FocusRef {
  id: string;
  type: FocusNodeType;
  href: string | null;
  member_id?: number; // the real member id, when the node is a person or an agent
  shown?: number; // a group: how many of member_count are drawn
  truncated?: boolean;
}

/** What the Agent View component needs to know when it is drawing a record, not the org. */
export interface FocusContext {
  kind: FocusKind;
  name: string;
  title: string | null;
  href: string | null;
  groups: number;
  records: number;
}

export type EdgeKind = "centre_of" | "has_member";

export interface OrgEdge {
  source: string;
  target: string;
  kind: EdgeKind;
}

export interface OrgTeam {
  department_id: number;
  name: string;
  member_count: number;
  agent_count: number;
}

export interface OrgCentre {
  id: string;
  member_id: number;
  name: string;
  title: string | null;
  member_kind: MemberKind;
  avatar_url: string;
}

export interface OrgSummary {
  people: number;
  agents: number;
  teams: number;
  levels: number;
}

export interface OrgGraph {
  generated_at: string;
  centre: OrgCentre | null;
  summary: OrgSummary;
  teams: OrgTeam[];
  nodes: OrgNode[];
  edges: OrgEdge[];
}

export interface MemberDepartmentRef {
  department_id: number;
  name: string;
  is_primary: boolean;
}

export interface MemberDetailAgent {
  status: string;
  agent_kind: AgentKind;
  role_key: string | null;
  model_key: string | null;
  harness: string | null;
  is_office_manager: boolean | null;
  hired_at: string | null;
  suspended_at: string | null;
  offboarded_at: string | null;
  roster?: { id: string; name: string; status: string; role_key: string | null }[];
}

export interface MemberDetail {
  id: string;
  member_id: number;
  name: string;
  title: string | null;
  member_kind: MemberKind;
  avatar_url: string;
  departments: MemberDepartmentRef[];
  manager: DepartmentManagerRef | null;
  agent?: MemberDetailAgent;
}

// What the server-side loader hands the client component — one shape whether the data
// came from the real API or the fictional demo roster.
export type ViewMode = "live" | "demo";

export interface OrgGraphResult {
  ok: true;
  mode: ViewMode;
  graph: OrgGraph;
}

export interface SignedOutResult {
  ok: false;
  reason: "signed_out";
  loginUrl: string | null;
}

export type OrgGraphLoad = OrgGraphResult | SignedOutResult;
