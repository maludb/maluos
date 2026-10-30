"use client";
/* eslint-disable @next/next/no-img-element */

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import DefaultApplicationForm from "./DefaultApplicationForm";
import { dateOnly, formatDate } from "@/lib/format";
import type { ActionState } from "@/lib/actions";
import type { MySettings as Data } from "@/lib/schemas/settings";
import { settingsSecret, type SecretAnswer } from "./secretActions";

const NAV: [Data["section"], string, string][] = [
  ["profile", "feather-user", "Profile"], ["notifications", "feather-bell", "Notifications"],
  ["security", "feather-shield", "Security (2FA)"], ["tokens", "feather-key", "AI access (MCP)"],
  ["desks", "feather-monitor", "Desks"],
];

/** A save that PHP answers with a sentence ("Profile saved") shows it, as the section's notice did. */
const notice = (state: ActionState) =>
  state.status === "ok" && state.message ? <div className="alert alert-success py-2 mt-3 mb-0">{state.message}.</div>
    : state.status === "invalid" ? <div className="alert alert-danger py-2 mt-3 mb-0">{state.errors.join(" ")}</div>
    : state.status === "error" || state.status === "pending_approval" ? <div className="alert alert-danger py-2 mt-3 mb-0">{state.message}</div> : null;

/**
 * Settings (screen `settings`) — app/views/settings/page.php and its five section partials.
 * A section is a URL (?section=), as it was. One-time secrets arrive through
 * settingsSecret() and live in this component's state only.
 */
export default function MySettings({ data, timeZone, isSuperAdmin = false }: { data: Data; timeZone: string; isSuperAdmin?: boolean }) {
  return (
    <>
      <PageHeader title="Settings" crumbs={[{ label: "Settings" }]} id="settings" />
      <div className="main-content" data-screen="settings">
        <div className="row">
          <div className="col-lg-3 mb-3">
            <div className="card stretch stretch-full">
              <div className="list-group list-group-flush" id="settings-nav">
                {NAV.map(([key, icon, label]) => (
                  <Link href={`/settings?section=${key}`} key={key} scroll={false}
                        className={`list-group-item list-group-item-action d-flex align-items-center gap-2${data.section === key ? " active" : ""}`}>
                    <i className={icon}></i><span>{label}</span>
                  </Link>
                ))}
                {/* Your own, but a page of its own (db/156): the Telegram, SMS and email that reach your assistant. */}
                <Link href="/settings/channels" id="settings-nav-channels" className="list-group-item list-group-item-action d-flex align-items-center gap-2">
                  <i className="feather-message-circle"></i><span>My channels</span>
                </Link>
                {/* The business's menu, not the member's own settings — so a link out, not a section. */}
                {isSuperAdmin && ([
                  ["/settings/navigation", "settings-nav-navigation", "feather-menu", "Navigation & applications"],
                  ["/settings/business", "settings-nav-business", "feather-briefcase", "Business settings"],
                  ["/settings/models", "settings-nav-models", "feather-cpu", "Models"],
                  ["/settings/prompts", "settings-nav-prompts", "feather-file-text", "Prompt library"],
                  ["/settings/approval-policies", "settings-nav-policies", "feather-shield", "Approval policies"],
                ] as const).map(([href, id, icon, label]) => (
                  <Link href={href} id={id} key={id} className="list-group-item list-group-item-action d-flex align-items-center gap-2">
                    <i className={icon}></i><span>{label}</span>
                  </Link>
                ))}
              </div>
            </div>
          </div>
          <div className="col-lg-9">
            <div id="settings-content">
              {data.section === "profile" && <Profile data={data} />}
              {data.section === "notifications" && <Notifications data={data} />}
              {data.section === "security" && <Security data={data} />}
              {data.section === "tokens" && <Tokens data={data} timeZone={timeZone} />}
              {data.section === "desks" && <Desks data={data} timeZone={timeZone} />}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card stretch stretch-full">
      <div className="card-header"><h5 className="card-title">{title}</h5></div>
      <div className="card-body">{children}</div>
    </div>
  );
}

