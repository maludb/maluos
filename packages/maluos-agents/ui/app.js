// Agents app UI (Phase 12 slice 8). Everything comes through the native bridge: window.maluos.call(method, params)
// posts a JSON-RPC request to the WebKit message handler; the native side answers with window.maluos._reply and
// pushes state with window.maluos._event({type: "state"}).
"use strict";
const VERSION = "0.3.0";
const pending = new Map();
let seq = 0;
window.maluos = {
  call(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, {resolve, reject});
      try { window.webkit.messageHandlers.maluos.postMessage(JSON.stringify({id, method, params: params || {}})); }
      catch (e) { pending.delete(id); reject(new Error("no native side: " + e)); }
    });
  },
  _reply(res) {
    const p = pending.get(res.id); if (!p) return; pending.delete(res.id);
    if (res.error !== undefined) p.reject(new Error(res.error)); else p.resolve(res.result);
  },
  _event(ev) { if (ev.type === "state") setState(ev.data); },
};
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const when = (ts) => { if (!ts) return ""; const d = new Date(ts); return isNaN(d) ? String(ts).slice(0, 19) : d.toLocaleString(); };
const toast = (text) => { try { window.webkit.messageHandlers.maluos.postMessage(JSON.stringify({method: "toast", params: {text}})); } catch (e) {} };

let state = {agents: [], office: {enrolled: false}, service: false, selected: null};
let selected = null;
let page = "talk";
const chats = {};         // agent id -> [{who, text, ts, working}]
const loaded = {};        // agent id -> {policy, memory, activity, logs, card}
const working = {};       // agent id -> task id being polled (slice 9: streaming answers)

function setState(s) {
  state = s;
  if (!selected && s.selected) selected = s.selected;
  if (selected && selected !== "inbox:" && !s.agents.some((a) => a.id === selected)) selected = null;
  renderList(); renderDetail();
}

function agent() { return state.agents.find((a) => a.id === selected); }

function renderList() {
  const list = $("#list"); list.innerHTML = "";
  const local = state.agents.filter((a) => a.kind === "local"), office = state.agents.filter((a) => a.kind === "office");
  const host = state.host || {};
  $("#side-sub").textContent = host.hostname ? `on ${host.hostname}` : "";
  const groups = [["This desk", local, state.service ? "No agents on this desk. sudo maluctl agent create NAME --exec CMD" : "The session service is not reachable."]];
  if (state.office.enrolled) groups.push([state.office.name || "The office", office, state.office.agents_error || "The office lists no agents for this desk."]);
  if (state.office.enrolled) {
    // Phase 13 slice 2: the person's estate inbox (questions, decisions, results from agents anywhere in the estate)
    const g = document.createElement("div"); g.className = "group"; g.textContent = "You"; list.appendChild(g);
    const ib = state.office.inbox || {};
    const el = document.createElement("div"); el.className = "item" + (selected === "inbox:" ? " active" : ""); el.dataset.id = "inbox:";
    el.innerHTML = `<span class="dot ${ib.unread ? "on" : ""}"></span><span class="t"><span class="n">Inbox</span><br><span class="s muted">${esc(ib.unread ? ib.unread + " unread" : "nothing waiting")}</span></span>`;
    el.onclick = () => { selected = "inbox:"; renderList(); renderDetail(); };
    list.appendChild(el);
    if (!local.some((a) => (a.capabilities || []).includes("personal"))) {
      const mk = document.createElement("div"); mk.className = "item muted"; mk.innerHTML = `<span class="t"><button id="make-personal">Make my personal agent</button></span>`;
      list.appendChild(mk);
      mk.querySelector("button").onclick = () => window.maluos.call("personal_create", {}).then((r) => toast(r.message || "your personal agent is being made")).catch((e) => toast(e.message));
    }
  }
  for (const [title, items, emptyText] of groups) {
    const g = document.createElement("div"); g.className = "group"; g.textContent = title; list.appendChild(g);
    if (!items.length) { const e = document.createElement("div"); e.className = "item muted"; e.textContent = emptyText; list.appendChild(e); continue; }
    for (const a of items) {
      const el = document.createElement("div"); el.className = "item" + (a.id === selected ? " active" : ""); el.dataset.id = a.id;
      const on = a.kind === "local" ? a.active === "active" : a.presence === "online";
      const dotCls = a.kind === "local" && a.active === "failed" ? "failed" : on ? "on" : "";
      const sub = a.kind === "local" ? `${a.active}${a.mine ? " · yours" : a.owner ? " · " + a.owner : ""}${a.tasks ? " · accepts tasks" : ""}${a.capabilities.length ? " · " + a.capabilities.join(", ") : ""}`
                                     : `${a.presence}${a.node ? " · on " + a.node : ""}${a.state && a.state !== "idle" ? " · " + a.state : ""}${a.capabilities.length ? " · " + a.capabilities.join(", ") : ""}`;
      el.innerHTML = `<span class="dot ${dotCls}"></span><span class="t"><span class="n">${esc(a.name)}</span><br><span class="s muted">${esc(sub)}</span></span>`;
      el.onclick = () => { selected = a.id; page = page || "talk"; window.maluos.call("select", {id: a.id}).catch(() => {}); renderList(); renderDetail(); };
      list.appendChild(el);
    }
  }
  $("#side-foot").textContent = `${local.length} on this desk` + (state.office.enrolled ? ` · ${office.length} at ${state.office.name || "the office"} (${state.office.presence || "?"})` : " · no office");
}

