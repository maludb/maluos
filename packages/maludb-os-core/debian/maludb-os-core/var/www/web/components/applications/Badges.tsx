import { ucfirst } from "@/lib/format";

const HEALTH: Record<string, [string, string]> = {
  up: ["Up", "success"], degraded: ["Degraded", "warning"], down: ["Down", "danger"], unknown: ["Unknown", "secondary"],
};
const CRITICALITY: Record<string, string> = { critical: "danger", high: "warning", normal: "info", low: "secondary" };
const STATUS: Record<string, string> = { active: "success", planned: "info", degraded: "warning", retired: "dark" };

/** Health badge with the words under it — app/views/applications/partials/health-badge.php. */
export function HealthBadge({ health }: { health: { status: string; detail: string } }) {
  const [label, color] = HEALTH[health.status] ?? [ucfirst(health.status), "secondary"];
  return (
    <>
      <span className={`badge bg-soft-${color} text-${color}`}>{label}</span>
      <div className="text-muted fs-11">{health.detail}</div>
    </>
  );
}

export function CriticalityBadge({ criticality }: { criticality: string }) {
  const c = CRITICALITY[criticality] ?? "secondary";
  return <span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(criticality)}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const c = STATUS[status] ?? "secondary";
  return <span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(status)}</span>;
}