function Profile({ data }: { data: Data }) {
  const p = data.profile;
  return (
    <Section title="Profile">
      <ActionForm path="/settings/profile.php" renderState={notice}>
        <div className="row mb-3"><label className="col-lg-3 col-form-label" htmlFor="settings-field-name">Display name</label>
          <div className="col-lg-9"><input type="text" name="display_name" id="settings-field-name" className="form-control" defaultValue={p.display_name} required /></div></div>
        <div className="row mb-3"><label className="col-lg-3 col-form-label" htmlFor="settings-field-tz">Timezone</label>
          <div className="col-lg-9">
            <select name="timezone" id="settings-field-tz" className="form-control" defaultValue={p.timezone}>
              {data.timezones.map((tz) => <option value={tz} key={tz}>{tz}</option>)}
            </select>
          </div></div>
        <div className="row mb-3"><label className="col-lg-3 col-form-label" htmlFor="settings-field-org">Organization</label>
          <div className="col-lg-9"><input type="text" name="organization" id="settings-field-org" className="form-control" defaultValue={p.organization} /></div></div>
        <div className="row mb-3"><label className="col-lg-3 col-form-label" htmlFor="settings-field-bio">Bio</label>
          <div className="col-lg-9"><textarea name="bio" id="settings-field-bio" className="form-control" rows={3} defaultValue={p.bio}></textarea></div></div>
        <div className="row"><div className="col-lg-9 offset-lg-3">
          <SubmitButton className="btn btn-primary"><i className="feather-save me-2"></i>Save profile</SubmitButton>
        </div></div>
      </ActionForm>
      <hr className="my-4" />
      <h6 className="fs-13 mb-2">Your default application</h6>
      <DefaultApplicationForm value={data.default_application} idPrefix="settings-default-app" />
    </Section>
  );
}

const SWITCHES: [keyof Data["notifications"], string, string][] = [
  ["notify_reply", "Replies & comments", "When someone replies to your issue or comments on your plan"],
  ["notify_event", "Events", "Event changes, cancellations, and reminders"],
  ["notify_exam", "Exams & certifications", "Exam-in-7-days and certification-expiring reminders"],
  ["notify_digest", "Community digest", "What changed since you last logged in"],
];

function Notifications({ data }: { data: Data }) {
  return (
    <Section title="Email notifications">
      <ActionForm path="/settings/notifications.php" renderState={notice}>
        {SWITCHES.map(([name, label, desc]) => (
          <div className="form-check form-switch mb-3" key={name}>
            <input type="checkbox" className="form-check-input" role="switch" name={name} id={`settings-${name}`} value="1"
                   defaultChecked={data.notifications[name]} />
            <label className="form-check-label" htmlFor={`settings-${name}`}><strong>{label}</strong><div className="fs-12 text-muted">{desc}</div></label>
          </div>
        ))}
        <SubmitButton className="btn btn-primary"><i className="feather-save me-2"></i>Save preferences</SubmitButton>
      </ActionForm>
    </Section>
  );
}

/** Runs one secret-bearing write and keeps its answer in state — the only place the secret ever lives here. */
function useSecret() {
  const router = useRouter();
  const [answer, setAnswer] = useState<SecretAnswer | null>(null);
  const [pending, startTransition] = useTransition();
  const run = (kind: Parameters<typeof settingsSecret>[0], fields: Record<string, string> = {}) =>
    startTransition(async () => {
      const next = await settingsSecret(kind, fields);
      setAnswer(next);
      if (next.status === "ok") router.refresh();
    });
  return { answer, pending, run };
}