function renderDetail() {
  if (selected === "inbox:") return renderInbox();
  const a = agent();
  $("#empty").hidden = !!a; $("#detail").hidden = !a;
  if (!a) return;
  $("#name").textContent = a.name;
  $("#meta").textContent = a.kind === "local"
    ? `${a.principal} · ${a.unit} · ${a.active}${a.sub && a.sub !== "running" && a.sub !== "dead" ? " (" + a.sub + ")" : ""}${a.sandbox === "strict" ? " · strict sandbox" : ""}${a.owner ? " · owner " + a.owner : ""}`
    : `${a.principal} · at ${a.office || "the office"}${a.node ? " on " + a.node : ""} · ${a.presence}${a.state && a.state !== "idle" ? " · " + a.state : ""}${a.accept_from ? " · accepts " + (a.accept_from.length ? a.accept_from.join(", ") : "its owner only") : ""}`;
  const acts = $("#head-actions"); acts.innerHTML = "";
  if (a.kind === "local") {
    if (a.active === "active") { acts.appendChild(btn("Stop", () => act("stop"))); acts.appendChild(btn("Restart", () => act("restart"))); }
    else acts.appendChild(btn("Start", () => act("start"), "primary"));
  } else if (a.page) acts.appendChild(btn("Office page", () => window.maluos.call("open_page", {id: a.id}).catch((e) => toast(e.message))));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  ({talk: renderTalk, control: renderControl, policy: renderPolicy, memory: renderMemory, activity: renderActivity})[page]();
}

function btn(label, fn, cls) { const b = document.createElement("button"); b.textContent = label; if (cls) b.className = cls; b.onclick = fn; return b; }
function act(action) {
  const a = agent(); if (!a) return;
  window.maluos.call("agent_action", {id: a.id, action}).then(() => toast(`${a.name}: ${action}`)).catch((e) => toast(`${a.name}: ${action} failed: ${e.message}`));
}

