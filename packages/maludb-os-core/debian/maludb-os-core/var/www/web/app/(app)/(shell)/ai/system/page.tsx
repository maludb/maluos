import type { Metadata } from "next";
import AiOpsNav, { StateBadge } from "@/components/aiops/AiOpsNav";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { herePath } from "@/lib/here";
import { recordHref, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { systemScreen } from "@/lib/schemas/aiops";

export const metadata: Metadata = { title: "System" };

const SEVERITY = ["noise", "minor", "degraded", "serious", "critical"];
const SEV_TONE = ["secondary", "secondary", "warning", "danger", "danger"];
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");

/**
 * Screen `system` — the Sysadmin's view of this server (db/145): the health probes, the open events from the logs
 * and the kernel's guardrails (redacted samples, classified by JEV), and what it decided. In shadow mode it sends
 * nothing — the decisions say what it would have done. Data: GET /ai/system/ (super-admin, IT admins).
 */
export default async function SystemPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const q = status && ["open", "muted", "all"].includes(status) ? `?status=${status}` : "";
  const here = await herePath();
  return renderScreen(`/ai/system/${q}`, systemScreen, (data) => {
    const problems = data.probes.filter((p) => p.status !== "ok");
    return (
      <>
        <PageHeader title="System" id="system" crumbs={[{ label: "AI Ops", href: "/ai" }, { label: "System" }]} />
        <div className="main-content" data-screen="system">
          <AiOpsNav active="system" />
          {data.agents.map((a) => (
            <div className={`alert ${a.mode === "live" ? "alert-soft-success-message" : "alert-soft-warning-message"} py-2`} key={a.id} id={`system-agent-${a.id}`}>
              <strong>{a.name}</strong> is {a.mode === "live" ? "live — it escalates what it finds." : "in shadow — it records what it would do and sends nothing."}{" "}
              <Link href={`/agents/${a.id}`}>Its page</Link>
            </div>
          ))}
          <div className="row">
            <div className="col-xl-4">
              <div className="card" id="system-health-card">
                <div className="card-header"><h5 className="card-title">Health {problems.length > 0 && <span className="badge bg-soft-danger text-danger ms-1">{problems.length} to look at</span>}</h5></div>
                <div className="card-body p-0">
                  <ul className="list-group list-group-flush">
                    {data.probes.length === 0 && <li className="list-group-item text-muted fs-13">Not probed yet.</li>}
                    {data.probes.map((p) => (
                      <li className="list-group-item" key={p.probe} id={`system-probe-${p.probe}`}>
                        <div className="d-flex align-items-center gap-2"><span className="font-monospace fs-12">{p.probe}</span><span className="ms-auto"><StateBadge state={p.status} /></span></div>
                        {p.status !== "ok" && <div className="fs-12 text-muted mt-1">{p.detail}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
            <div className="col-xl-8">
              <div className="card" id="system-events-card">
                <div className="card-header d-flex flex-wrap gap-2 align-items-center">
                  <h5 className="card-title mb-0">From the logs and guardrails</h5>
                  <span className="ms-auto d-flex gap-2 fs-12">
                    {[["open", "Open"], ["muted", "Muted"], ["all", "All"]].map(([k, l]) => (
                      <Link key={k} href={`/ai/system?status=${k}`} className={data.filters.status === k ? "fw-bold" : ""}>{l}</Link>
                    ))}
                  </span>
                </div>
                <div className="card-body">
                  {data.events.length === 0 && <p className="text-muted mb-0">Nothing here.</p>}
                  {data.events.map((e) => (
                    <div className="card mb-2" key={e.id} id={`system-event-${e.id}`}>
                      <div className="card-body p-3">
                        <div className="d-flex flex-wrap gap-2 align-items-center mb-1">
                          {e.severity !== null && <span className={`badge bg-soft-${SEV_TONE[e.severity]} text-${SEV_TONE[e.severity]}`}>{SEVERITY[e.severity]}</span>}
                          {e.category && <span className="badge bg-soft-info text-info">{e.category}</span>}
                          <span className="fs-12 text-muted">{e.source} · {e.occurrences}× · last {fmt(e.last_seen)}</span>
                          <span className="ms-auto"><StateBadge state={e.status} /></span>
                        </div>
                        <div className="font-monospace fs-12" style={{ overflowWrap: "anywhere" }}>{e.sample}</div>
                        {e.note && <div className="fs-12 text-muted mt-1">{e.status_by_name ? `${e.status_by_name}: ` : ""}{e.note}</div>}
                        {data.can.act && (
                          <div className="d-flex flex-wrap gap-2 mt-2">
                            {(e.status === "open"
                              ? [["acknowledged", "Acknowledge"], ["resolved", "Resolve"], ["muted", "Mute"]]
                              : e.status === "acknowledged" ? [["resolved", "Resolve"], ["muted", "Mute"]] : [["open", "Reopen"]]).map(([s, l]) => (
                              <ActionForm path="/ai/system/event-status.php" key={s}>
                                <input type="hidden" name="event" value={e.id} /><input type="hidden" name="status" value={s} />
                                <SubmitButton className="btn btn-sm btn-light-brand" id={`system-event-${e.id}-${s}`}>{l}</SubmitButton>
                              </ActionForm>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="card" id="system-decisions-card">
                <div className="card-header"><h5 className="card-title">What it decided</h5></div>
                <div className="card-body p-0"><div className="table-responsive"><table className="table table-sm mb-0">
                  <thead className="thead-light"><tr><th>When</th><th>Decision</th><th>About</th><th>Note</th></tr></thead>
                  <tbody>
                    {data.decisions.length === 0 && <tr><td colSpan={4} className="text-center text-muted py-4">Nothing but routine so far.</td></tr>}
                    {data.decisions.map((d) => (
                      <tr key={d.id} id={`system-decision-${d.id}`}>
                        <td className="fs-12 text-muted text-nowrap">{fmt(d.at)}</td>
                        <td><StateBadge state={d.decision} />{d.mode === "shadow" && <span className="badge bg-light text-dark ms-1" title="Shadow: nothing was sent">would</span>}</td>
                        <td className="fs-12" style={{ overflowWrap: "anywhere" }}>{(() => { const h = recordHref(d.subject_kind, d.subject_id); return h ? <Link href={withBack(h, here)}>{d.subject}</Link> : d.subject; })()}</td>
                        <td className="fs-12 text-muted">{d.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div></div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  });
}