function Security({ data }: { data: Data }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  // The QR and key, then the recovery codes: component state only, gone when the page is left.
  const [enroll, setEnroll] = useState<{ qrDataUri: string; manualKey: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");

  const begin = () => startTransition(async () => {
    const a = await settingsSecret("enroll2fa", {});
    if (a.status === "error") { setError(a.message); return; }
    setError("");
    if (a.enrolling && a.qrDataUri && a.manualKey) setEnroll({ qrDataUri: a.qrDataUri, manualKey: a.manualKey });
    else router.refresh();                                  // already enabled elsewhere
  });
  const confirm = () => startTransition(async () => {
    const a = await settingsSecret("enable2fa", { code });
    if (a.status === "error") {
      // A refused code keeps the QR on screen, as PHP re-rendered it; an expired enrollment starts over.
      setError(a.message);
      if (a.expired) setEnroll(null);
      return;
    }
    setError(""); setEnroll(null); setCode(""); setCodes(a.recoveryCodes ?? []);
    router.refresh();
  });

  return (
    <Section title="Two-factor authentication">
      {error !== "" && <div className="alert alert-danger py-2">{error}</div>}
      {codes.length > 0 && (
        <div className="alert alert-success">
          <strong>2FA is on.</strong> Save these recovery codes now — each works once if you lose your authenticator:
          <div className="row mt-2">{codes.map((c) => <div className="col-6 col-md-4" key={c}><code className="user-select-all">{c}</code></div>)}</div>
        </div>
      )}
      {data.security.enabled && codes.length === 0 ? (
        <>
          <p><span className="badge bg-soft-success text-success"><i className="feather-shield me-1"></i>Enabled</span> Your account is protected by an authenticator app.</p>
          <ActionForm path="/settings/2fa/disable.php" resetOnSuccess>
            <label className="form-label fs-13" htmlFor="settings-2fa-disable-code">Enter a current code (or a recovery code) to disable 2FA:</label>
            <div className="input-group" style={{ maxWidth: "340px" }}>
              <input type="text" name="code" id="settings-2fa-disable-code" className="form-control" placeholder="123456" inputMode="numeric" required />
              <SubmitButton className="btn btn-outline-danger">Disable 2FA</SubmitButton>
            </div>
          </ActionForm>
        </>
      ) : enroll ? (
        <>
          <h6 className="fw-bold mb-2">1. Scan this with your authenticator app</h6>
          <img src={enroll.qrDataUri} alt="2FA QR code" width={180} height={180} className="mb-2 border rounded" />
          <p className="fs-12 text-muted">Or enter this key manually: <code className="user-select-all">{enroll.manualKey}</code></p>
          <h6 className="fw-bold mb-2 mt-3">2. Enter the 6-digit code to confirm</h6>
          <form onSubmit={(e) => { e.preventDefault(); confirm(); }}>
            <div className="input-group" style={{ maxWidth: "340px" }}>
              <input type="text" name="code" id="settings-2fa-code" className="form-control" placeholder="123456" inputMode="numeric"
                     autoComplete="one-time-code" required autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
              <button type="submit" className="btn btn-primary" disabled={pending}>Confirm &amp; enable</button>
            </div>
          </form>
        </>
      ) : !data.security.enabled ? (
        <>
          <p>Add a second factor with an authenticator app (Google Authenticator, 1Password, Authy…). It applies to password and Google sign-ins alike.</p>
          <button type="button" className="btn btn-primary" disabled={pending} onClick={begin}>
            <i className="feather-shield me-2"></i>Enable 2FA
          </button>
        </>
      ) : null}
    </Section>
  );
}

function Tokens({ data, timeZone }: { data: Data; timeZone: string }) {
  const { answer, pending, run } = useSecret();
  const [label, setLabel] = useState("");
  return (
    <Section title="Connect your own AI (MCP)">
      <p className="fs-13 text-muted">Connect Claude Desktop, Claude Code, or any MCP client to <strong>your</strong> memory. Each tool sees only what you can see. Add these as bearer-authenticated MCP servers:</p>
      <div className="mb-3">
        <div className="input-group input-group-sm mb-1"><span className="input-group-text">Records</span><input className="form-control" readOnly value={data.mcp.records_url} /></div>
        <div className="input-group input-group-sm"><span className="input-group-text">Activity</span><input className="form-control" readOnly value={data.mcp.activity_url} /></div>
      </div>
      {answer?.status === "error" && <div className="alert alert-danger py-2">{answer.message}</div>}
      {answer?.status === "ok" && answer.token && (
        <div className="alert alert-success"><strong>New token (copy it now — shown once):</strong><br /><code className="user-select-all">{answer.token}</code></div>
      )}
      <form className="mb-3" onSubmit={(e) => { e.preventDefault(); run("createToken", { label }); setLabel(""); }}>
        <div className="input-group">
          <input type="text" name="label" className="form-control" placeholder="Label (e.g. Claude Desktop on my laptop)" required
                 value={label} onChange={(e) => setLabel(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={pending}><i className="feather-plus me-1"></i>Create token</button>
        </div>
      </form>
      <div className="table-responsive">
        <table className="table table-hover mb-0">
          <thead className="thead-light"><tr><th>Label</th><th>Last used</th><th>Created</th><th className="text-end"></th></tr></thead>
          <tbody>
            {data.tokens.length === 0 ? (
              <tr><td colSpan={4} className="text-muted text-center py-3">No tokens yet.</td></tr>
            ) : data.tokens.map((t) => (
              <tr id={`mcp-token-${t.id}`} key={t.id}>
                <td>{t.label}</td>
                <td>{t.last_used_at ? formatDate(t.last_used_at, timeZone) : <small className="text-muted">never</small>}</td>
                <td>{t.created_at ? formatDate(t.created_at, timeZone) : dateOnly(t.created_at)}</td>
                <td className="text-end">
                  {/* HTMX posted this button with hx-vals; here it is a one-button form. */}
                  <ActionForm path="/settings/tokens/revoke.php" confirm="Revoke this token? Clients using it stop working.">
                    <input type="hidden" name="id" value={t.id} />
                    <SubmitButton className="btn btn-sm btn-outline-danger">Revoke</SubmitButton>
                  </ActionForm>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

/**
 * Settings → Desks (db/187, docs/build-specs/desk-enrolment.md): the person's enrolled MaluOS desktops, with
 * presence, and "Enrol a desk", which mints a ONE-TIME code shown here and nowhere else (settingsSecret, like a
 * new token). The desk runs `sudo maluctl office enroll <url> --code <code>` within fifteen minutes. Retiring a
 * desk is the estate's own action (locations/retire.php: the desk's owner may).
 */
function Desks({ data, timeZone }: { data: Data; timeZone: string }) {
  const [answer, setAnswer] = useState<SecretAnswer | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("desk");
  const [pending, startTransition] = useTransition();
  const presence = (p: string) => p === "online" ? <span className="badge bg-success">online</span>
    : p === "offline" ? <span className="badge bg-secondary">offline</span> : <span className="badge bg-light text-dark">unknown</span>;
  const made = answer?.status === "ok" ? answer : null;
  const officeUrl = made?.enrollUrl || data.mcp.records_url.replace(/\/mcp\/records$/, "/");
  const isNode = (made?.kind ?? "desk") !== "desk";
  return (
    <Section title={data.estate ? "Desks and the estate" : "Desks"}>
      <p className="text-muted small">
        A desk is a MaluOS desktop enrolled as yours: it shows in Work Locations with its presence, reads records and activity as you, and
        its agents reach this office through your desk token. Make a code here, then on the desktop run the command it shows.
        {data.estate && <> As an operator you also mint a <strong>node code</strong> for a MaluOS server or inference host (db/188): it joins the estate and reports to you here.</>}
      </p>
      {answer?.status === "error" && <div className="alert alert-danger py-2">{answer.message}</div>}
      {answer?.status === "ok" && answer.code && (
        <div className="alert alert-success">
          <strong>{isNode ? "Node code" : "Enrolment code"} (shown once; valid 15 minutes):</strong> <code className="user-select-all">{answer.code}</code><br />
          <small>{isNode ? "On the server" : "On the desktop"}: <code className="user-select-all">{isNode
            ? `sudo maluctl estate join ${officeUrl} --code ${answer.code} --kind ${made?.kind}`
            : `sudo maluctl office enroll ${officeUrl} --code ${answer.code}`}</code></small>
        </div>
      )}
      <form className="mb-3" onSubmit={(e) => { e.preventDefault(); startTransition(async () => { setAnswer(await settingsSecret("deskCode", { name, kind })); setName(""); }); }}>
        <div className="input-group">
          {data.estate && (
            <select name="kind" className="form-select flex-grow-0 w-auto" value={kind} onChange={(e) => setKind(e.target.value)} id="desk-code-kind">
              <option value="desk">A desk of mine</option>
              <option value="server">A server node</option>
              <option value="inference">An inference node</option>
            </select>
          )}
          <input type="text" name="name" className="form-control" placeholder={kind === "desk" ? "Desk name (optional, e.g. Ed's laptop)" : "Node name (optional; the hostname otherwise)"}
                 value={name} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={pending}><i className="feather-plus me-1"></i>{kind === "desk" ? "Enrol a desk" : "Make a node code"}</button>
        </div>
      </form>
      <div className="table-responsive">
        <table className="table table-hover mb-0">
          <thead className="thead-light"><tr><th>Desk</th><th>Presence</th><th>Last seen</th><th>Machine</th><th className="text-end"></th></tr></thead>
          <tbody>
            {data.desks.length === 0 ? (
              <tr><td colSpan={5} className="text-muted text-center py-3">No desks yet.</td></tr>
            ) : data.desks.map((d) => (
              <tr id={`desk-${d.id}`} key={d.id}>
                <td><Link href={`/locations/${d.id}`}>{d.name}</Link></td>
                <td>{presence(d.presence)}</td>
                <td>{d.last_seen_at ? formatDate(d.last_seen_at, timeZone) : <small className="text-muted">never</small>}</td>
                <td><small className="text-muted">{[d.hostname, d.os, d.app_version].filter(Boolean).join(" · ") || "—"}</small></td>
                <td className="text-end">
                  <ActionForm path="/locations/retire.php" confirm="Retire this desk? Its token stops working and it leaves Work Locations.">
                    <input type="hidden" name="location" value={d.id} />
                    <SubmitButton className="btn btn-sm btn-outline-danger">Retire</SubmitButton>
                  </ActionForm>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.estate && <Estate estate={data.estate} timeZone={timeZone} />}
    </Section>
  );
}

/**
 * The estate for an operator (db/188; maluos docs/phase13-slice1-nodes.md): every server and inference node with
 * the health the kernel computed from its last report, and the open alerts. Read-only here; the node's own row in
 * Work Locations has the rest, and the Desk's Estate view on a MaluOS desktop shows the same answer live.
 */
function Estate({ estate, timeZone }: { estate: NonNullable<Data["estate"]>; timeZone: string }) {
  const health = (h: string) => h === "ok" ? <span className="badge bg-success">ok</span>
    : h === "warning" ? <span className="badge bg-warning text-dark">warning</span>
    : h === "critical" ? <span className="badge bg-danger">critical</span>
    : <span className="badge bg-secondary">{h}</span>;
  return (
    <div className="mt-4" id="settings-estate">
      <h6 className="fw-bold">The estate</h6>
      {estate.overlay && (
        <p className="text-muted small" id="settings-estate-overlay">
          {/* db/189: the estate's own network (maluos docs/phase13-slice1b-overlay.md) */}
          Overlay network {estate.overlay.range}{estate.overlay.hub
            ? <>, hub <Link href={`/locations/${estate.overlay.hub.id}`}>{estate.overlay.hub.name}</Link> at {estate.overlay.hub.endpoint} ({estate.overlay.hub.address}), {estate.overlay.members} member{estate.overlay.members === 1 ? "" : "s"} with an address.</>
            : <>: no hub yet — join the coordinator&apos;s own host with <code>sudo maluctl estate join … --hub HOST:51820</code> and every member gets its tunnel.</>}
        </p>
      )}
      <div className="table-responsive">
        <table className="table table-hover mb-3">
          <thead className="thead-light"><tr><th>Node</th><th>Kind</th><th>Health</th><th>Summary</th><th>Units</th><th>Agents</th><th>Disk</th><th>Overlay</th><th>Last report</th></tr></thead>
          <tbody>
            {estate.nodes.length === 0 ? (
              <tr><td colSpan={9} className="text-muted text-center py-3">No nodes yet. Make a node code above and run the command it shows on the server.</td></tr>
            ) : estate.nodes.map((n) => (
              <tr id={`node-${n.id}`} key={n.id}>
                <td><Link href={`/locations/${n.id}`}>{n.name}</Link>{n.hostname && n.hostname !== n.name && <small className="text-muted"> · {n.hostname}</small>}</td>
                <td>{n.kind}</td>
                <td>{health(n.health)}</td>
                <td><small>{n.summary}</small></td>
                <td><small>{n.units.up} up{n.units.down > 0 && <span className="text-danger">, {n.units.down} down</span>}</small></td>
                <td><small>{n.agents.running}/{n.agents.count}{n.agents.failed > 0 && <span className="text-danger">, {n.agents.failed} failed</span>}</small></td>
                <td><small>{n.disk_max_pct !== null ? `${n.disk_max_pct} %` : "—"}</small></td>
                <td><small>{n.overlay ? n.overlay.address : "—"}</small></td>
                <td>{n.last_report_at ? formatDate(n.last_report_at, timeZone) : <small className="text-muted">never</small>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {estate.delegation && <Delegation d={estate.delegation} timeZone={timeZone} />}
      {estate.inference && <Inference inf={estate.inference} nodes={estate.nodes} timeZone={timeZone} />}
      {estate.alerts.length > 0 && (
        <>
          <h6 className="fw-bold">Open alerts</h6>
          <ul className="list-unstyled mb-0" id="settings-estate-alerts">
            {estate.alerts.map((a) => (
              <li key={a.id} className="mb-1">
                <span className={`badge ${a.severity === "critical" ? "bg-danger" : "bg-warning text-dark"} me-2`}>{a.severity}</span>
                <strong>{a.node}</strong>: {a.title} <small className="text-muted">{a.ts ? `since ${formatDate(a.ts, timeZone)}` : ""}</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * db/190, Phase 13 slice 2 (maluos docs/phase13-slice2-delegation.md): the estate's agent directory (what every node
 * registered, by capability and accept policy), the last tasks sent across the estate with their provenance, and the
 * actions a system manager ran on remote nodes. The Agents app on a desk is the working surface; this is the record.
 */
function Delegation({ d, timeZone }: { d: NonNullable<NonNullable<Data["estate"]>["delegation"]>; timeZone: string }) {
  const state = (s: string) => s === "completed" ? <span className="badge bg-success">completed</span>
    : s === "queued" || s === "running" ? <span className="badge bg-info text-dark">{s}</span>
    : s === "pending_approval" ? <span className="badge bg-warning text-dark">waiting for a person</span>
    : <span className="badge bg-danger">{s}</span>;
  return (
    <div className="mb-3" id="settings-estate-delegation">
      <h6 className="fw-bold">Agents across the estate</h6>
      <p className="text-muted small">Every node registers its agents by what they can do; a task sent to one carries a signed envelope, and the node that hosts the agent decides on its own whether to accept it. The coordinator signs as <code>{d.coordinator_key.split(" ").slice(0, 2).join(" ").slice(0, 40)}…</code>.</p>
      <div className="table-responsive">
        <table className="table table-sm table-hover mb-3" id="settings-estate-agents">
          <thead className="thead-light"><tr><th>Agent</th><th>Node</th><th>Capabilities</th><th>Accepts from</th><th>Ceiling</th><th>Presence</th><th>Owner</th></tr></thead>
          <tbody>
            {d.agents.length === 0 ? (
              <tr><td colSpan={7} className="text-muted text-center py-3">No agents registered yet. A node lists its agents with its first report after <code>maluctl agent create</code>.</td></tr>
            ) : d.agents.map((a) => (
              <tr id={`estate-agent-${a.id}`} key={a.id}>
                <td><strong>{a.display_name || a.name}</strong>{a.display_name && a.display_name !== a.name && <small className="text-muted"> · {a.name}</small>}{a.hired && <span className="badge bg-light text-dark ms-1">Agent HR</span>}</td>
                <td>{a.node.id !== null ? <Link href={`/locations/${a.node.id}`}>{a.node.name}</Link> : <span>coordinator</span>}</td>
                <td><small>{a.capabilities.join(", ") || "—"}</small></td>
                <td><small>{a.accept_from.length ? a.accept_from.join(", ") : "its owner only"}</small></td>
                <td><small>{a.max_classification ?? "—"}</small></td>
                <td>{a.presence === "online" ? <span className="badge bg-success">online</span> : <span className="badge bg-secondary">{a.state === "failed" ? "failed" : a.presence}</span>}</td>
                <td><small>{a.owner ?? "—"}</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.tasks.length > 0 && (
        <>
          <h6 className="fw-bold">Last tasks</h6>
          <div className="table-responsive">
            <table className="table table-sm table-hover mb-3" id="settings-estate-tasks">
              <thead className="thead-light"><tr><th>When</th><th>Task</th><th>Agent</th><th>From</th><th>State</th><th>Models</th><th>Envelope</th></tr></thead>
              <tbody>
                {d.tasks.map((t) => (
                  <tr key={t.id}>
                    <td><small>{t.ts ? formatDate(t.ts, timeZone) : ""}</small></td>
                    <td><small>{t.text}</small></td>
                    <td><small>{t.agent} on {t.node_name}</small></td>
                    <td><small>{t.originator}{t.sender.principal !== t.originator && ` via ${t.sender.principal}`}</small></td>
                    <td>{state(t.state)}{t.reason && <small className="text-muted"> {t.reason}</small>}</td>
                    <td><small>{t.models}{t.usd !== null && t.usd > 0 ? ` · $${t.usd.toFixed(4)}` : ""}</small></td>
                    <td><small className="text-muted">{t.envelope_id.slice(0, 12)}…{t.hop > 1 ? ` hop ${t.hop}` : ""}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {d.actions.length > 0 && (
        <>
          <h6 className="fw-bold">Actions on nodes</h6>
          <ul className="list-unstyled mb-3" id="settings-estate-actions">
            {d.actions.map((a) => (
              <li key={a.id} className="mb-1">
                {state(a.state)} <strong>{a.action}{a.agent ? ` ${a.agent}` : ""}</strong> on {a.node.name ?? a.node.id}
                <small className="text-muted"> {a.created_at ? formatDate(a.created_at, timeZone) : ""}{a.reason ? ` · ${a.reason}` : ""}</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * db/191, Phase 13 slice 3 (maluos docs/phase13-slice3-inference.md): shared inference across the estate. Every
 * member's gateway reports what it serves with its heartbeat; the shared ones with an overlay address are published
 * to the members the policy allows, who dial them over the overlay with their own inference key. The rules say who
 * may use what (the most specific subject wins, a deny beats an allow; a desk's GPU is never used by other desks);
 * the scheduler entitlement turns on estate-wide placement.
 */
function Inference({ inf, nodes, timeZone }: { inf: NonNullable<NonNullable<Data["estate"]>["inference"]>; nodes: NonNullable<Data["estate"]>["nodes"]; timeZone: string }) {
  const wait = (w: Record<string, number>) => Object.entries(w).map(([c, s]) => `${c} ${s}s`).join(", ") || "—";
  return (
    <div className="mb-3" id="settings-estate-inference">
      <h6 className="fw-bold">Shared inference</h6>
      <p className="text-muted small">
        A GPU host that joins the estate is a backend of every member the policy allows, reached over the overlay with the member&apos;s own inference key; nothing is paired by hand.
        {" "}{inf.members_with_keys} member{inf.members_with_keys === 1 ? "" : "s"} hold{inf.members_with_keys === 1 ? "s" : ""} a key; {inf.queue.backends} backend{inf.queue.backends === 1 ? "" : "s"} published, {inf.queue.queued} queued and {inf.queue.running} running across the estate.
      </p>
      <ActionForm path="/settings/desks/inference.php" className="mb-3" id="settings-estate-scheduler">
        <input type="hidden" name="op" value="scheduler" />
        <input type="hidden" name="on" value={inf.scheduler ? "0" : "1"} />
        <span className={`badge ${inf.scheduler ? "bg-success" : "bg-secondary"} me-2`}>scheduler {inf.scheduler ? "on" : "off"}</span>
        <small className="text-muted me-2">{inf.scheduler ? `Estate-wide placement answers every gateway's place request with a ${inf.lease_s} s lease.` : "Each gateway ranks the estate's backends by its own expected wait; placement, priorities and backpressure need the scheduler entitlement."}</small>
        <SubmitButton className="btn btn-sm btn-outline-secondary">{inf.scheduler ? "Turn off" : "Turn on"}</SubmitButton>
      </ActionForm>
      <div className="table-responsive">
        <table className="table table-sm table-hover mb-3" id="settings-estate-backends">
          <thead className="thead-light"><tr><th>Host</th><th>Kind</th><th>Published</th><th>Models</th><th>Queue</th><th>Expected wait</th><th>Sharing</th><th>Updated</th></tr></thead>
          <tbody>
            {inf.backends.length === 0 ? (
              <tr><td colSpan={8} className="text-muted text-center py-3">No gateway has reported yet. A member&apos;s heartbeat carries what its gateway serves once it runs maluos-gateway 0.6.0 or later.</td></tr>
            ) : inf.backends.map((b) => (
              <tr id={`estate-backend-${b.id}`} key={b.id}>
                <td><Link href={`/locations/${b.id}`}>{b.display_name}</Link><small className="text-muted"> · {b.name}.internal{b.address ? ` (${b.address}:${b.port})` : ""}</small></td>
                <td>{b.kind}</td>
                <td>{b.published ? <span className="badge bg-success">yes</span> : <span className="badge bg-secondary">{b.why ?? "no"}</span>}</td>
                <td><small>{b.models.map((m) => m.loaded ? <strong key={m.name}>{m.name} </strong> : <span key={m.name}>{m.name} </span>)}{b.models.length === 0 && "—"}</small></td>
                <td><small>{b.queue.queued} queued, {b.queue.running} running</small></td>
                <td><small>{wait(b.expected_wait_s)}</small></td>
                <td><small>{b.share ? `on, ${b.contribution}` : "off"}</small></td>
                <td>{b.updated_at ? formatDate(b.updated_at, timeZone) : <small className="text-muted">never</small>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h6 className="fw-bold">Who may use what</h6>
      <p className="text-muted small">Without a rule every active member may use every shared backend at an internal ceiling. The most specific subject wins (a node over a department over a kind over the organisation), a rule naming one backend beats one for any, and a deny beats an allow. A desk&apos;s contribution is never used by other desks.</p>
      {inf.rules.length > 0 && (
        <ul className="list-unstyled mb-3" id="settings-estate-inference-rules">
          {inf.rules.map((r) => (
            <li key={r.id} className="mb-1 d-flex align-items-center">
              <span className={`badge ${r.allow ? "bg-success" : "bg-danger"} me-2`}>{r.allow ? "allow" : "deny"}</span>
              <span><strong>{r.subject}</strong> → {r.backend_name ?? "any backend"}
                <small className="text-muted">{r.max_class ? ` · class ≤ ${r.max_class}` : ""}{r.max_classification ? ` · classification ≤ ${r.max_classification}` : ""}{r.priority !== 0 ? ` · priority ${r.priority}` : ""}{r.note ? ` · ${r.note}` : ""}</small>
              </span>
              <ActionForm path="/settings/desks/inference.php" className="ms-2" confirm="Remove this rule?">
                <input type="hidden" name="op" value="rule_delete" />
                <input type="hidden" name="id" value={r.id} />
                <SubmitButton className="btn btn-sm btn-link text-danger p-0">remove</SubmitButton>
              </ActionForm>
            </li>
          ))}
        </ul>
      )}
      <ActionForm path="/settings/desks/inference.php" className="row g-2 align-items-end mb-3" id="settings-estate-inference-rule-add" resetOnSuccess>
        <input type="hidden" name="op" value="rule_add" />
        <div className="col-6 col-md-2"><label className="form-label small mb-0">Subject</label><input className="form-control form-control-sm" name="subject" defaultValue="org" placeholder="org, dept:3, kind:desk, node:57" /></div>
        <div className="col-6 col-md-2"><label className="form-label small mb-0">Backend</label>
          <select className="form-select form-select-sm" name="backend_location_id" defaultValue=""><option value="">any</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></div>
        <div className="col-4 col-md-1"><label className="form-label small mb-0">Allow</label><select className="form-select form-select-sm" name="allow" defaultValue="1"><option value="1">allow</option><option value="0">deny</option></select></div>
        <div className="col-4 col-md-2"><label className="form-label small mb-0">Class ≤</label><select className="form-select form-select-sm" name="max_class" defaultValue=""><option value="">host default</option><option value="interactive">interactive</option><option value="agent">agent</option><option value="batch">batch</option></select></div>
        <div className="col-4 col-md-2"><label className="form-label small mb-0">Classification ≤</label><select className="form-select form-select-sm" name="max_classification" defaultValue=""><option value="">internal</option><option value="public">public</option><option value="internal">internal</option><option value="restricted">restricted</option><option value="prohibited">prohibited</option></select></div>
        <div className="col-4 col-md-1"><label className="form-label small mb-0">Priority</label><input className="form-control form-control-sm" name="priority" type="number" defaultValue="0" /></div>
        <div className="col-8 col-md-2"><label className="form-label small mb-0">Note</label><input className="form-control form-control-sm" name="note" /></div>
        <div className="col-12 col-md-12"><SubmitButton className="btn btn-sm btn-outline-primary">Add rule</SubmitButton></div>
      </ActionForm>
    </div>
  );
}