// -- Talk
function renderTalk() {
  const a = agent(); const chat = $("#chat"); chat.innerHTML = "";
  const rows = chats[a.id] || [];
  if (!rows.length && !(loaded[a.id] || {}).tasksLoaded) {
    (loaded[a.id] = loaded[a.id] || {}).tasksLoaded = true;
    window.maluos.call("agent_tasks", {id: a.id, limit: 30}).then((r) => {
      const hist = [];
      for (const t of (r.tasks || []).slice().reverse()) {
        hist.push({who: "me", text: t.input.text, ts: t.ts});
        if (t.state === "completed") hist.push({who: "them", text: t.output.text, ts: t.done_ts, note: t.provenance ? `from ${(t.provenance.agent || "").replace(/^agent:/, "")} on ${t.provenance.node || "?"} · ${(t.provenance.models || []).length} model call(s)` : null});
        else if (t.state === "failed") hist.push({who: "err", text: t.error || "failed", ts: t.done_ts});
      }
      chats[a.id] = hist.concat(chats[a.id] || []); if (selected === a.id && page === "talk") renderTalk();
    }).catch(() => {});
  }
  for (const m of rows) {
    const el = document.createElement("div"); el.className = "msg " + m.who + (m.working ? " working" : "");
    el.innerHTML = esc(m.text) + (m.working ? `<span class="cursor">▌</span>` : "") + (m.note ? `<span class="prov">${esc(m.note)}</span>` : "") + (m.ts ? `<span class="when">${esc(when(m.ts))}</span>` : ""); chat.appendChild(el);
  }
  chat.scrollTop = chat.scrollHeight;
  const can = a.tasks;
  $("#send").disabled = !can; $("#text").disabled = !can;
  $("#talk-note").textContent = can
    ? (a.kind === "local" ? `Tasks go to ${a.name}'s socket on this desk; each answer is the agent's own work (its ledger rows show on Activity).`
                          : `Tasks go to ${a.office || "the office"} with this desk's token; the office's ${a.name} answers.`)
    : (a.kind === "local" ? (a.active === "active" ? "This agent serves no task interface (maluos_agent_tasks); only its logs and unit are here." : "Start the agent to talk to it.")
                          : "The office publishes no task interface for this agent.");
}
$("#compose").onsubmit = (ev) => {
  ev.preventDefault();
  const a = agent(); const text = $("#text").value.trim(); if (!a || !text) return;
  $("#text").value = "";
  (chats[a.id] = chats[a.id] || []).push({who: "me", text, ts: new Date().toISOString()}); renderTalk();
  $("#send").disabled = true;
  // Slice 9: the task comes back at once; the answer is drawn as it grows (tasks/get once a second while it works).
  const reply = {who: "them", text: "", ts: null, working: true};
  chats[a.id].push(reply);
  const settle = (t) => {
    reply.working = false; working[a.id] = null;
    if (t.state === "completed") {
      reply.text = t.output.text; reply.ts = t.done_ts;
      const p = t.provenance; const u = t.usage || {};
      if (p) reply.note = `from ${(p.agent || "").replace(/^agent:/, "") || a.name} on ${p.node || a.node || "?"} · ${(p.models || []).length} model call${(p.models || []).length === 1 ? "" : "s"}${u.usd ? " · $" + Number(u.usd).toFixed(4) : " · $0.00"} · envelope ${(p.envelope || "").slice(0, 16)}`;
    }
    else if (t.state === "pending_approval") { reply.who = "them"; reply.text = `waiting for an approval: ${(t.ask && t.ask.subject) || "the agent's owner must approve this task"}`; reply.ts = new Date().toISOString(); }
    else { reply.who = "err"; reply.text = `${t.state}: ${t.error || "no answer (tasks/get " + t.id + ")"}`; reply.ts = t.done_ts || new Date().toISOString(); }
    if (selected === a.id && page === "talk") renderTalk();
  };
  const poll = (tid) => {
    if (working[a.id] !== tid) return;
    window.maluos.call("agent_task", {id: a.id, task: tid}).then((t) => {
      if (t.state === "submitted" || t.state === "working" || t.state === "queued" || t.state === "running") {
        const txt = (t.output && t.output.text) || "";
        if (txt !== reply.text) { reply.text = txt; if (selected === a.id && page === "talk") renderTalk(); }
        setTimeout(() => poll(tid), 1000);
      } else settle(t);
    }).catch((e) => settle({state: "failed", error: e.message, id: tid}));
  };
  window.maluos.call("agent_send", {id: a.id, text}).then((t) => {
    if (t.state === "submitted" || t.state === "working" || t.state === "queued" || t.state === "running") { working[a.id] = t.id; reply.text = (t.output && t.output.text) || ""; if (selected === a.id && page === "talk") renderTalk(); setTimeout(() => poll(t.id), 700); }
    else settle(t);
  }).catch((e) => settle({state: "failed", error: e.message}));
};
$("#text").onkeydown = (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("#compose").requestSubmit(); } };

