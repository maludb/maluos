import type { Metadata } from "next";
import { notFound } from "next/navigation";
import AgentAvatarBadge from "@/components/agents/AgentAvatarBadge";
import AgentSkillAssign from "@/components/agents/AgentSkillAssign";
import ChatTab from "@/components/agents/ChatTab";
import InboxTab from "@/components/assistants/InboxTab";
import KindBadge from "@/components/skills/KindBadge";
import { AgentKindBadge, AgentStatusBadge } from "@/components/agents/Badges";
import ActionForm from "@/components/kit/ActionForm";
import AgentViewButton from "@/components/kit/AgentViewButton";
import SubmitButton from "@/components/kit/SubmitButton";
import Link from "@/components/kit/Link";
import Who from "@/components/kit/Who";
import PageHeader from "@/components/kit/PageHeader";
import { getSession } from "@/lib/api";
import { formatTs, ucfirst } from "@/lib/format";
import { herePath } from "@/lib/here";
import { isSafeBack, withBack } from "@/lib/routes";
import { renderScreen } from "@/lib/screen";
import { agentView, type AgentView } from "@/lib/schemas/agents";
import type { AgentOps } from "@/lib/schemas/aiops";
import { StateBadge, money, tokens } from "@/components/aiops/AiOpsNav";

export const metadata: Metadata = { title: "Agent · HR" };

const TAB_KEYS = ["chat", "job", "tools", "skills", "duties", "roster", "inbox", "performance", "trail"] as const;

/**
 * Screen `agent-view` — tabs are the card header and each tab is a URL (?tab=), as in PHP.
 * Data: GET /agents/{id}?tab= (insider; below app_can_see_agent the views hide the job
 * description, grants and budget, so a plain insider simply sees less).
 */
