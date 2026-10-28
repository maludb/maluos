import type { Metadata } from "next";
import AgentAvatarBadge from "@/components/agents/AgentAvatarBadge";
import AutoRefresh from "@/components/kit/AutoRefresh";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { ucfirst } from "@/lib/format";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { dashboard, type HomeAgent, type HomeTeamMember } from "@/lib/schemas/home";

export const metadata: Metadata = { title: "Home" };

const STATUS_BADGE: Record<string, string> = { candidate: "warning", active: "success", suspended: "dark", offboarded: "secondary" };
const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * Screen `dashboard` — the shape of the business in counts, then one card per agent. PHP serves
 * it at `/`; here `/` is the Agent View, so the traditional dashboard lives at /dashboard.
 * The agent grid re-reads itself once a minute while the page sits open, as the HTMX one did.
 */
export default async function DashboardPage() {
  const here = await herePath();
  return renderScreen("/", dashboard, (data) => {
    const c = data.counts;
    return (
      <>
        <AutoRefresh seconds={60} />
        <PageHeader title={data.brand} id="home">
          <Link href={withBack("/agents/new", here)} id="home-hire-agent-btn" className="btn btn-primary">
            <i className="feather-plus me-2"></i><span>Hire an agent</span>
          </Link>
        </PageHeader>

        <div className="main-content" data-screen="dashboard">
          <div className="row" id="home-counts-row">
            {/* The decision waiting on the viewer first, then the shape of the business: five tiles,
                two across on a phone, four across from a large screen. Each leads to its list. */}
            <div className="col-6 col-lg-3">
              <div className="card stretch stretch-full" id="home-approvals-card">
                <div className="card-body py-3">
                  <Link href="/approvals" className="stretched-link" id="home-approvals-link" aria-label="Approvals waiting for your decision"></Link>
                  <div className="fs-12 fw-medium text-muted text-uppercase">Approvals</div>
                  <div className={`fs-20 fw-bold ${c.pending_approvals > 0 ? "text-primary" : "text-dark"}`}>{fmt(c.pending_approvals)}</div>
                  <div className="fs-11 text-muted">
                    waiting for you{c.pending_approvals_others > 0 ? ` · ${fmt(c.pending_approvals_others)} with others` : ""}
                  </div>
                </div>
              </div>
            </div>
            <CountTile id="home-count-locations" href="/locations" label="Locations" value={c.locations}
                       detail={`${c.offices} offices · ${c.desks} desks`} aria="Work locations" />
            <CountTile id="home-count-departments" href="/team/departments" label="Departments" value={c.departments}
                       detail={`${fmt(c.department_members)} people and agents`} aria="Departments" />
            <CountTile id="home-count-agents" href="/agents" label="Agents" value={c.active_agents} aria="Agents"
                       detail={c.candidate_agents > 0 || c.suspended_agents > 0
                         ? `employed · ${c.candidate_agents} candidates · ${c.suspended_agents} suspended`
                         : "employed and working"} />
            <CountTile id="home-count-applications" href="/applications" label="Applications" value={c.applications} aria="Applications"
                       detail={`${Math.max(0, c.applications - c.builtin_applications)} registered · ${c.builtin_applications} the platform`} />
          </div>

          <div id="home-agents">
            <div className="d-flex align-items-center justify-content-between mb-3" id="home-agents-heading">
              <h5 className="mb-0">Agents</h5>
              <Link href="/agents" className="fs-11 fw-semibold text-uppercase" id="home-agents-all">
                {data.agent_total > data.agents.length ? `All ${fmt(data.agent_total)}` : "Agent HR"}
              </Link>
            </div>
            <div className="row" id="home-agents-row">
              {data.agents.length === 0 ? (
                <div className="col-12">
                  <div className="card stretch stretch-full" id="home-agents-empty">
                    <div className="card-body text-center text-muted py-5">
                      <i className="feather-cpu fs-1 d-block mb-2 opacity-50"></i>
                      No agents yet. <Link href={withBack("/agents/new", here)}>Hire one</Link>.
                    </div>
                  </div>
                </div>
              ) : (
                data.agents.map((a) => <AgentCard a={a} key={a.id} here={here} />)
              )}
            </div>
          </div>

          <div id="home-team" className="mt-2">
            <div className="d-flex align-items-center justify-content-between mb-3" id="home-team-heading">
              <h5 className="mb-0">Team Members</h5>
              <div className="d-flex gap-3">
                <Link href="/team/invitations" className="fs-11 fw-semibold text-uppercase" id="home-team-invite">Invite</Link>
                <Link href="/team?kind=human" className="fs-11 fw-semibold text-uppercase" id="home-team-all">Human Workforce</Link>
              </div>
            </div>
            <div className="row" id="home-team-row">
              {data.team_members.length === 0 ? (
                <div className="col-12">
                  <div className="card stretch stretch-full" id="home-team-empty">
                    <div className="card-body text-center text-muted py-5">
                      <i className="feather-user fs-1 d-block mb-2 opacity-50"></i>
                      No team members yet. <Link href="/team/invitations">Invite someone</Link>.
                    </div>
                  </div>
                </div>
              ) : (
                data.team_members.map((m) => <TeamMemberCard m={m} key={m.id} here={here} />)
              )}
            </div>
          </div>
        </div>
      </>
    );
  });
}