// -- Control
function renderControl() {
  const a = agent(); const cards = $("#control-cards"); cards.innerHTML = "";
  const card = (title, value, actions) => {
    const c = document.createElement("div"); c.className = "card"; c.innerHTML = `<h4>${esc(title)}</h4><div class="v">${value}</div>`;
    if (actions && actions.length) { const d = document.createElement("div"); d.className = "actions"; actions.forEach((b) => d.appendChild(b)); c.appendChild(d); }
    cards.appendChild(c);
  };
  if (a.kind === "local") {
    card("Unit", `${esc(a.unit)}<br><span class="muted">${esc(a.active)}${a.since ? " since " + esc(when(a.since)) : ""}</span>`,
         a.active === "active" ? [btn("Stop", () => act("stop")), btn("Restart", () => act("restart"))] : [btn("Start", () => act("start"), "primary")]);
    card("Command", `<code>${esc(a.exec || "/usr/lib/maluos/maluos-agent-idle")}</code>`, []);
    card("Run a one-off command as the agent", `<span class="muted">Its identity and environment, in a terminal (administrator).</span>`,
         [btn("Open terminal", () => window.maluos.call("open_terminal", {argv: ["sh", "-c", `echo 'maluctl agent run ${a.id.slice(6)} -- CMD...'; sudo maluctl agent run ${a.id.slice(6)} -- sh -i`]}).catch((e) => toast(e.message)))]);
    card("Task interface", a.tasks ? `<span class="muted">Serving on /run/maluos/agents/${esc(a.id.slice(6))}/tasks.sock</span>` : `<span class="muted">Not served by this agent.</span>`, []);
    $("#logs-refresh").disabled = false; $("#logs-terminal").disabled = false;
    if (!(loaded[a.id] || {}).logs) loadLogs(); else $("#logs").textContent = loaded[a.id].logs;
  } else {
    card("Where it runs", `${esc(a.office || "the office")}${a.node ? " · node " + esc(a.node) : ""}<br><span class="muted">${esc(a.presence)}${a.state ? " · " + esc(a.state) : ""}</span>`, []);
    card("Start, stop, restart", `<span class="muted">Operator actions on an office agent come with Phase 13 slice 2 (the delegation envelope); until then the office's own page has them.</span>`,
         a.page ? [btn("Office page", () => window.maluos.call("open_page", {id: a.id}).catch((e) => toast(e.message)))] : []);
    card("Capabilities", a.capabilities.length ? a.capabilities.map((c) => `<span class="chip">${esc(c)}</span>`).join("") : `<span class="muted">none declared</span>`, []);
    $("#logs").textContent = "An office agent's logs come with Phase 13 slice 2; its Activity page shows what the office publishes.";
    $("#logs-refresh").disabled = true; $("#logs-terminal").disabled = true;
  }
}
function loadLogs() {
  const a = agent(); if (!a || a.kind !== "local") return;
  $("#logs").textContent = "Reading the journal…";
  window.maluos.call("agent_logs", {id: a.id, lines: 300}).then((r) => { (loaded[a.id] = loaded[a.id] || {}).logs = r.text || "(no lines)"; if (selected === a.id) $("#logs").textContent = loaded[a.id].logs; })
    .catch((e) => { if (selected === a.id) $("#logs").textContent = e.message; });
}
$("#logs-refresh").onclick = loadLogs;
$("#logs-terminal").onclick = () => { const a = agent(); if (a && a.kind === "local") window.maluos.call("open_terminal", {argv: ["sh", "-c", `journalctl -f -u ${a.unit} || sudo journalctl -f -u ${a.unit}`]}).catch((e) => toast(e.message)); };

