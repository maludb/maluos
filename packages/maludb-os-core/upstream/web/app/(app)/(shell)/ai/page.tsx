import type { Metadata } from "next";
import AiOpsNav, { StateBadge, money, tokens } from "@/components/aiops/AiOpsNav";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import { herePath } from "@/lib/here";
import { withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { aiOpsIndexScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "AI Ops" };

/**
 * Screen `ai-ops` — the AI Ops front page (owner, 2026-09-27: a real index, not a redirect): one card a
 * section with its headline numbers and the way in. Data: GET /ai/ (any insider; the sections a person may
 * not open are left out, as their screens would refuse them).
 */
export default async function AiOpsIndexPage() {
  const here = await herePath();
  return renderScreen("/ai/", aiOpsIndexScreen, ({ spend, log, statements, evals, ops, models }) => {
    const Card = ({ id, href, title, children }: { id: string; href: string; title: string; children: React.ReactNode }) => (
      <div className="col-md-6 col-xl-4" id={id}>
        <div className="card h-100 mb-0">
          <div className="card-header"><h5 className="card-title"><Link href={withBack(href, here)} className="text-dark">{title}</Link></h5>
            <Link href={withBack(href, here)} className="btn btn-sm btn-light-brand" id={`${id}-open`}>Open<i className="feather-arrow-right ms-1"></i></Link></div>
          <div className="card-body d-flex flex-column gap-2">{children}</div>
        </div>
      </div>
    );
    const Big = ({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) => (
      <div><div className="text-muted fs-12">{label}</div><div className={`fs-4 fw-bold${tone ? ` text-${tone}` : ""}`}>{value}</div></div>
    );
    const Line = ({ children }: { children: React.ReactNode }) => <div className="fs-12 text-muted">{children}</div>;
    return (
      <>
        <PageHeader title="AI Ops" crumbs={[{ label: "AI Ops" }]} id="ai-ops" />
        <div className="main-content" data-screen="ai-ops">
          <AiOpsNav active="overview" />
          <div className="row g-3">
            <Card id="ai-ops-spend" href="/ai/spend" title="Spend">
              <Big label="This month" value={money(spend.cost, spend.currency)} />
              <Line>{spend.calls.toLocaleString()} calls · {tokens(spend.tokens)} tokens{spend.failed > 0 && <> · <span className="text-danger">{spend.failed} failed</span></>}</Line>
              {spend.providers.map((p) => <Line key={p.name}>{p.name}: {money(p.cost, spend.currency)}</Line>)}
            </Card>
            <Card id="ai-ops-log" href="/ai/prompt-log?period=today" title="Prompt log">
              <Big label="Calls today" value={log.calls_today.toLocaleString()} tone={log.failed_today > 0 ? "danger" : undefined} />
              <Line>{money(log.cost_today, spend.currency)} today{log.failed_today > 0 ? ` · ${log.failed_today} failed` : ""}</Line>
            </Card>
            <Card id="ai-ops-statements" href={`/ai/spend/statements?period=${statements.period}`} title="Statements">
              <Big label={statements.period} value={<StateBadge state={statements.status} />} />
              <Line>{statements.status === "open" ? "Open until a super-admin closes it; late calls are flagged into it." : `Closed${statements.closed_at ? ` ${statements.closed_at.slice(0, 10)}` : ""}.`}</Line>
            </Card>
            {evals && (<>
              <Card id="ai-ops-evals" href="/ai/evals" title="Evals">
                <Big label="Active sets" value={<>{evals.sets_active} <span className="fs-12 fw-normal text-muted">of {evals.sets_total}</span></>} />
                {evals.last_run
                  ? <Line>Last run: <Link href={withBack(`/ai/evals/runs/${evals.last_run.id}`, here)}>#{evals.last_run.id}</Link> {evals.last_run.set_name} <StateBadge state={evals.last_run.status} />{evals.last_run.score !== null && ` · ${evals.last_run.score}`}</Line>
                  : <Line>No eval run yet — a set with no runs has not been evaluated.</Line>}
              </Card>
              <Card id="ai-ops-watch" href="/ai/evals/watch" title="Watch">
                <Big label="Open alerts" value={evals.alerts_open} tone={evals.alerts_critical > 0 ? "danger" : evals.alerts_open > 0 ? "warning" : undefined} />
                <Line>{evals.alerts_critical > 0 ? `${evals.alerts_critical} critical · ` : ""}{evals.schedules_active} active schedule{evals.schedules_active === 1 ? "" : "s"}</Line>
              </Card>
              <Card id="ai-ops-traces" href="/ai/evals/traces" title="Graded traces">
                <Big label="Real runs graded" value={evals.traces_graded} />
                <Line>{evals.traces_failed > 0 ? <span className="text-danger">{evals.traces_failed} failed</span> : "None failed"}</Line>
              </Card>
            </>)}
            {ops && (<>
              <Card id="ai-ops-audit" href="/ai/audit" title="Audit">
                <Big label="Auditor decisions, 7 days" value={ops.audit_decisions_7d} />
                <Line>What the Auditor found on agent work; findings advise, nothing blocks.</Line>
              </Card>
              <Card id="ai-ops-system" href="/ai/system" title="System">
                <Big label="Health probes" value={<>{ops.probes_total - ops.probes_failed - ops.probes_warning} <span className="fs-12 fw-normal text-muted">of {ops.probes_total} ok</span></>}
                     tone={ops.probes_failed > 0 ? "danger" : ops.probes_warning > 0 ? "warning" : undefined} />
                <Line>{ops.probes_failed > 0 ? `${ops.probes_failed} failed · ` : ""}{ops.probes_warning > 0 ? `${ops.probes_warning} warning · ` : ""}{ops.events_open} open event{ops.events_open === 1 ? "" : "s"} · {ops.system_decisions_7d} Sysadmin decisions in 7 days</Line>
              </Card>
            </>)}
            <Card id="ai-ops-models" href="/settings/models" title="Models">
              <Big label="Active" value={<>{models.active} <span className="fs-12 fw-normal text-muted">of {models.total}</span></>} />
              <Line>The registry every hire and every call is priced from.</Line>
            </Card>
          </div>
        </div>
      </>
    );
  });
}