function CountTile({ id, href, label, value, detail, aria }: { id: string; href: string; label: string; value: number; detail: string; aria: string }) {
  return (
    <div className="col-6 col-lg-3">
      <div className="card stretch stretch-full" id={id}>
        <div className="card-body py-3">
          <Link href={href} className="stretched-link" aria-label={aria}></Link>
          <div className="fs-12 fw-medium text-muted text-uppercase">{label}</div>
          <div className="fs-20 fw-bold text-dark">{fmt(value)}</div>
          <div className="fs-11 text-muted">{detail}</div>
        </div>
      </div>
    </div>
  );
}

/** A link inside a card that is itself one stretched link: lifted above it, so it is what the click hits. */
const OVER_STRETCH = { position: "relative", zIndex: 2 } as const;

function AgentCard({ a, here }: { a: HomeAgent; here: string | null }) {
  const badge = STATUS_BADGE[a.status] ?? "secondary";
  return (
    <div className="col-6 col-sm-4 col-xl-3">
      <div className="card stretch stretch-full" id={`home-agent-card-${a.id}`}>
        <div className="card-body text-center position-relative">
          <Link href={`/agents/${a.id}`} className="stretched-link" aria-label={a.display_name}></Link>
          <div className="mb-2" id={`home-agent-avatar-${a.id}`}>
            <AgentAvatarBadge initials={a.initials} pictureUrl={a.picture_url} sizeClass="avatar-lg" />
          </div>
          <div className="fw-bold text-dark text-truncate" title={a.display_name}>{a.display_name}</div>
          <div className="fs-11 text-muted text-truncate" title={a.job_title ?? ""}>{a.job_title ?? "—"}</div>
          {a.description && <div className="fs-11 text-muted text-truncate-2-line mt-1" id={`home-agent-description-${a.id}`} title={a.description}>{a.description}</div>}
          {a.status !== "active" && <span className={`badge bg-soft-${badge} text-${badge} mt-2`}>{ucfirst(a.status)}</span>}
          {/* Plain blocks, not flex rows: a flex child needs min-width:0 before text-truncate bites. */}
          <div className="fs-11 text-muted text-truncate mt-2" title={a.department_name ?? ""}>
            <i className="feather-users me-1"></i>{a.department_name
              ? (a.department_id !== null ? <Link href={withBack(`/team/departments/${a.department_id}`, here)} className="text-muted" style={OVER_STRETCH}>{a.department_name}</Link> : a.department_name)
              : "No department"}
          </div>
          <div className="fs-11 text-muted text-truncate" title={a.model_key ?? ""}>
            <i className="feather-cpu me-1"></i>{a.model_id !== null && a.model_key ? <Link href={withBack(`/settings/models/${a.model_id}/edit`, here)} className="text-muted" style={OVER_STRETCH}>{a.model_key}</Link> : a.model_key ?? "No model"}
          </div>
          <div className="border-top mt-3 pt-2" id={`home-agent-activity-${a.id}`}>
            <div className={`fs-11 fw-semibold text-${a.activity.tone} text-truncate`} title={a.activity.headline}>
              <i className={`${a.activity.icon} me-1`}></i>{a.run_id !== null
                ? <Link href={withBack(`/ai/runs/${a.run_id}`, here)} className={`text-${a.activity.tone}`} style={OVER_STRETCH}>{a.activity.headline}</Link>
                : a.activity.headline}
            </div>
            <div className="fs-11 text-muted text-truncate" title={a.activity.detail}>{a.activity.detail}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = { super_admin: "Super-admin", dept_admin: "Dept-admin", user: "User" };

function TeamMemberCard({ m, here }: { m: HomeTeamMember; here: string | null }) {
  return (
    <div className="col-6 col-sm-4 col-xl-3">
      <div className="card stretch stretch-full" id={`home-team-card-${m.id}`}>
        <div className="card-body text-center position-relative">
          <Link href={`/team/${m.id}`} className="stretched-link" aria-label={m.display_name}></Link>
          <div className="mb-2">
            <div className="avatar-text avatar-lg rounded-circle mx-auto bg-soft-primary text-primary fw-bold">{m.initials}</div>
          </div>
          <div className="fw-bold text-dark text-truncate" title={m.display_name}>{m.display_name}</div>
          <div className="fs-11 text-muted text-truncate" title={m.job_title ?? ""}>{m.job_title ?? "—"}</div>
          {m.status !== "active" && <span className="badge bg-soft-dark text-dark mt-2">{ucfirst(m.status)}</span>}
          <div className="fs-11 text-muted text-truncate mt-2" title={m.departments.join(", ")}>
            <i className="feather-users me-1"></i>{m.department_links.length > 0
              ? m.department_links.map((d, i) => <span key={d.id}>{i > 0 && ", "}<Link href={withBack(`/team/departments/${d.id}`, here)} className="text-muted" style={OVER_STRETCH}>{d.name}</Link></span>)
              : m.departments.length > 0 ? m.departments.join(", ") : "No department"}
          </div>
          <div className="fs-11 text-muted text-truncate">
            <i className="feather-shield me-1"></i>{ROLE_LABEL[m.business_role] ?? m.business_role}
          </div>
          <div className="border-top mt-3 pt-2 fs-11 text-muted text-truncate" id={`home-team-login-${m.id}`}>
            {m.last_login_display ? `Last signed in ${m.last_login_display}` : "Has not signed in yet"}
          </div>
        </div>
      </div>
    </div>
  );
}