// -- Policy
function kv(pairs) { return `<dl class="kv">${pairs.filter(([k, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`; }
function renderPolicy() {
  const a = agent(); const el = $("#policy");
  el.innerHTML = `<p class="muted">Loading…</p>`;
  window.maluos.call("agent_policy", {id: a.id}).then((r) => {
    if (selected !== a.id) return;
    let html = "";
    if (a.kind === "local") {
      html += `<h3>Identity</h3>` + kv([["Principal", esc(a.principal)], ["Owner", esc(a.owner || "none (a system agent)")], ["Sandbox", esc(a.sandbox)], ["Unit", esc(a.unit)]]);
      html += `<h3>Delegations it holds</h3>`;
      html += r.delegations.length ? table(r.delegations.map((d) => [when(d.created_at || d.ts), d.secret || d.secret_name || "(all)", d.from || d.from_ref || "", d.expires_at ? when(d.expires_at) : "never"]), ["Since", "Secret", "From", "Expires"]) : `<p class="muted">None: the agent uses no secret of yours by delegation.</p>`;
      html += `<h3>Grants on your secrets</h3>`;
      html += r.grants.length ? table(r.grants.map((g) => [g.secret, g.level, g.expires_at ? when(g.expires_at) : "never"]), ["Secret", "Level", "Expires"]) : `<p class="muted">None.</p>`;
      const pol = r.policy || {}; const mf = r.manifest || {};
      html += `<h3>Who may task it</h3>` + kv([["Capabilities", (mf.capabilities || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("") || "none declared"],
                                                ["Accepts from", (pol.accept_from || []).length ? esc(pol.accept_from.join(", ")) : "its owner only"],
                                                ["Classification ceiling", esc(pol.max_classification || "none")], ["Waits for your approval", (pol.approve || []).length ? esc(pol.approve.join(", ")) : "nothing"]]);
      html += `<form id="policy-form" class="policy-form"><label>Accepts from <input name="accept_from" value="${esc((pol.accept_from || []).join(","))}" placeholder="org, dept:3, user:ed, agent:helper, node:desk"></label>`
            + `<label>Ceiling <select name="max_classification">${["", "public", "internal", "restricted", "prohibited"].map((c) => `<option value="${c}"${(pol.max_classification || "") === c ? " selected" : ""}>${c || "none"}</option>`).join("")}</select></label>`
            + `<label>Approve <input name="approve" value="${esc((pol.approve || []).join(","))}" placeholder="restricted, user:stranger"></label><button type="submit">Save (administrator)</button></form>`;
      html += `<h3>Model policy</h3><p class="muted">Class, tiers, backends, cloud, egress and budget are set by an administrator (maluctl agent create, maluctl gateway policy); reading them needs the administrator's password.</p>`;
      html += `<div class="actions"><button id="policy-admin">Show the full policy (administrator)</button></div>`;
    } else {
      const c = r.card || {};
      html += `<h3>Card</h3>` + kv([["Name", esc(c.name || a.name)], ["Description", esc(c.description || a.description)], ["Principal", esc(c.principal || a.principal)],
                                   ["Owner", esc(c.owner || a.owner || "the office")], ["Node", esc(a.node)], ["Protocol", esc(c.protocol)],
                                   ["Capabilities", (c.capabilities || a.capabilities || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("") || "none declared"]]);
      html += `<h3>Who may task it</h3>` + kv([["Accepts from", a.accept_from ? (a.accept_from.length ? esc(a.accept_from.join(", ")) : "its owner only") : "the office decides"], ["Classification ceiling", esc(a.max_classification || "none")],
                                                ["Node", esc(a.node || "the office")], ["Hired by the office", a.hired ? "yes (Agent HR)" : "no"]]);
      html += `<p class="muted">The policy is the agent's owner's, set on its host (maluctl agent policy); the office's Agent HR holds its class, tiers, backends, budget and scopes once it is hired.</p>`;
    }
    if (r.note) html += `<p class="muted">${esc(r.note)}</p>`;
    el.innerHTML = html;
    const f = $("#policy-form"); if (f) f.onsubmit = (ev) => { ev.preventDefault(); const d = new FormData(f);
      window.maluos.call("policy_set", {id: a.id, accept_from: d.get("accept_from"), max_classification: d.get("max_classification"), approve: d.get("approve")}).then(() => { toast(`${a.name}: policy saved`); renderPolicy(); }).catch((e) => toast(e.message)); };
    const b = $("#policy-admin"); if (b) b.onclick = () => window.maluos.call("open_terminal", {argv: ["sh", "-c", `${r.admin_hint}; echo; read -p 'Enter closes this window' _`]}).catch((e) => toast(e.message));
  }).catch((e) => { if (selected === a.id) el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
}
function table(rows, head) {
  return `<table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i === 0 ? "ts" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

// -- Memory
function renderMemory() {
  const a = agent(); const el = $("#memory"); el.innerHTML = `<p class="muted">Loading…</p>`;
  window.maluos.call("agent_memory", {id: a.id}).then((r) => {
    if (selected !== a.id) return;
    let html = `<h3>Compartments</h3>`;
    html += r.compartments.length ? table(r.compartments.map((c) => [c.name, c.owner || c.owner_ref || "", c.scope || "", c.locked ? "locked" : "open", c.secret_count ?? c.secrets ?? ""]), ["Name", "Owner", "Scope", "State", "Secrets"])
                                  : `<p class="muted">${a.kind === "local" ? "No compartment of this agent is visible to you." : "An office agent's compartment lives at the office."}</p>`;
    html += `<h3>Claims</h3><p class="muted">${esc(r.claims_note || "")}</p>`;
    if (r.note) html += `<p class="muted">${esc(r.note)}</p>`;
    el.innerHTML = html;
  }).catch((e) => { if (selected === a.id) el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
}

// -- Activity
function renderActivity() {
  const a = agent(); const el = $("#activity"); el.innerHTML = `<p class="muted">Loading…</p>`;
  window.maluos.call("agent_activity", {id: a.id, limit: 60}).then((r) => {
    if (selected !== a.id) return;
    const rows = r.activity || [];
    el.innerHTML = (rows.length ? table(rows.map((x) => [when(x.ts), x.kind, x.actor, x.summary]), ["When", "Kind", "Actor", "What"]) : `<p class="muted">Nothing yet.</p>`)
      + `<p class="note muted">Source: ${esc(r.source || "")}</p>`;
  }).catch((e) => { if (selected === a.id) el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
}
$("#activity-refresh").onclick = renderActivity;

document.querySelectorAll(".tab").forEach((t) => t.onclick = () => { page = t.dataset.page; renderDetail(); });

// -- timers (slice 9): the Control and Activity pages re-read while they are visible; logs every 5 s while the unit is active
let tick = 0;
setInterval(() => {
  tick += 5;
  const a = agent(); if (!a || document.hidden) return;
  if (page === "control" && a.kind === "local" && a.active === "active") loadLogs();
  if (tick % 30 === 0) {
    if (page === "activity") renderActivity();
    else if (page === "control") renderControl();
  }
}, 5000);

// -- start
try { window.webkit.messageHandlers.maluos.postMessage(JSON.stringify({method: "ready", params: {version: VERSION}})); }
catch (e) { $("#side-foot").textContent = "No native side (open this page with maluos-agents)."; }


// -- Inbox (Phase 13 slice 2): the person's estate inbox — questions, decisions, results and notes from agents anywhere
function renderInbox() {
  $("#empty").hidden = true; $("#detail").hidden = false;
  $("#name").textContent = "Inbox"; $("#meta").textContent = "what agents in the estate ask or tell you; a decision or a reply goes back signed by this desk";
  $("#head-actions").innerHTML = "";
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", false));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-policy"));
  const el = $("#policy"); el.innerHTML = `<p class="muted">Loading…</p>`;
  window.maluos.call("inbox", {all: true}).then((r) => {
    if (selected !== "inbox:") return;
    const items = r.items || [];
    if (!items.length) { el.innerHTML = `<p class="muted">Nothing in your inbox.</p>`; return; }
    let html = "";
    for (const i of items) {
      const from = `${(i.from || {}).principal || "?"} on ${(i.from || {}).node || "?"}`;
      html += `<div class="inbox-item ${i.status}"><div class="ih"><span class="chip">${esc(i.kind.replace("_", " "))}</span> <strong>${esc(i.subject)}</strong> <span class="muted">${esc(from)} · ${esc(when(i.created_at))}</span></div>`;
      if (i.body) html += `<div class="ib">${esc(i.body)}</div>`;
      if (i.status === "done") html += `<div class="muted">${esc(i.decision ? "you decided: " + i.decision + (i.decision_note ? " — " + i.decision_note : "") : i.reply ? "you replied: " + i.reply : "done")}</div>`;
      else if (i.kind === "decision_needed") html += `<div class="actions">${(i.options || ["approve", "deny"]).map((o) => `<button data-decide="${esc(o)}" data-id="${i.id}">${esc(o)}</button>`).join(" ")}</div>`;
      else if (i.kind === "question") html += `<form class="reply" data-id="${i.id}"><input name="text" placeholder="your reply"><button type="submit">Reply</button></form>`;
      else html += `<div class="actions"><button data-read="${i.id}">Mark read</button></div>`;
      html += `</div>`;
    }
    el.innerHTML = html;
    el.querySelectorAll("button[data-decide]").forEach((b) => b.onclick = () => window.maluos.call("inbox_decide", {id: Number(b.dataset.id), decision: b.dataset.decide}).then(() => renderInbox()).catch((e) => toast(e.message)));
    el.querySelectorAll("button[data-read]").forEach((b) => b.onclick = () => window.maluos.call("inbox_read", {id: Number(b.dataset.read)}).then(() => renderInbox()).catch((e) => toast(e.message)));
    el.querySelectorAll("form.reply").forEach((f) => f.onsubmit = (ev) => { ev.preventDefault(); const t = new FormData(f).get("text");
      window.maluos.call("inbox_reply", {id: Number(f.dataset.id), text: t}).then(() => renderInbox()).catch((e) => toast(e.message)); });
  }).catch((e) => { if (selected === "inbox:") el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
}
