import Link from "@/components/kit/Link";
import type { ApplicationCard as Card } from "@/lib/schemas/applications";
import { withBack } from "@/lib/routes";

const HEALTH: Record<string, [string, string]> = {
  up: ["Up", "success"], degraded: ["Degraded", "warning"], down: ["Down", "danger"], unknown: ["Not checked", "secondary"],
};
const STATE: Record<Card["state"], [string, string]> = {
  active: ["Active", "success"], off: ["Turned off", "warning"], planned: ["Planned", "info"],
  available: ["Available", "secondary"], retired: ["Retired", "dark"],
};

/**
 * One application of the inventory. What runs is a solid card outlined in the brand colour, with a
 * filled icon and a "Running" mark, that opens the application; what could run is a dashed, muted
 * card whose only control is how to turn it on. `showArea` names the business area (the running
 * cards stand outside the area groups).
 */
export default function ApplicationCard({ card, can, here = null, showArea = false }: { card: Card; can: { edit: boolean; arrange_menu: boolean }; here?: string | null; showArea?: boolean }) {
  const active = card.state === "active";
  const [stateLabel, stateColor] = STATE[card.state];
  const href = card.id === null ? null : withBack(`/applications/${card.id}`, here);
  const title = href ? <Link href={href} className="fw-bold text-dark">{card.name}</Link>
                     : <span className="fw-bold text-muted">{card.name}</span>;

  return (
    <div className="col-xl-4 col-md-6" id={`application-card-${card.key}`} data-state={card.state}>
      <div className={`card h-100 mb-0 ${active ? "border border-2 border-primary shadow-sm" : "border-dashed bg-transparent shadow-none"}`}>
        <div className="card-body d-flex flex-column gap-3">
          <div className="d-flex align-items-start gap-3">
            <div className={`avatar-text avatar-md rounded flex-shrink-0 ${active ? "bg-primary text-white" : "bg-gray-200 text-muted"}`}>
              <i className={card.icon}></i>
            </div>
            <div className="flex-grow-1 overflow-hidden">
              <div className="d-flex flex-wrap align-items-center gap-2">
                {title}
                {active
                  ? <span className="badge bg-success"><i className="feather-check-circle me-1"></i>Running</span>
                  : <span className={`badge bg-soft-${stateColor} text-${stateColor}`}>{stateLabel}</span>}
              </div>
              {showArea && card.business_area !== "" && <div className="fs-11 text-uppercase text-muted">{card.business_area}</div>}
              <div className="fs-12 text-muted text-truncate-2-line">{card.description ?? "—"}</div>
            </div>
          </div>

          {active && (
            <div className="d-flex flex-column gap-1 fs-12">
              <div className="d-flex justify-content-between gap-2">
                <span className="text-muted">Expert</span>
                <span className={card.expert_name ? "fw-medium text-dark text-truncate" : "text-muted"}>
                  {card.expert_name
                    ? (card.expert_member_id !== null
                        ? <Link href={withBack(`/agents/${card.expert_member_id}`, here)} className="text-dark"><i className="feather-cpu me-1"></i>{card.expert_name}</Link>
                        : <><i className="feather-cpu me-1"></i>{card.expert_name}</>)
                    : "No expert yet"}
                </span>
              </div>
              <div className="d-flex justify-content-between gap-2">
                <span className="text-muted">Skills</span>
                <span className={card.skill_count > 0 ? "fw-medium text-dark" : "text-muted"}>
                  {card.skill_count > 0 ? card.skill_count : "None yet"}
                </span>
              </div>
              <div className="d-flex justify-content-between gap-2">
                <span className="text-muted">Owner</span>
                <span className="text-truncate">{card.owner_department_name
                  ? (card.owner_department_id !== null ? <Link href={withBack(`/team/departments/${card.owner_department_id}`, here)}>{card.owner_department_name}</Link> : card.owner_department_name)
                  : "—"}</span>
              </div>
            </div>
          )}

          {card.gaps.length > 0 && <div className="fs-11 text-danger">{card.gaps.join("; ")}</div>}

          <div className="d-flex flex-wrap align-items-center gap-2 mt-auto">
            {active && card.health && (() => {
              const [label, color] = HEALTH[card.health.status] ?? [card.health.status, "secondary"];
              return <span className={`badge bg-soft-${color} text-${color}`} title={card.health.detail}>{label}</span>;
            })()}
            {active && card.has_agent_mcp && <span className="badge bg-soft-primary text-primary" title="Agents can reach it over MCP">MCP</span>}
            {card.vendor && <span className="fs-11 text-muted">{card.vendor}</span>}
            {card.state === "available" && !card.is_builtin && can.edit && (
              <Link href={withBack(`/applications/new?catalog=${encodeURIComponent(card.catalog_key ?? "")}`, here)}
                    id={`application-card-${card.key}-register`} className="btn btn-sm btn-light-brand ms-auto">
                <i className="feather-plus me-1"></i>Register
              </Link>
            )}
            {href && card.state !== "off" && (
              <Link href={href} id={`application-card-${card.key}-manage`} className="btn btn-sm btn-light-brand ms-auto">
                <i className="feather-settings me-1"></i>Manage
              </Link>
            )}
            {card.open_url && card.state === "active" && (
              card.open_url.startsWith("/")
                ? <a href={card.open_url} id={`application-card-${card.key}-open`} className="btn btn-sm btn-primary">
                    Open<i className="feather-external-link ms-1"></i>
                  </a>
                : <a href={card.open_url} id={`application-card-${card.key}-open`} className="btn btn-sm btn-primary"
                     target="_blank" rel="noopener noreferrer">
                    Open<i className="feather-external-link ms-1"></i>
                  </a>
            )}
            {card.state === "off" && can.arrange_menu && (
              <Link href="/settings/navigation" id={`application-card-${card.key}-turn-on`}
                    className="btn btn-sm btn-light-brand ms-auto">Turn on in Navigation</Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