export default async function AgentPage({
  params, searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; back?: string; c?: string; archived?: string }>;
}) {
  const { id: rawId } = await params;
  if (!/^\d+$/.test(rawId)) notFound();
  const { tab: rawTab, back: rawBack, c: rawConversation, archived: rawArchived } = await searchParams;
  // The Chat tab (agent-chat.md) also carries which conversation is open (?c=<id> or ?c=new) and whether the archive is shown.
  const chatParams = rawTab === "chat"
    ? [rawConversation && /^(\d+|new)$/.test(rawConversation) ? `&c=${rawConversation}` : "", rawArchived === "1" ? "&archived=1" : ""].join("")
    : "";
  const tabQuery = rawTab && (TAB_KEYS as readonly string[]).includes(rawTab) ? `?tab=${rawTab}${chatParams}` : "";
  // The `back` this page was opened with rides along on its tabs; `here` (this URL, back included) is
  // what every link off the page carries, so a run or an approval opened here comes back to this tab.
  const back = isSafeBack(rawBack) ? rawBack : null;
  const here = await herePath();
  const timeZone = (await getSession()).member?.timezone ?? "UTC";

  return renderScreen(`/agents/${rawId}${tabQuery}`, agentView, (data) => {
    const { agent: a, can, pending_version: pending } = data;
    const id = a.id as number;
    // A voice agent stands outside delegation entirely (db/091), so it has no roster to show.
    const tabs: [AgentView["tab"], string][] = [
      ["chat", "Chat"], ["job", "Job"], ["tools", "Tools"], ["skills", "Skills"], ["duties", "Duties"],
      ...(a.kind === "voice" ? [] : [["roster", a.kind === "orchestrator" ? "Roster" : "Orchestrators"] as [AgentView["tab"], string]]),
      ["inbox", "Inbox"], ["performance", "Performance"], ["trail", "Trail"],
    ];

    return (
      <>
        <PageHeader title={a.name} icon="feather-cpu" id="agent-view" crumbs={[{ label: "HR", href: "/agents" }, { label: a.name }]} back={{ href: "/agents", label: "Agents" }}>
          <AgentViewButton kind="agent" id={id} screen="agent-view" />
          <Link href={`/agents/versions?agent=${id}`} className="btn btn-light-brand" id="agent-view-versions-btn">
            <i className="feather-clock me-2"></i><span>Config history</span>
          </Link>
          {can.edit && (
            <Link href={`/memory/core/${id}`} className="btn btn-light-brand" id="agent-view-core-memory-btn">
              <i className="feather-database me-2"></i><span>Core memory</span>
            </Link>
          )}
          {can.edit && pending && a.status !== "offboarded" && (
            <ActionForm path="/agents/config-activate.php" confirm={`Activate version ${pending.version_no}?`}>
              <input type="hidden" name="agent" value={id} />
              <input type="hidden" name="version" value={pending.id} />
              <SubmitButton className="btn btn-primary" id="agent-view-activate-btn">
                <i className="feather-check me-2"></i><span>Activate version {pending.version_no}</span>
              </SubmitButton>
            </ActionForm>
          )}
          {can.edit && a.status !== "offboarded" && (
            <Link href={withBack(`/agents/${id}/edit`, here)} className={`btn ${pending ? "btn-light-brand" : "btn-primary"}`} id="agent-view-edit-btn">
              <i className="feather-edit-2 me-2"></i><span>Edit</span>
            </Link>
          )}
          {can.edit && a.status === "suspended" && (
            <ActionForm path="/agents/reinstate.php">
              <input type="hidden" name="agent" value={id} />
              <SubmitButton className="btn btn-light-brand" id="agent-view-reinstate-btn">Reinstate</SubmitButton>
            </ActionForm>
          )}
        </PageHeader>

        <div className="main-content" data-screen="agent-view" data-entity="member" data-record-id={id}>
          {data.system_one && (
            <div className={`alert ${data.system_one.mode === "live" ? "alert-soft-success-message" : "alert-soft-warning-message"} d-flex flex-wrap align-items-center gap-2`} id="agent-system-one-mode">
              <span><strong>{data.system_one.mode === "live" ? "Live" : "Shadow"}.</strong>{" "}
                {data.system_one.mode === "live"
                  ? "This system_one agent acts on what it finds: it starts evaluations, opens alerts and escalates."
                  : "This system_one agent records what it would do and sends nothing. Watch its decisions, then switch it live."}</span>
              {data.system_one.can_switch && (
                <ActionForm path="/agents/system-one-mode.php" className="ms-auto"
                            confirm={data.system_one.mode === "live" ? "Put it back in shadow? It stops sending anything." : "Switch it live? It will escalate and alert on what it finds."}>
                  <input type="hidden" name="agent" value={id} />
                  <input type="hidden" name="mode" value={data.system_one.mode === "live" ? "shadow" : "live"} />
                  <SubmitButton className="btn btn-sm btn-light-brand" id="agent-system-one-switch">{data.system_one.mode === "live" ? "Back to shadow" : "Switch live"}</SubmitButton>
                </ActionForm>
              )}
            </div>
          )}
          {data.paused.length > 0 && <PausedBlock data={data} timeZone={timeZone} here={here} />}
          <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
            <AgentStatusBadge status={a.status} />
            <span className="text-muted fs-12">{a.job_title ?? ""}</span>
            {a.manager_name && <span className="text-muted fs-12">reports to <Who who={{ id: a.manager_member_id, name: a.manager_name, kind: a.manager_kind }} here={here} /></span>}
          </div>

          <div className="row">
            <div className="col-xxl-8">
              <div className="card border-top-0" id="agent-view-detail-card">
                <div className="card-header p-0">
                  <ul className="nav nav-tabs flex-wrap w-100 text-center" id="agent-view-tabs" role="tablist">
                    {tabs.map(([key, label]) => (
                      <li className="nav-item flex-fill border-top" role="presentation" key={key}>
                        <Link href={withBack(`/agents/${id}?tab=${key}`, back)} id={`agent-view-tab-${key}`}
                              className={`nav-link${data.tab === key ? " active" : ""}`} scroll={false}>{label}</Link>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="tab-content">
                  <div className="tab-pane fade show active p-4" id={`agent-view-pane-${data.tab}`} role="tabpanel">
                    {data.tab === "chat" && data.chat !== null && <ChatTab agentId={id} agentName={a.name} chat={data.chat} timeZone={timeZone} here={here} back={back} />}
                    {data.tab === "job" && <JobTab data={data} timeZone={timeZone} here={here} />}
                    {data.tab === "tools" && <ToolsTab data={data} here={here} />}
                    {data.tab === "skills" && <SkillsTab data={data} here={here} />}
                    {data.tab === "duties" && <DutiesTab data={data} timeZone={timeZone} here={here} />}
                    {data.tab === "roster" && <RosterTab data={data} timeZone={timeZone} here={here} />}
                    {data.tab === "inbox" && <InboxTab inbox={data.inbox} timeZone={timeZone} />}
                    {data.tab === "performance" && <PerformanceTab data={data} timeZone={timeZone} here={here} />}
                    {data.tab === "trail" && <TrailTab data={data} timeZone={timeZone} />}
                  </div>
                </div>
              </div>
            </div>

            <div className="col-xxl-4">
              {/* Up to three stacked cards in one column: plain .card, never stretch-full. */}
              <div className="card" id="agent-view-identity-card">
                <div className="card-header"><h5 className="card-title">Identity</h5></div>
                <div className="card-body">
                  <div className="d-flex align-items-center gap-2 mb-3">
                    <AgentAvatarBadge initials={a.avatar.initials} pictureUrl={a.avatar.picture_url} sizeClass="avatar-md" />
                    <div>
                      <div className="fw-semibold">{a.name}</div>
                      <span id="agent-view-kind-badge"><AgentKindBadge kind={a.kind} label={a.kind_label} rosterCount={a.subagent_count} /></span>{" "}
                      {a.role_key && <span className="badge bg-soft-secondary text-secondary">{a.role_key}</span>}
                      {a.kind === "voice" && (
                        <div className="fs-12 text-muted mt-1" id="agent-view-phone">
                          <i className="feather-phone me-1"></i>
                          {a.phone_number ? `${a.phone_number} — inbound calls run on this agent's prompt` : "No number connected yet"}
                        </div>
                      )}
                    </div>
                  </div>
                  {a.description && <p className="fs-13 text-muted mb-3">{a.description}</p>}
                  <dl className="row mb-0">
                    <dt className="col-5 text-muted fs-12">Email</dt>
                    <dd className="col-7">{a.email ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Departments</dt>
                    <dd className="col-7">{a.department_links.length > 0
                      ? a.department_links.map((d, i) => <span key={d.id}>{i > 0 && ", "}<Link href={withBack(`/team/departments/${d.id}`, here)}>{d.name}</Link></span>)
                      : a.departments.join(", ") || "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Manager</dt>
                    <dd className="col-7">{a.manager_member_id !== null && a.manager_name ? <Who who={{ id: a.manager_member_id, name: a.manager_name, kind: a.manager_kind }} here={here} /> : a.manager_name ?? "—"}</dd>
                    <dt className="col-5 text-muted fs-12">Hired</dt>
                    <dd className="col-7">{a.hired_at ? formatTs(a.hired_at, timeZone) : "—"}</dd>
                  </dl>
                </div>
              </div>

              {can.edit && (
                <div className="card" id="agent-view-manager-card">
                  <div className="card-header"><h5 className="card-title">Manager</h5></div>
                  <div className="card-body">
                    <ActionForm path="/agents/manager.php" className="d-flex gap-2" id="agent-view-manager-form">
                      <input type="hidden" name="agent" value={id} />
                      <select name="manager" className="form-select form-select-sm" id="agent-form-field-manager_member_id"
                              defaultValue={a.manager_member_id ?? ""} key={a.manager_member_id ?? 0}>
                        {data.options.managers.map((m) => (
                          <option value={m.id} key={m.id}>{m.name}{m.kind === "agent" ? " (orchestrator)" : ""}</option>
                        ))}
                      </select>
                      <SubmitButton className="btn btn-sm btn-light-brand" id="agent-view-manager-btn">Set</SubmitButton>
                    </ActionForm>
                    <div className="form-text">A person, or an orchestrator agent. A subagent or a voice agent
                      manages nobody, and so is refused by name.</div>
                  </div>
                </div>
              )}

              {a.status !== "offboarded" && can.edit && (
                <div className="card" id="agent-view-danger-card">
                  <div className="card-header"><h5 className="card-title text-danger">Danger zone</h5></div>
                  <div className="card-body d-flex flex-column gap-3">
                    {a.status !== "suspended" && (
                      <ActionForm path="/agents/suspend.php" confirm="Suspend this agent?" id="agent-view-suspend-form">
                        <input type="hidden" name="agent" value={id} />
                        <input type="text" name="reason" className="form-control form-control-sm mb-2"
                               id="agent-form-field-suspend_reason" placeholder="Reason (optional)" />
                        <SubmitButton className="btn btn-sm btn-light-brand w-100" id="agent-view-suspend-btn">Suspend</SubmitButton>
                      </ActionForm>
                    )}
                    {can.offboard && (
                      <ActionForm path="/agents/offboard.php" id="agent-view-offboard-form"
                                  confirm="Offboard this agent? Tokens and grants are revoked; the trail is kept.">
                        <input type="hidden" name="agent" value={id} />
                        <input type="text" name="reason" className="form-control form-control-sm mb-2" required
                               id="agent-form-field-offboard_reason" placeholder="Reason (required)" />
                        <SubmitButton className="btn btn-sm btn-outline-danger w-100" id="agent-view-offboard-btn">Offboard</SubmitButton>
                      </ActionForm>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </>
    );
  });
}

function FactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="row g-0 mb-3">
      <div className="col-sm-5 text-muted">{label}</div>
      <div className="col-sm-7 fw-semibold">{children}</div>
    </div>
  );
}

function JobTab({ data, timeZone, here }: { data: AgentView; timeZone: string; here: string | null }) {
  const { agent: a, version: v, can } = data;
  return (
    <>
      {v === null ? (
        <p className="text-muted">No configuration version exists yet.</p>
      ) : (
        <>
          <h6 className="fw-bold mb-2">Job description (version {v.version_no})</h6>
          <p className="mb-4" style={{ whiteSpace: "pre-wrap" }}>{v.job_description ?? ""}</p>

          <FactRow label="System prompt:">
            {v.system_prompt ? (
              <><Link href={withBack(`/settings/prompts/${v.system_prompt.id}`, here)}>{v.system_prompt.name}</Link>{" "}
                <span className="text-muted fs-12">v{v.system_prompt.version}</span></>
            ) : <span className="text-muted">Written inline for this agent</span>}
          </FactRow>
          {v.parameters_summary !== "" && <FactRow label="Model parameters:">{v.parameters_summary}</FactRow>}
          {(v.run_limits.max_turns !== "" || v.run_limits.run_timeout_seconds !== "") && (
            <FactRow label="Run limits:">
              {[v.run_limits.max_turns !== "" ? `${v.run_limits.max_turns} turns` : null,
                v.run_limits.run_timeout_seconds !== "" ? `${v.run_limits.run_timeout_seconds} seconds` : null]
                .filter(Boolean).join(" · ")}
            </FactRow>
          )}
          <FactRow label="Model:">{v.model_id !== null ? <Link href={withBack(`/settings/models/${v.model_id}/edit`, here)}>{a.model_key ?? v.model_name ?? "—"}</Link> : a.model_key ?? "—"} <span className="text-muted fs-12">({a.harness ?? "—"})</span></FactRow>
          <FactRow label="Monthly budget:">{v.monthly_budget_display ?? "No limit set"}</FactRow>
          <FactRow label="Activation:">
            {v.activated_at ? (
              <>
                <span className="badge bg-soft-success text-success">Active since {formatTs(v.activated_at, timeZone)}</span>
                <div className="fs-12 text-muted mt-1">
                  {v.gated ? "Passed its gating eval run before going live."
                    : "Went live without an eval gate — no eval set exists for this agent yet."}
                </div>
              </>
            ) : <span className="badge bg-soft-warning text-warning">Not activated</span>}
          </FactRow>
          {v.change_note && <FactRow label="Change note:">{v.change_note}</FactRow>}

          {can.edit && !v.activated_at && (
            <ActionForm path="/agents/config-activate.php" confirm="Activate this version?" id="agent-job-activate-form">
              <input type="hidden" name="agent" value={a.id ?? ""} />
              <input type="hidden" name="version" value={v.id} />
              <SubmitButton className="btn btn-sm btn-primary" id="agent-job-activate-btn">
                <i className="feather-check me-2"></i>Activate this version
              </SubmitButton>
            </ActionForm>
          )}
        </>
      )}

      <div className="row g-0 mb-3 mt-4">
        <div className="col-sm-5 text-muted">Home location:</div>
        <div className="col-sm-7 fw-semibold">
          {a.home_location_id !== null
            ? <Link href={withBack(`/locations/${a.home_location_id}`, here)}>{a.home_location_name ?? "View location"}</Link>
            : <span className="text-muted">No home location set.</span>}
        </div>
      </div>
    </>
  );
}

function ToolsTab({ data, here }: { data: AgentView; here: string | null }) {
  const id = data.agent.id as number;
  const canEdit = data.can.edit;
  return (
    <>
      <div className="table-responsive mb-3">
        <table className="table table-hover mb-0" id="agent-tools-table">
          <thead className="thead-light">
            <tr><th>Application</th><th>Endpoint</th><th>Tool</th><th>Constraints</th>{canEdit && <th className="text-end">Actions</th>}</tr>
          </thead>
          <tbody>
            {data.tool_grants.length === 0 ? (
              <tr><td colSpan={canEdit ? 5 : 4} className="text-center text-muted py-4">No tools granted yet.</td></tr>
            ) : data.tool_grants.map((g) => (
              <tr id={`agent-tool-row-${g.endpoint_id}-${g.tool_name}`} key={g.id}>
                <td>{g.application_id !== null ? <Link href={withBack(`/applications/${g.application_id}`, here)}>{g.application_name}</Link> : g.application_name}</td>
                <td><span className="badge bg-soft-info text-info">{g.endpoint_name}</span></td>
                <td><code>{g.tool_name}</code></td>
                <td className="text-muted fs-12">{g.constraints ? <code>{g.constraints}</code> : "—"}</td>
                {canEdit && (
                  <td className="text-end">
                    <ActionForm path="/agents/tool-revoke.php" confirm="Revoke this tool grant?">
                      <input type="hidden" name="agent" value={id} />
                      <input type="hidden" name="grant" value={g.id} />
                      <SubmitButton className="btn btn-sm btn-light-brand text-danger">Revoke</SubmitButton>
                    </ActionForm>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <ActionForm path="/agents/tool-grant.php" className="row g-2 align-items-end" id="agent-tools-grant-form" resetOnSuccess>
          <input type="hidden" name="agent" value={id} />
          <div className="col-sm-4">
            <label className="form-label fs-12" htmlFor="agent-form-field-endpoint">Endpoint</label>
            <select name="application_endpoint_id" id="agent-form-field-endpoint" className="form-select form-select-sm" defaultValue="">
              <option value="">— choose —</option>
              {data.options.tool_endpoints.map((e) => <option value={e.id} key={e.id}>{e.name}</option>)}
            </select>
          </div>
          <div className="col-sm-3">
            <label className="form-label fs-12" htmlFor="agent-form-field-tool_name">Tool name</label>
            <input type="text" name="tool_name" className="form-control form-control-sm" id="agent-form-field-tool_name" placeholder="find_expenses" />
          </div>
          <div className="col-sm-4">
            <label className="form-label fs-12" htmlFor="agent-form-field-constraints">Constraints (JSON)</label>
            <input type="text" name="constraints" className="form-control form-control-sm" id="agent-form-field-constraints"
                   placeholder={'{"max_amount": 500}'} />
          </div>
          <div className="col-sm-1">
            <SubmitButton className="btn btn-sm btn-primary w-100" id="agent-tools-grant-btn">Grant</SubmitButton>
          </div>
        </ActionForm>
      )}
    </>
  );
}

/**
 * The Skills tab (owner, 2026-09-27): what the next run carries, resolved exactly as the runner
 * resolves it — each skill with where it comes from (this agent, its role, a department, an
 * application, everyone), whether it is pinned, its version, how this harness delivers it, and
 * what is shadowed by a more specific assignment. Assign to this agent alone; withdraw what was
 * given to it alone (anything else is withdrawn where it was given).
 */
function SkillsTab({ data, here }: { data: AgentView; here: string | null }) {
  const id = data.agent.id as number;
  const s = data.skills;
  if (!s) return <p className="text-muted mb-0">Skills are not available for this agent.</p>;
  const DELIVERY: Record<string, [string, string]> = {
    inline: ["success", "Inline"], on_request: ["warning", "On request"], folder: ["info", "Folder"], none: ["secondary", "Not used"],
  };
  const inlineCount = s.resolved.filter((r) => r.delivery === "inline").length;
  const rule = s.rule === "inline"
    ? `The Claude harness carries the first ${s.inline_max} skills, by name, in the agent's persona (${s.inline_chars.toLocaleString()} characters each; a longer one is cut there); ${s.resolved.length > s.inline_max ? `the other ${s.resolved.length - s.inline_max} are on request through the skill_read tool.` : "every skill here is inline."}`
    : s.rule === "folder" ? "Hermes reads the whole synced folder: every skill here is available to the run, none is inlined."
    : "A system_one agent follows its playbooks and uses no skills; what is assigned to it waits for a harness that does.";
  return (
    <>
      <p className="fs-12 text-muted" id="agent-skills-rule">{rule} Assigned skills are synced read-only into the agent&rsquo;s directory before every run; the most specific assignment of a name wins.</p>
      {s.library_error && <div className="alert alert-warning py-2 fs-12" id="agent-skills-library-error">{s.library_error} The assignments below are shown without their descriptions and versions.</div>}
      <div className="table-responsive mb-3">
        <table className="table table-hover mb-0" id="agent-skills-table">
          <thead className="thead-light">
            <tr><th>Skill</th><th>From</th><th>Version</th><th>Delivery</th>{s.can.assign && <th className="text-end">Actions</th>}</tr>
          </thead>
          <tbody>
            {s.resolved.length === 0 ? (
              <tr><td colSpan={s.can.assign ? 5 : 4} className="text-center text-muted py-4">No skill reaches this agent yet.</td></tr>
            ) : s.resolved.map((r) => {
              const [tone, label] = DELIVERY[r.delivery] ?? ["secondary", r.delivery];
              return (
                <tr id={`agent-skill-row-${r.name}`} key={r.name}>
                  <td>
                    {r.in_library ? <Link href={withBack(`/ai/skills/${encodeURIComponent(r.name)}`, here)} className="fw-semibold">{r.name}</Link> : <span className="fw-semibold">{r.name}</span>}
                    {r.kind === "runbook" && <KindBadge kind={r.kind} className="ms-2" />}
                    {r.enabled === false && <span className="badge bg-soft-danger text-danger ms-2">disabled in the library</span>}
                    {!r.in_library && <span className="badge bg-soft-warning text-warning ms-2">not in the library</span>}
                    {r.description && <div className="fs-12 text-muted text-truncate-2-line">{r.description}</div>}
                  </td>
                  <td>
                    {r.source.href ? <Link href={withBack(r.source.href, here)}>{r.source.label}</Link> : r.source.label}
                    {r.assigned_by && <div className="fs-12 text-muted">by <Who who={{ id: r.assigned_by.id, name: r.assigned_by.name }} here={here} /></div>}
                    {r.note && <div className="fs-12 text-muted">{r.note}</div>}
                    {r.shadowed.length > 0 && <div className="fs-12 text-muted">also from {r.shadowed.map((x, i) => <span key={`${x.scope_kind}-${i}`}>{i > 0 && ", "}{x.href ? <Link href={withBack(x.href, here)}>{x.label}</Link> : x.label}</span>)} (shadowed)</div>}
                  </td>
                  <td className="text-nowrap">
                    {r.pinned_bundle_hash
                      ? <><code className="fs-12" title={r.pinned_bundle_hash}>{r.pinned_bundle_hash.slice(0, 12)}</code> <span className="badge bg-soft-secondary text-dark">{r.pinned_by_config ? "pinned in the configuration" : "pinned"}</span></>
                      : <>{r.version ? <code className="fs-12">{r.version}</code> : <span className="text-muted">—</span>} <span className="fs-12 text-muted">newest</span></>}
                  </td>
                  <td><span className={`badge bg-soft-${tone} text-${tone}`}>{label}</span></td>
                  {s.can.assign && (
                    <td className="text-end">
                      {r.source.scope_kind === "agent" && r.assignment_id !== null ? (
                        <ActionForm path="/skills/unassign.php" confirm={`Withdraw ${r.name} from this agent?`}>
                          <input type="hidden" name="skill_assignment" value={r.assignment_id} />
                          <SubmitButton className="btn btn-sm btn-light-brand" id={`agent-skill-withdraw-${r.name}`}>Withdraw</SubmitButton>
                        </ActionForm>
                      ) : r.source.scope_kind === "pinned" ? <span className="fs-12 text-muted">set in the configuration</span>
                        : <Link href={withBack("/skills", here)} className="fs-12">withdraw where it was given</Link>}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {s.rule === "inline" && s.resolved.length > 0 && <p className="fs-12 text-muted">{inlineCount} inline of {s.resolved.length}.</p>}
      {s.can.assign && (
        <div className="card mb-0" id="agent-skills-assign-card"><div className="card-body">
          {s.assignable.length > 0
            ? <AgentSkillAssign agentId={id} assignable={s.assignable} />
            : <p className="text-muted fs-12 mb-0">Every enabled skill in the library already reaches this agent.</p>}
        </div></div>
      )}
      <p className="fs-12 text-muted mt-3 mb-0">The library, every assignment and the agents&rsquo; proposals: <Link href={withBack("/skills", here)}>Skills</Link> · <Link href={withBack("/ai/skills", here)}>Skill library</Link>.</p>
    </>
  );
}

function DutiesTab({ data, timeZone, here }: { data: AgentView; timeZone: string; here: string | null }) {
  const id = data.agent.id as number;
  const canEdit = data.can.edit;
  return (
    <>
      <div className="table-responsive">
        <table className="table table-hover mb-0" id="agent-duties-table">
          <thead className="thead-light">
            <tr><th>Name</th><th>Schedule</th><th>Timezone</th><th>Next run</th><th>Active</th>{canEdit && <th className="text-end">Run</th>}</tr>
          </thead>
          <tbody>
            {data.duties.length === 0 ? (
              <tr><td colSpan={canEdit ? 6 : 5} className="text-center text-muted py-4">No duties yet — add one from Edit.</td></tr>
            ) : data.duties.map((d) => (
              <tr id={`agent-duty-row-${d.id}`} key={d.id}>
                <td className="fw-medium">{d.name}<div className="fs-11 text-muted">{d.instructions}</div></td>
                <td><code>{d.schedule_cron}</code></td>
                <td className="text-muted fs-12">{d.timezone}</td>
                <td className="text-muted fs-12">{d.next_run_at ? formatTs(d.next_run_at, timeZone) : "not scheduled yet"}</td>
                <td>
                  {d.active
                    ? <span className="badge bg-soft-success text-success">Active</span>
                    : <span className="badge bg-soft-secondary text-secondary">Paused</span>}
                </td>
                {canEdit && (
                  <td className="text-end">
                    <ActionForm path="/agents/run-duty.php">
                      <input type="hidden" name="agent" value={id} />
                      <input type="hidden" name="duty" value={d.id} />
                      <SubmitButton className="btn btn-sm btn-light-brand" id={`agent-duty-run-${d.id}`}>Run now</SubmitButton>
                    </ActionForm>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <p className="fs-12 text-muted mt-2 mb-0">Add, edit or remove duties from <Link href={withBack(`/agents/${id}/edit`, here)}>Edit</Link> —
          every change writes a new configuration version.</p>
      )}
    </>
  );
}

function RosterTab({ data, timeZone, here }: { data: AgentView; timeZone: string; here: string | null }) {
  const { agent: a, roster } = data;
  const id = a.id as number;
  const canEdit = data.can.edit;

  if (a.kind === "orchestrator") {
    const rostered = new Set(roster.map((r) => r.member_id));
    const available = data.options.subagents.filter((o) => !rostered.has(o.id));
    return (
      <>
        <div className="table-responsive mb-3">
          <table className="table table-hover mb-0" id="agent-roster-table">
            <thead className="thead-light">
              <tr><th>Name</th><th>Role</th><th>Status</th><th>Note</th><th>Added</th>{canEdit && <th className="text-end">Actions</th>}</tr>
            </thead>
            <tbody>
              {roster.length === 0 ? (
                <tr><td colSpan={canEdit ? 6 : 5} className="text-center text-muted py-4">No subagents on this roster yet.</td></tr>
              ) : roster.map((r) => (
                <tr id={`agent-roster-row-${r.member_id}`} key={r.member_id}>
                  <td><Link href={withBack(`/agents/${r.member_id}`, here)}>{r.name}</Link></td>
                  <td className="text-muted fs-12">{r.role_key ?? "—"}</td>
                  <td><span className="badge bg-soft-secondary text-secondary">{ucfirst(r.status ?? "")}</span></td>
                  <td className="text-muted fs-12">{r.note ?? "—"}</td>
                  <td className="text-muted fs-12">{r.added_at ? formatTs(r.added_at, timeZone) : "—"}</td>
                  {canEdit && (
                    <td className="text-end">
                      <ActionForm path="/agents/subagent-remove.php" confirm={`Remove ${r.name} from this roster?`}>
                        <input type="hidden" name="agent" value={id} />
                        <input type="hidden" name="subagent" value={r.member_id} />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger">Remove</SubmitButton>
                      </ActionForm>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit && (
          <>
            <ActionForm path="/agents/subagent-add.php" className="row g-2 align-items-end" id="agent-roster-add-form" resetOnSuccess>
              <input type="hidden" name="agent" value={id} />
              <div className="col-sm-5">
                <label className="form-label fs-12" htmlFor="agent-form-field-subagent">Subagent</label>
                <select name="subagent" id="agent-form-field-subagent" className="form-select form-select-sm" required defaultValue="">
                  <option value="">— choose —</option>
                  {available.map((o) => <option value={o.id} key={o.id}>{o.name}</option>)}
                </select>
              </div>
              <div className="col-sm-5">
                <label className="form-label fs-12" htmlFor="agent-form-field-roster-note">Note</label>
                <input type="text" name="note" className="form-control form-control-sm" id="agent-form-field-roster-note"
                       placeholder="What this subagent handles" />
              </div>
              <div className="col-sm-2">
                <SubmitButton className="btn btn-sm btn-primary w-100" id="agent-roster-add-btn">Add</SubmitButton>
              </div>
            </ActionForm>
            {available.length === 0 && data.options.subagents.length > 0 && (
              <p className="fs-12 text-muted mt-2">Every subagent this app knows is already on this roster.</p>
            )}
            {data.options.subagents.length === 0 && (
              <p className="fs-12 text-muted mt-2">No subagents exist yet to add — hire one, or set another agent&rsquo;s kind to subagent.</p>
            )}
          </>
        )}
      </>
    );
  }

  return (
    <>
      <p className="fs-12 text-muted mb-3">This agent is a subagent — its orchestrator roster memberships are managed
        from each orchestrator&rsquo;s own Roster tab, not here.</p>
      <div className="table-responsive">
        <table className="table table-hover mb-0" id="agent-orchestrators-table">
          <thead className="thead-light"><tr><th>Orchestrator</th><th>Note</th><th>Added</th></tr></thead>
          <tbody>
            {roster.length === 0 ? (
              <tr><td colSpan={3} className="text-center text-muted py-4">Not on any orchestrator&rsquo;s roster.</td></tr>
            ) : roster.map((r) => (
              <tr id={`agent-orchestrator-row-${r.member_id}`} key={r.member_id}>
                <td><Link href={withBack(`/agents/${r.member_id}`, here)}>{r.name}</Link></td>
                <td className="text-muted fs-12">{r.note ?? "—"}</td>
                <td className="text-muted fs-12">{r.added_at ? formatTs(r.added_at, timeZone) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const APPROVAL_COLOR: Record<string, string> = { approved: "success", executed: "success", rejected: "danger", execution_failed: "danger", pending: "warning" };

/**
 * What the agent is stuck on, at the top of its page (owner, 2026-09-27: "paused for an approval"
 * must be a few clicks from released). Each paused run lists its pending requests; the approver
 * decides here — approve (and, by default, let the agent carry on with a follow-up run) or reject
 * with a reason — and the agent's nearest human manager may withdraw. Deciding the last pending
 * request releases the run; the handlers are the approvals module's own.
 */
function PausedBlock({ data, timeZone, here }: { data: AgentView; timeZone: string; here: string | null }) {
  const a = data.agent;
  const count = data.paused.reduce((n, r) => n + r.requests.length, 0);
  return (
    <div className="card border-warning" id="agent-paused-card">
      <div className="card-header d-flex flex-wrap align-items-center gap-2">
        <h5 className="card-title mb-0 text-warning"><i className="feather-pause-circle me-2"></i>Paused for an approval</h5>
        <span className="text-muted fs-12">{a.name} asked for {count === 1 ? "one thing" : `${count} things`} and waits on the answer{data.paused.length > 1 ? ` in ${data.paused.length} runs` : ""}. Decide each below to release it.</span>
      </div>
      <div className="card-body">
        {data.paused.map((run) => (
          <div className="mb-4" key={run.id} id={`agent-paused-run-${run.id}`}>
            <div className="fs-12 text-muted mb-2">
              Run <Link href={withBack(`/ai/runs/${run.id}`, here)} className="fw-semibold">#{run.id}</Link> · {run.duty_name ?? run.trigger.replace(/_/g, " ")} · started {formatTs(run.started_at, timeZone, false)}
            </div>
            {run.requests.map((r) => (
              <div className="border rounded p-3 mb-2" key={r.approval_request_id} id={`agent-paused-request-${r.approval_request_id}`}>
                <div className="d-flex flex-wrap align-items-center gap-2 mb-1">
                  <Link href={withBack(`/approvals/${r.approval_request_id}`, here)} className="fw-semibold text-wrap">{r.summary}</Link>
                  {r.amount !== null && <span className="badge bg-soft-secondary text-secondary">{r.amount} {r.currency ?? ""}</span>}
                </div>
                <div className="fs-12 text-muted mb-2">
                  {r.action_key}{r.policy ? ` · ${r.policy}` : ""} · asked {formatTs(r.created_at, timeZone, false)} · approver {r.approver.name}
                  {r.expires_at && ` · expires ${formatTs(r.expires_at, timeZone, false)}`}
                </div>
                {r.can.decide ? (
                  <div className="row g-3">
                    <div className="col-12 col-md-7">
                      <ActionForm path="/approvals/approve.php" confirm="Approve this? The action is carried out straight away." id={`agent-paused-approve-${r.approval_request_id}`}>
                        <input type="hidden" name="approval_request" value={r.approval_request_id} />
                        <input type="text" name="note" className="form-control form-control-sm mb-2" placeholder="Note for the agent (optional)" maxLength={1000} />
                        <div className="form-check mb-2">
                          <input className="form-check-input" type="checkbox" name="follow_up" value="1" defaultChecked id={`agent-paused-follow-${r.approval_request_id}`} />
                          <label className="form-check-label fs-12" htmlFor={`agent-paused-follow-${r.approval_request_id}`}>Then let {a.name} carry on with the rest of the work</label>
                        </div>
                        <SubmitButton className="btn btn-sm btn-success"><i className="feather-check me-2"></i>Approve and carry out</SubmitButton>
                      </ActionForm>
                    </div>
                    <div className="col-12 col-md-5">
                      <ActionForm path="/approvals/reject.php" id={`agent-paused-reject-${r.approval_request_id}`}>
                        <input type="hidden" name="approval_request" value={r.approval_request_id} />
                        <input type="hidden" name="follow_up" value="1" />
                        <input type="text" name="reason" className="form-control form-control-sm mb-2" placeholder="Why not (the agent reads it)" maxLength={1000} required />
                        <SubmitButton className="btn btn-sm btn-light-brand text-danger">Reject</SubmitButton>
                      </ActionForm>
                    </div>
                  </div>
                ) : (
                  <div className="fs-13 text-muted">Waiting for {r.approver.name} to decide.</div>
                )}
                {r.can.cancel && (
                  <ActionForm path="/approvals/cancel.php" confirm="Withdraw this request? The agent's run is released without it." className="mt-2" id={`agent-paused-cancel-${r.approval_request_id}`}>
                    <input type="hidden" name="approval_request" value={r.approval_request_id} />
                    <SubmitButton className="btn btn-sm btn-link text-muted p-0">Withdraw the request instead</SubmitButton>
                  </ActionForm>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Everything about the agent's work, on its own page (owner, 2026-09-27: nobody should have to
 * bounce around screens for it): model calls, spend, runs and evaluations from the AI Ops views,
 * then what activity memory knows. Each section still links to the AI Ops screen that goes deeper.
 */
function PerformanceTab({ data, timeZone, here }: { data: AgentView; timeZone: string; here: string | null }) {
  const id = data.agent.id as number;
  const { ops } = data;
  const { this_month: month, all } = ops.ledger;
  const latestEval = ops.evals?.runs.find((r) => r.score !== null) ?? null;
  const tiles: [string, string, string][] = [
    [String(month.calls), "Model calls this month", money(month.cost, month.currency)],
    [String(all.calls), "Model calls all time", money(all.cost, all.currency)],
    [String(ops.run_counts.total), "Runs all time", ops.run_counts.active > 0 ? `${ops.run_counts.active} under way` : `${ops.run_counts.failed} failed`],
    [latestEval ? `${Number(latestEval.score)}%` : "—", "Latest eval score", latestEval ? `${latestEval.cases_passed}/${latestEval.cases_total} cases` : "not evaluated"],
    [String(data.counts.activity), "Actions logged", "all time"],
    [String(data.counts.escalations), "Escalations raised", `${data.counts.approvals} approvals asked`],
  ];
  const periods: [string, AgentOps["ledger"]["all"]][] = [["This month", month], ["Last month", ops.ledger.last_month], ["All time", all]];

  return (
    <>
      <div className="row g-3 mb-4" id="agent-performance-tiles">
        {tiles.map(([value, label, note]) => (
          <div className="col-6 col-md-4" key={label}>
            <div className="text-center p-3 border rounded h-100">
              <div className="fs-24 fw-bold">{value}</div>
              <div className="fs-12 text-muted">{label}</div>
              <div className="fs-12 text-muted">{note}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="d-flex align-items-center mb-2">
        <h6 className="fw-bold mb-0">Spend</h6>
        <Link href="/ai/spend?group_by=agent" className="ms-auto fs-12">Spend by agent</Link>
      </div>
      <div className="table-responsive mb-4">
        <table className="table table-sm mb-0" id="agent-performance-spend">
          <thead className="thead-light"><tr><th>Period</th><th className="text-end">Calls</th><th className="text-end">Failed</th><th className="text-end">In / out</th><th className="text-end">Cached</th><th className="text-end">Latency</th><th className="text-end">Cost</th></tr></thead>
          <tbody>
            {periods.map(([label, p]) => (
              <tr key={label}>
                <td>{label}</td>
                <td className="text-end">{p.calls}</td>
                <td className={`text-end${p.failed > 0 ? " text-danger" : ""}`}>{p.failed}</td>
                <td className="text-end">{tokens(p.input_tokens)} / {tokens(p.output_tokens)}</td>
                <td className="text-end">{tokens(p.cache_read_tokens)}</td>
                <td className="text-end">{p.avg_latency_ms !== null ? `${(p.avg_latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                <td className="text-end">{money(p.cost, p.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="d-flex align-items-center mb-2">
        <h6 className="fw-bold mb-0">Recent runs</h6>
        {ops.run_counts.last_started_at && <span className="ms-auto fs-12 text-muted">last started {formatTs(ops.run_counts.last_started_at, timeZone, false)}</span>}
      </div>
      {ops.runs.length === 0 ? (
        <p className="text-muted fs-13">No runs yet that you may see.</p>
      ) : (
        <div className="table-responsive mb-4">
          <table className="table table-sm table-hover mb-0" id="agent-performance-runs">
            <thead className="thead-light"><tr><th>Run</th><th>Trigger</th><th>Outcome</th><th className="text-end">In / out</th><th className="text-end">Cost</th></tr></thead>
            <tbody>
              {ops.runs.map((r) => (
                <tr key={r.id} id={`agent-run-row-${r.id}`}>
                  <td className="text-nowrap"><Link href={withBack(`/ai/runs/${r.id}`, here)} className="fw-semibold">#{r.id}</Link>
                    <div className="fs-12 text-muted">{formatTs(r.started_at, timeZone, false)}</div></td>
                  <td>{r.duty_name ?? r.trigger.replace(/_/g, " ")}
                    <div className="fs-12 text-muted">{r.model_id !== null && r.model_name ? <Link href={withBack(`/settings/models/${r.model_id}/edit`, here)}>{r.model_name}</Link> : r.model_name ?? r.harness ?? ""}
                      {r.requested_by ? <> · for <Who who={r.requested_by} here={here} /></> : r.requested_by_name ? ` · for ${r.requested_by_name}` : ""}</div></td>
                  <td><StateBadge state={r.status} />{r.error && <div className="fs-12 text-danger text-wrap">{r.error}</div>}
                    {r.approval_request_id !== null && <div className="fs-12"><Link href={withBack(`/approvals/${r.approval_request_id}`, here)}>approval #{r.approval_request_id}</Link></div>}</td>
                  <td className="text-end text-nowrap">{tokens(r.input_tokens)} / {tokens(r.output_tokens)}</td>
                  <td className="text-end text-nowrap">{money(r.cost, r.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="d-flex align-items-center mb-2">
        <h6 className="fw-bold mb-0">Recent model calls</h6>
        <Link href={`/ai/prompt-log?agent=${id}&period=all`} className="ms-auto fs-12" id="agent-performance-prompt-log">All calls in the prompt log</Link>
      </div>
      {ops.calls.length === 0 ? (
        <p className="text-muted fs-13">No model calls yet that you may see.</p>
      ) : (
        <div className="table-responsive mb-4">
          <table className="table table-sm table-hover mb-0" id="agent-performance-calls">
            <thead className="thead-light"><tr><th>When</th><th>Model</th><th>Outcome</th><th className="text-end">In / out</th><th className="text-end">Latency</th><th className="text-end">Cost</th></tr></thead>
            <tbody>
              {ops.calls.map((c) => (
                <tr key={c.id} id={`agent-call-row-${c.id}`}>
                  <td className="text-nowrap"><Link href={withBack(`/ai/prompt-log/${c.id}`, here)} className="fw-semibold">{formatTs(c.occurred_at, timeZone, false)}</Link>
                    {c.run_id !== null && <div><Link href={withBack(`/ai/runs/${c.run_id}`, here)} className="fs-12 text-muted">run #{c.run_id}</Link></div>}</td>
                  <td>{c.model_id !== null ? <Link href={withBack(`/settings/models/${c.model_id}/edit`, here)}>{c.model_name ?? c.provider_model_id}</Link> : c.model_name ?? c.provider_model_id}<div className="fs-12 text-muted">{c.call_kind.replace(/_/g, " ")}{c.acting.name ? <> · for <Who who={c.acting} here={here} /></> : ""}</div></td>
                  <td><StateBadge state={c.status} label={c.status_label} />{c.error_code && <div className="fs-12 text-danger">{c.error_code}</div>}</td>
                  <td className="text-end text-nowrap">{tokens(c.input_tokens)} / {tokens(c.output_tokens)}</td>
                  <td className="text-end text-nowrap">{c.latency_ms !== null ? `${(c.latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                  <td className="text-end text-nowrap">{money(c.cost, c.currency, 6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ops.evals && (
        <>
          <div className="d-flex align-items-center mb-2">
            <h6 className="fw-bold mb-0">Evaluations</h6>
            <Link href={`/ai/evals?agent=${id}`} className="ms-auto fs-12" id="agent-performance-evals">Its eval sets</Link>
          </div>
          {ops.evals.alerts.length > 0 && (
            <ul className="list-group list-group-flush mb-3" id="agent-performance-eval-alerts">
              {ops.evals.alerts.map((al) => (
                <li className="list-group-item d-flex flex-wrap gap-2 align-items-center px-0" key={al.id}>
                  <StateBadge state={al.severity} label={al.severity} />
                  <Link href={withBack(`/ai/evals/alerts/${al.id}`, here)} className="fw-medium">{al.eval_set_name}</Link>
                  <span className="fs-13 text-wrap">{al.detail}</span>
                  <span className="ms-auto fs-12 text-muted">{al.status}</span>
                </li>
              ))}
            </ul>
          )}
          {ops.evals.sets.length === 0 ? (
            <p className="text-muted fs-13">No eval set written for this agent yet — which is not the same as passing.</p>
          ) : (
            <div className="table-responsive mb-3">
              <table className="table table-sm table-hover mb-0" id="agent-performance-eval-sets">
                <thead className="thead-light"><tr><th>Set</th><th className="text-end">Cases</th><th className="text-end">Pass at</th><th>Status</th><th>Latest run</th></tr></thead>
                <tbody>
                  {ops.evals.sets.map((s) => {
                    const last = ops.evals!.runs.find((r) => r.eval_set_id === s.id) ?? null;
                    return (
                      <tr key={s.id ?? s.name}>
                        <td className="text-wrap"><Link href={withBack(`/ai/evals/${s.id}`, here)} className="fw-semibold">{s.name}</Link></td>
                        <td className="text-end">{s.active_case_count}{s.case_count !== s.active_case_count && <span className="text-muted"> / {s.case_count}</span>}</td>
                        <td className="text-end">{Number(s.pass_threshold)}%</td>
                        <td><StateBadge state={s.status} label={s.status_label} /></td>
                        <td>{last ? (
                          <><Link href={withBack(`/ai/evals/runs/${last.id}`, here)}>#{last.id}</Link> <StateBadge state={last.status} />
                            <span className="fs-12 text-muted ms-1">{last.score !== null ? `${Number(last.score)}% (${last.cases_passed}/${last.cases_total})` : last.trigger}</span></>
                        ) : <span className="text-muted fs-12">never run</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {ops.evals.runs.length > 0 && (
            <ul className="list-unstyled mb-4 fs-13" id="agent-performance-eval-runs">
              {ops.evals.runs.map((r) => (
                <li key={r.id} className="d-flex flex-wrap gap-2 py-1">
                  <Link href={withBack(`/ai/evals/runs/${r.id}`, here)}>Run #{r.id}</Link><StateBadge state={r.status} />
                  <span className="text-muted"><Link href={withBack(`/ai/evals/${r.eval_set_id}`, here)}>{r.eval_set_name}</Link> · {r.score !== null ? `${Number(r.score)}% (${r.cases_passed}/${r.cases_total})` : r.trigger}</span>
                  <span className="ms-auto text-muted fs-12">{formatTs(r.started_at ?? r.finished_at, timeZone, false)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <div className="d-flex align-items-center mb-2">
        <h6 className="fw-bold mb-0">Recent approval requests</h6>
        <Link href="/approvals?role=approver" className="ms-auto fs-12">The approvals queue</Link>
      </div>
      {data.approvals.length === 0 ? (
        <p className="text-muted fs-13">None yet.</p>
      ) : (
        <ul className="list-group list-group-flush mb-4" id="agent-performance-approvals">
          {data.approvals.map((ap) => {
            const c = APPROVAL_COLOR[ap.status] ?? "secondary";
            return (
              <li className="list-group-item d-flex flex-wrap justify-content-between align-items-center gap-2 px-0" key={ap.id}>
                <span className="text-wrap">
                  <Link href={withBack(`/approvals/${ap.id}`, here)}>{ap.summary}</Link>
                  <span className="fs-12 text-muted d-block">
                    asked {formatTs(ap.created_at, timeZone, false)}{ap.approver_name ? <> · approver <Who who={{ id: ap.approver_member_id, name: ap.approver_name }} here={here} /></> : ""}
                    {ap.agent_run_id !== null && <> · <Link href={withBack(`/ai/runs/${ap.agent_run_id}`, here)}>run #{ap.agent_run_id}</Link></>}
                    {ap.decided_at && ` · decided ${formatTs(ap.decided_at, timeZone, false)}`}
                  </span>
                </span>
                <span className={`badge bg-soft-${c} text-${c}`}>{ucfirst(ap.status.replace(/_/g, " "))}</span>
              </li>
            );
          })}
        </ul>
      )}

      <h6 className="fw-bold mb-2">Performance reviews</h6>
      {data.reviews.length === 0 ? (
        <p className="text-muted fs-13">No reviews written yet.</p>
      ) : (
        <ul className="list-group list-group-flush">
          {data.reviews.map((r) => (
            <li className="list-group-item px-0" key={r.id}>
              <div className="d-flex justify-content-between">
                <span className="fw-medium">{r.period_start} – {r.period_end}</span>
                {r.rating !== null && <span className="badge bg-soft-brand text-brand">{r.rating}/5</span>}
              </div>
              {r.summary && <p className="fs-13 mb-0 mt-1">{r.summary}</p>}
            </li>
          ))}
        </ul>
      )}
      <Link href={withBack(`/team/reviews/new?member=${id}`, here)} className="btn btn-sm btn-light-brand mt-3" id="agent-performance-review-btn">Write a review</Link>
    </>
  );
}

function TrailTab({ data, timeZone }: { data: AgentView; timeZone: string }) {
  const id = data.agent.id as number;
  return (
    <>
      <h6 className="fw-bold mb-2">Employment record</h6>
      <div className="table-responsive mb-3">
        <table className="table table-hover mb-0" id="agent-trail-events-table">
          <thead className="thead-light"><tr><th>When</th><th>Event</th><th>Note</th></tr></thead>
          <tbody>
            {data.hr_events.length === 0 ? (
              <tr><td colSpan={3} className="text-center text-muted py-4">No HR events yet.</td></tr>
            ) : data.hr_events.map((e) => (
              <tr id={`agent-hr-event-row-${e.id}`} key={e.id}>
                <td className="text-muted fs-12">{formatTs(e.occurred_at, timeZone)}</td>
                <td>{e.label}</td>
                <td className="fs-12">{e.note ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Link href={`/activity?entity_type=member&entity_id=${id}&period=all`} className="fs-12" id="agent-trail-activity-link">
        <i className="feather-activity me-1"></i>Full activity trail
      </Link>
    </>
  );
}
