/**
 * Click-around (docs/build-specs/click-around.md): the one place that knows where a kind of record
 * lives (R2), how a member's name becomes the right link (R1), and how a link carries the page it
 * left so the target can offer a way back (R4). Nothing here touches next/headers — client
 * components import it too; the request's own path comes from lib/here.ts.
 */

export type MemberRef = { id: number | string | null | undefined; kind?: string | null };

/** An agent's page or a person's — `kind` is members.member_kind ('agent' | 'human'). */
export function memberHref(m: MemberRef): string | null {
  if (m.id === null || m.id === undefined || m.id === "") return null;
  return m.kind === "agent" ? `/agents/${m.id}` : `/team/${m.id}`;
}

/** Every entity_type log_activity() is called with that has a page, and where that page is. */
const RECORD_PATHS: Record<string, (id: string) => string> = {
  agent: (id) => `/agents/${id}`,
  member: (id) => `/team/${id}`,
  department: (id) => `/team/departments/${id}`,
  location: (id) => `/locations/${id}`,
  application: (id) => `/applications/${id}`,
  application_endpoint: (id) => `/applications/endpoints/${id}/edit`,
  approval_request: (id) => `/approvals/${id}`,
  approval_policy: (id) => `/settings/approval-policies/${id}/edit`,
  model: (id) => `/settings/models/${id}/edit`,
  system_prompt: (id) => `/settings/prompts/${id}`,
  eval_set: (id) => `/ai/evals/${id}`,
  eval_run: (id) => `/ai/evals/runs/${id}`,
  eval_alert: (id) => `/ai/evals/alerts/${id}`,
  eval_case: (id) => `/ai/evals/cases/${id}/edit`,
  agent_run: (id) => `/ai/runs/${id}`,
  prompt_ledger: (id) => `/ai/prompt-log/${id}`,
  ledger: (id) => `/ai/prompt-log/${id}`,
  nav_item: (id) => `/settings/navigation/items/${id}`,
  skill_proposal: (id) => `/skills/proposals/${id}`,
  skill: () => "/skills",
  skill_assignment: () => "/skills",
  business_settings: () => "/settings/business",
  business_hours: () => "/settings/business",
};

/** Where a record of this kind lives, or null when it has no page (then show it as text). */
export function recordHref(kind: string | null | undefined, id: number | string | null | undefined): string | null {
  if (!kind || id === null || id === undefined || id === "") return null;
  const path = RECORD_PATHS[kind];
  return path ? path(String(id)) : null;
}

/** A `back` is honoured only as a relative path of ours: one leading slash, nothing that could leave the site. */
export function isSafeBack(path: string | null | undefined): path is string {
  return typeof path === "string" && path.length > 0 && path.length <= 1500 && /^\/(?!\/)[^\s\\]*$/.test(path);
}

/**
 * The link off a list, a table, a card or another record's page carries the page it leaves
 * (`here` = the request's own path and query, lib/here.ts), so the target shows "Back to …" and
 * returns to exactly that URL — period, filters, tab and page kept. A chain holds because `here`
 * includes its own `back`.
 */
export function withBack(href: string, here: string | null | undefined): string {
  if (!isSafeBack(here)) return href;
  return `${href}${href.includes("?") ? "&" : "?"}back=${encodeURIComponent(here)}`;
}

/**
 * Where a form lands after PHP says where the record now lives (R5): on the record, and with the
 * trail the form page arrived with. If the form's `back` IS that record's page (an edit opened from
 * it, tab and trail included), go there; otherwise (a create opened from a list) the new record
 * carries the list as its back.
 */
export function afterSave(location: string, back: string | null | undefined): string {
  if (!isSafeBack(back)) return location;
  const path = (s: string) => (s.split("?")[0] ?? "").replace(/\/+$/, "");
  return path(location) === path(back) ? back : withBack(location, back);
}

/** The list pages, as a back link names them. Longest matching prefix wins. */
const LIST_LABELS: Record<string, string> = {
  "/dashboard": "Dashboard", "/activity": "Activity",
  "/ai/spend": "AI spend", "/ai/spend/statements": "Statements", "/ai/prompt-log": "Prompt log",
  "/ai/evals": "Evals", "/ai/evals/watch": "Watch", "/ai/evals/traces": "Graded traces", "/ai/audit": "Audit", "/ai/system": "System",
  "/agents": "Agents", "/agents/escalations": "Escalations", "/agents/versions": "Config history",
  "/team": "People", "/team/departments": "Departments", "/team/invitations": "Invitations",
  "/locations": "Work locations", "/applications": "Applications", "/approvals": "Approvals",
  "/skills": "Skills", "/memory": "Memory",
  "/settings": "Settings", "/settings/models": "Models", "/settings/prompts": "Prompt library",
  "/settings/approval-policies": "Approval policies", "/settings/navigation": "Navigation", "/settings/business": "Business settings",
};

/** The record pages, as a back link names them ("Back to the agent"). */
const DETAIL_LABELS: [RegExp, string][] = [
  [/^\/agents\/\d+/, "the agent"], [/^\/ai\/runs\/\d+/, "the run"], [/^\/ai\/prompt-log\/\d+/, "the call"],
  [/^\/ai\/evals\/runs\/\d+/, "the eval run"], [/^\/ai\/evals\/alerts\/\d+/, "the alert"], [/^\/ai\/evals\/\d+/, "the eval set"],
  [/^\/team\/departments\/\d+/, "the department"], [/^\/team\/\d+/, "the person"], [/^\/locations\/\d+/, "the location"],
  [/^\/applications\/\d+/, "the application"], [/^\/approvals\/\d+/, "the approval"], [/^\/skills\/proposals\/\d+/, "the proposal"],
  [/^\/settings\/prompts\/\d+/, "the prompt"], [/^\/memory\/core\/\d+/, "core memory"],
];

/** What a back link to this path says after "Back to", or null when the path has no name. */
export function backLabel(path: string): string | null {
  const p = (path.split("?")[0] ?? "").replace(/\/+$/, "") || "/";
  for (const [re, label] of DETAIL_LABELS) if (re.test(p)) return label;
  let best: string | null = null;
  for (const key of Object.keys(LIST_LABELS)) {
    if ((p === key || p.startsWith(`${key}/`)) && (best === null || key.length > best.length)) best = key;
  }
  return best === null ? null : LIST_LABELS[best];
}
