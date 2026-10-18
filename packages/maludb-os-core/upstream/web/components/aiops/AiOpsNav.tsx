import Link from "@/components/kit/Link";

const TABS: [string, string, string][] = [["overview", "/ai", "Overview"], ["log", "/ai/prompt-log", "Prompt log"], ["spend", "/ai/spend", "Spend"], ["statements", "/ai/spend/statements", "Statements"],
  ["evals", "/ai/evals", "Evals"], ["watch", "/ai/evals/watch", "Watch"], ["traces", "/ai/evals/traces", "Graded traces"],
  ["audit", "/ai/audit", "Audit"], ["system", "/ai/system", "System"], ["skills", "/ai/skills", "Skills"], ["models", "/settings/models", "Models"]];

/** The AI Ops sections as plain links (a section is a URL — no client state). `hide` drops what this viewer would only be refused. */
export default function AiOpsNav({ active, hide = [] }: { active: string; hide?: string[] }) {
  return (
    <ul className="nav nav-tabs mb-3 flex-nowrap overflow-auto" id="aiops-nav" style={{ whiteSpace: "nowrap" }}>
      {TABS.filter(([key]) => !hide.includes(key)).map(([key, href, label]) => (
        <li className="nav-item" key={key}><Link href={href} className={`nav-link ${key === active ? "active" : ""}`} id={`aiops-nav-${key}`}>{label}</Link></li>
      ))}
    </ul>
  );
}

const TONE: Record<string, string> = { ok: "success", succeeded: "success", completed: "success", passed: "success", closed: "success", error: "danger", failed: "danger",
  timeout: "warning", rate_limited: "warning", refused: "warning", cancelled: "secondary", void: "secondary", running: "primary", queued: "info", draft: "secondary",
  active: "success", retired: "secondary", open: "danger", acknowledged: "warning", resolved: "success",
  warning: "warning", muted: "secondary", alert: "danger", escalate: "warning", finding: "info", record: "secondary", mute: "secondary",
  shadow: "secondary", live: "success" };
export function StateBadge({ state, label }: { state: string; label?: string }) {
  const tone = TONE[state] ?? "secondary";
  return <span className={`badge bg-soft-${tone} text-${tone}`}>{label ?? state.replace(/_/g, " ")}</span>;
}

/** The honest banner: authoring is real, running is not. */
export function NoRunner({ note }: { note?: string }) {
  return (
    <div className="alert alert-soft-warning-message" id="evals-no-runner" role="status">
      <strong>No eval runner yet.</strong> {note ?? "Sets, cases and schedules are saved and kept; nothing runs or grades them until the eval runner is built."}
    </div>
  );
}

export const money = (amount: string, currency: string, digits = 4) => `${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits })} ${currency}`;
export const tokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
