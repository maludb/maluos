"""A mock Business OS office for tests: the desk contract, surface 1 (docs/desk-enrolment.md),
an OpenAI-wire model endpoint beneath /desk-models, records/activity/memory MCP stubs, the estate
contract for nodes (docs/phase13-slice1-nodes.md: join, heartbeat with the report, the health rules
and the alerts the kernel will compute, the presence sweep) and inspection hooks. Stdlib only;
deterministic replies. Lives in maluos-estate; maluos_desk.mock_office is the same module.

  python3 -m maluos_estate.mock_office --port 18080 --code CODE [--code CODE2] [--node-code CODE] [--name "Mock Office"]
                                        [--models office-7b,office-embed] [--heartbeat-s 300] [--node-heartbeat-s 60] [--report-s 300]

  POST /api/v1/estate/join                 a server or inference node joins with a node code (a desk code is refused)
  POST /api/v1/estate/heartbeat            presence, facts and (every report_s) the report; the health rules run on it
  GET  /api/v1/estate/me, POST /api/v1/estate/leave          (Bearer node token)
  GET  /api/v1/estate/nodes[/ID]           the estate: nodes with health and the open alerts (node or desk token)
  GET  /api/v1/desks/estate                the same for a desk (endpoints.estate names it for every desk here)
  GET  /mock/nodes                         the nodes and the alerts, inspection
  POST /mock/report {"node_id": N, "report": {...}}   set a node's report (the rules run)
  POST /mock/alert {"node_id": N, "kind": K, "severity": S, "title": T}   raise one by hand
  POST /mock/code {"code": "...", "kind": "desk"|"node"}

  GET  /api/v1/health                      {"ok": true, "office": NAME}
  GET  /api/v1/desks/agents                the office's agents this desk may use (Phase 12 slice 8); per agent:
  GET  /api/v1/desks/agents/ID/activity    its recent activity, and
  POST /api/v1/desks/agents/ID/tasks       its task interface (JSON-RPC agent/card, tasks/send, tasks/get, tasks/list)
  GET  /agents/ID                          the office's own page for the agent (HTML; the Agents app shows it): with the desk
                                           token as a Bearer header it says "signed in as EMAIL" and sets a session cookie
                                           that signs the following page loads in (slice 9)
  POST /api/v1/desks/enroll                the contract
  POST /api/v1/desks/heartbeat, GET /api/v1/desks/me, POST /api/v1/desks/leave   (Bearer desk token)
  GET  /desk-models/                       200 (the gateway's reachability probe)
  GET  /desk-models/v1/models, POST /desk-models/v1/chat/completions (Bearer; stream or not)
  POST /mcp/records | /mcp/activity | /mcp/memory   JSON-RPC: initialize, tools/list, tools/call (Bearer)
  GET  /mock/state                         desks, heartbeats, chats, mcp calls (tokens hashed)
  POST /mock/retire {"desk_id": N}         retire a desk: its token answers 410 from then on
  POST /mock/code {"code": "..."}          add a one-time code
  -- Phase 13 slice 2 (docs/phase13-slice2-delegation.md): the directory, the keys, envelopes verified as the kernel does
  GET/POST /api/v1/estate/agents[/ID[/tasks]]   the directory; a node registers its agents; an agent's task interface (JSON-RPC)
  GET  /api/v1/estate/keys                 every member's public key and the coordinator's
  GET  /api/v1/estate/inbox?wait=N, POST …/inbox/ID/result    the node's inbox (tasks and actions, leased) and its results
  GET  /api/v1/estate/tasks/ID, POST /api/v1/estate/tasks (tasks/send by target)
  POST /api/v1/estate/nodes/ID/actions, GET /api/v1/estate/actions[/ID]
  GET  /api/v1/desks/inbox?wait=N, POST …/inbox/ID/reply|decide|read, POST /api/v1/desks/key
  POST /mock/task {"agent": NAME|ID, "originator": "user:x", "text": …, "sign": valid|tampered|expired|replay|stranger}   inject a task from the office
  POST /mock/inbox {"kind": "decision_needed", "subject": …}   inject an item into the person's inbox;  GET /mock/delegation  the state
"""
import argparse, ipaddress, hashlib, json, re, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SURFACE = 1


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Office:
    def __init__(self, name, codes, models, heartbeat_s, node_codes=(), report_s=300, node_heartbeat_s=None, overlay_range="100.100.0.0/16", fake_spokes=()):
        self.name, self.models, self.heartbeat_s, self.report_s = name, models, heartbeat_s, report_s
        # the overlay (Phase 13 slice 1b): the range, the hub, a version every member polls against; fake spokes so a hub under test has peers
        self.overlay = {"enabled": bool(overlay_range), "range": overlay_range or "100.100.0.0/16", "hub": None, "hub_endpoint": None, "hub_key": None, "version": 1}
        self.fake_spokes = []
        for spec in fake_spokes:
            n, _, k = spec.partition("=")
            self.fake_spokes.append({"id": -len(self.fake_spokes) - 1, "kind": "server", "name": n, "status": "active", "overlay_key": k, "overlay_address": None, "overlay_freed_at": None})
        self.node_heartbeat_s = node_heartbeat_s or heartbeat_s
        self.codes = {c: {"used": False, "kind": "desk"} for c in codes}
        for c in node_codes:
            self.codes[c] = {"used": False, "kind": "node"}
        self.nodes = {}         # id -> node (Phase 13 slice 1)
        self.node_tokens = {}   # token -> node id
        self.next_node_id = 57
        self.alerts = []        # the estate alerts the kernel will raise from the health rules
        self.next_alert_id = 301
        self.desks = {}         # id -> desk
        self.tokens = {}        # token -> desk id
        self.heartbeats, self.chats, self.mcp = [], [], []
        self.sessions = {}      # page session cookie -> desk id (slice 9: the office page with the desk's identity)
        self.next_id = 41
        self.lock = threading.Lock()
        self.tasks = {a["id"]: [] for a in self.AGENTS}      # agent id -> tasks (Phase 12 slice 8)
        for f in self.fake_spokes:                           # after the tables exist: allocation looks at nodes and desks
            self.ov_allocate(f, f["overlay_key"])
        # Phase 13 slice 2: the directory, tasks, actions, the person's inbox, the replay memory, the coordinator's key
        from maluos_estate import envelope as E
        self.E = E
        self.agents = {}            # id -> directory row
        self.next_agent_id = 101
        self.estate_tasks = {}      # id -> task row
        self.estate_actions = {}    # id -> action row
        self.inbox = []             # the person's (member 1) estate inbox items
        self.next_inbox_id = 501
        self.nonces = E.Nonces()
        self.coordinator_priv, self.coordinator_pub = E.genkey("coordinator")

    # -- the overlay (slice 1b): addresses, the hub, the peers and the names the kernel will publish
    @staticmethod
    def ov_label(name):
        import re as _re
        lab = _re.sub(r"-+", "-", _re.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-")
        return (lab or "node")[:63]

    def ov_members(self):
        """Every active member with a live address: nodes, desks and the fake spokes, by address."""
        out = []
        for m in list(self.nodes.values()) + list(self.desks.values()) + self.fake_spokes:
            if m.get("status") == "active" and m.get("overlay_address") and not m.get("overlay_freed_at"):
                out.append(m)
        out.sort(key=lambda m: ipaddress.ip_address(m["overlay_address"]))
        seen, rows = {}, []
        for m in out:
            lab = self.ov_label(m["name"])
            if lab in seen:
                lab = f"{lab}-{abs(m['id'])}"
            seen[lab] = True
            rows.append({"id": m["id"], "kind": "desk" if m in self.desks.values() else m.get("kind"), "name": lab, "address": m["overlay_address"], "public_key": m.get("overlay_key") or ""})
        return rows

    def ov_name(self, member):
        for r in self.ov_members():
            if r["id"] == member["id"]:
                return r["name"]
        return None

    def ov_allocate(self, member, key, hub=False):
        net = ipaddress.ip_network(self.overlay["range"])
        hosts = list(net.hosts())
        if hub:
            addr = str(hosts[0])
        elif member.get("overlay_address") and member["overlay_address"] != str(hosts[0]):
            addr = member["overlay_address"]
        else:
            used = {m["overlay_address"] for m in list(self.nodes.values()) + list(self.desks.values()) + self.fake_spokes
                    if m.get("overlay_address") and m is not member and (not m.get("overlay_freed_at") or time.time() - m["overlay_freed_at"] < 30 * 86400)}
            addr = next((str(h) for h in hosts[1:] if str(h) not in used), None)
            if addr is None:
                raise RuntimeError("the overlay range is full")
        member["overlay_key"], member["overlay_address"], member["overlay_freed_at"] = key, addr, None
        if hub:
            self.overlay["hub"], self.overlay["hub_key"] = member["id"], key
        self.overlay["version"] += 1
        return addr

    def ov_hub(self):
        hid = self.overlay["hub"]
        m = self.nodes.get(hid) if hid is not None else None
        if not m or m["status"] != "active" or not m.get("overlay_address"):
            return None
        return {"id": m["id"], "name": m["name"], "public_key": self.overlay["hub_key"] or m.get("overlay_key"), "endpoint": self.overlay["hub_endpoint"], "address": m["overlay_address"]}

    def ov_join(self, member, b, allow_hub):
        """The join's/enroll's overlay part: (status, code, message) on refusal, else None."""
        key = b.get("overlay_public_key")
        import re as _re
        if not self.overlay["enabled"] or not isinstance(key, str) or not _re.fullmatch(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=", key):
            member["overlay_seen"] = self.overlay["version"]; return None
        hub = b.get("overlay_hub") if allow_hub and isinstance(b.get("overlay_hub"), dict) else None
        if hub:
            ep = hub.get("endpoint")
            if not isinstance(ep, str) or not _re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", ep):
                return (400, "invalid", "overlay_hub.endpoint is host:port")
            cur = self.ov_hub()
            if cur and cur["id"] != member["id"]:
                return (409, "hub_exists", "the estate already has a hub; it must leave before another joins as the hub")
            self.overlay["hub_endpoint"] = ep
            self.ov_allocate(member, key, hub=True)
        else:
            self.ov_allocate(member, key)
        member["overlay_seen"] = self.overlay["version"]
        return None

    def ov_block(self, member):
        if not self.overlay["enabled"] or not member.get("overlay_address") or member.get("overlay_freed_at"):
            return None
        hub = self.ov_hub()
        is_hub = hub is not None and hub["id"] == member["id"]
        if hub is None:
            return None
        return {"address": member["overlay_address"], "prefix": ipaddress.ip_network(self.overlay["range"]).prefixlen, "name": (self.ov_name(member) or "node") + ".internal",
                "hub": None if is_hub else {"public_key": hub["public_key"], "endpoint": hub["endpoint"], "address": hub["address"]},
                "role": "hub" if is_hub else "spoke", "listen_port": 51820 if is_hub else None}

    def ov_answer(self, member):
        hub = self.ov_hub()
        is_hub = hub is not None and hub["id"] == member["id"]
        members = self.ov_members()
        me = next((m for m in members if m["id"] == member["id"]), None)
        if is_hub:
            peers = [{"public_key": m["public_key"], "address": m["address"], "name": m["name"]} for m in members if m["id"] != member["id"] and m["public_key"]]
        elif hub:
            peers = [{"public_key": hub["public_key"], "address": hub["address"], "name": self.ov_label(hub["name"])}]
        else:
            peers = []
        return {"ok": True, "surface": SURFACE, "fetched_at": now(),
                "self": {"address": me["address"], "name": me["name"] + ".internal", "role": "hub" if is_hub else "spoke"} if me else None,
                "hub": {"public_key": hub["public_key"], "endpoint": hub["endpoint"], "address": hub["address"], "name": self.ov_label(hub["name"]) + ".internal"} if hub else None,
                "peers": peers, "names": [{"name": m["name"], "address": m["address"], "kind": m["kind"]} for m in members],
                "refresh_s": 60, "version": self.overlay["version"]}

    def ov_changed(self, member):
        v = self.overlay["version"]
        if member.get("overlay_seen") == v:
            return False
        member["overlay_seen"] = v
        return True

    def ov_free(self, member):
        if member.get("overlay_address") and not member.get("overlay_freed_at"):
            member["overlay_freed_at"] = time.time(); self.overlay["version"] += 1
        if self.overlay["hub"] == member["id"]:
            self.overlay["hub"], self.overlay["hub_key"] = None, None; self.overlay["version"] += 1

    def ov_rotate(self, member, key):
        if not member.get("overlay_address"):
            self.ov_allocate(member, key)
        else:
            member["overlay_key"] = key
            if self.overlay["hub"] == member["id"]:
                self.overlay["hub_key"] = key
            self.overlay["version"] += 1

    def ov_public(self):
        return {**self.overlay, "members": self.ov_members()}

    def endpoints(self, base):
        return {"heartbeat": f"{base}/api/v1/desks/heartbeat", "me": f"{base}/api/v1/desks/me", "leave": f"{base}/api/v1/desks/leave",
                "records": f"{base}/mcp/records", "activity": f"{base}/mcp/activity", "memory": f"{base}/mcp/memory", "actions": None,
                "models": {"url": f"{base}/desk-models", "models": list(self.models)}, "apps": f"{base}/api/v1/desks/apps",
                "agents": f"{base}/api/v1/desks/agents", "estate": f"{base}/api/v1/desks/estate",
                "inbox": f"{base}/api/v1/desks/inbox", "key": f"{base}/api/v1/desks/key", "keys": f"{base}/api/v1/estate/keys", "actions": f"{base}/api/v1/estate/actions"}

    # -- the estate (Phase 13 slice 1): nodes, the report, the health rules the kernel will apply, the alerts
    CRITICAL_UNITS = ("postgresql@18-main.service", "maluos-vault.service")

    def node_endpoints(self, base):
        return {k: f"{base}/api/v1/estate/{k}" for k in ("heartbeat", "me", "leave", "nodes", "agents", "keys", "inbox", "tasks")}

    def node_answer(self, node, base):
        ov = self.ov_block(node)
        return {"ok": True, "surface": SURFACE,
                "node": {k: node.get(k) for k in ("id", "kind", "name", "status", "presence", "last_seen_at", "last_report_at")},
                "office": {"name": self.name, "url": base}, "endpoints": {**self.node_endpoints(base), "overlay": f"{base}/api/v1/estate/overlay" if ov else None},
                "heartbeat_s": self.node_heartbeat_s, "report_s": self.report_s, "overlay": ov}

    def raise_alert(self, node, kind, severity, title, report_ts=None, key=None):
        """One open row per (node, kind, key): the title and severity follow the latest report (a disk at 90 % then 97 %
        is one alert), the row's id and ts stay."""
        key = key or title
        for a in self.alerts:
            if a["node_id"] == node["id"] and a["kind"] == kind and a["key"] == key and not a["cleared_at"]:
                a["title"], a["severity"], a["report_ts"] = title, severity, report_ts or a["report_ts"]
                return a
        a = {"id": self.next_alert_id, "ts": now(), "node_id": node["id"], "node": node["name"], "kind": kind, "key": key, "severity": severity,
             "title": title, "cleared_at": None, "report_ts": report_ts}
        self.next_alert_id += 1
        self.alerts.append(a)
        return a

    def clear_alerts(self, node, keep, kinds_exclude=()):
        for a in self.alerts:
            if a["node_id"] == node["id"] and not a["cleared_at"] and a["kind"] not in kinds_exclude and (a["kind"], a["key"]) not in keep:
                a["cleared_at"] = now()

    def evaluate(self, node):
        """The fixed rules of the contract on the node's last report: what is wrong, as (kind, title) -> severity."""
        rep = node.get("report") or {}
        found = {}      # (kind, key) -> (severity, title)
        for u in rep.get("units") or []:
            if u.get("active") != "active":
                found[("unit_down", u.get("unit"))] = ("critical" if u.get("unit") in self.CRITICAL_UNITS else "warning", f"{u.get('unit')} {u.get('active')}")
        for a in rep.get("agents") or []:
            if a.get("active") == "failed" or (a.get("active") == "activating" and (a.get("restarts") or 0) > 0):
                found[("agent_down", a.get("name"))] = ("warning", f"agent {a.get('name')} {'failed' if a.get('active') == 'failed' else 'failing'} ({a.get('restarts') or 0} restarts)")
        v = rep.get("vault")
        if v is not None and not v.get("ok"):
            found[("unit_down", "maluos-vault")] = ("critical", "maluos-vault not answering")
        for al in (v or {}).get("alerts") or []:
            found[("vault_alert", str(al.get("id") or al.get("title")))] = ("warning", f"{(al.get('kind') or 'alert').replace('_', ' ')}: {al.get('principal') or '?'}")
        g = rep.get("gateway")
        if g is not None and not g.get("ok"):
            found[("unit_down", "maluos-gateway")] = ("warning", "maluos-gateway not answering")
        if (rep.get("updates") or {}).get("reboot_required"):
            found[("reboot_required", "reboot")] = ("warning", "a restart is required to finish updates")
        for d in rep.get("disk") or []:
            pct = d.get("used_pct") or 0
            if pct > 85:
                found[("disk_full", d.get("mount"))] = ("critical" if pct > 95 else "warning", f"disk {d.get('mount')} at {pct} %")
        m = rep.get("memory") or {}
        if m.get("total_mb") and m.get("available_mb") is not None and m["available_mb"] < 0.05 * m["total_mb"]:
            found[("memory_low", "memory")] = ("critical", f"memory available {m['available_mb']} MB of {m['total_mb']}")
        for (kind, key), (sev, title) in found.items():
            self.raise_alert(node, kind, sev, title, rep.get("ts"), key=key)
        self.clear_alerts(node, set(found), kinds_exclude=("node_offline", "manual"))

    def set_presence(self, node, presence):
        node["presence"] = presence
        if presence == "online":
            for a in self.alerts:
                if a["node_id"] == node["id"] and a["kind"] == "node_offline" and not a["cleared_at"]:
                    a["cleared_at"] = now()
        elif node["status"] == "active":
            self.raise_alert(node, "node_offline", "warning", f"{node['name']} is offline", key="presence")

    def sweep(self):
        """The presence sweep: a node silent for three heartbeats is offline (desks are swept by the real kernel the same way)."""
        with self.lock:
            for n in self.nodes.values():
                if n["status"] == "active" and n["presence"] == "online" and time.time() - n["_seen"] > 3 * self.node_heartbeat_s:
                    self.set_presence(n, "offline")

    def open_alerts(self, node):
        return [a for a in self.alerts if a["node_id"] == node["id"] and not a["cleared_at"]]

    def node_health(self, node):
        if node["status"] != "active":
            return "retired"
        if node["presence"] != "online":
            return "offline"
        sev = {a["severity"] for a in self.open_alerts(node) if a["kind"] != "node_offline"}
        return "critical" if "critical" in sev else "warning" if sev else "ok"

    def node_summary(self, node):
        rep = node.get("report") or {}
        parts = []
        failed = sum(1 for a in rep.get("agents") or [] if a.get("active") == "failed")
        down = [u for u in rep.get("units") or [] if u.get("active") != "active"]
        if down:
            parts.append(f"{len(down)} unit{'s' if len(down) != 1 else ''} down")
        if failed:
            parts.append(f"{failed} agent{'s' if failed != 1 else ''} failed")
        u = rep.get("updates") or {}
        if u.get("pending_count"):
            parts.append(f"{u['pending_count']} updates pending" + (f" ({u['security_count']} security)" if u.get("security_count") else ""))
        if u.get("reboot_required"):
            parts.append("restart required")
        for d in rep.get("disk") or []:
            if (d.get("used_pct") or 0) > 85:
                parts.append(f"disk {d.get('mount')} at {d['used_pct']} %")
        if node["presence"] != "online":
            return "offline"
        return " · ".join(parts) or "online"

    def node_row(self, node, full=False):
        rep = node.get("report") or {}
        us = rep.get("units") or []; ag = rep.get("agents") or []; g = rep.get("gateway") or {}; m = rep.get("memory") or {}
        row = {"id": node["id"], "kind": node["kind"], "name": node["name"], "hostname": (node.get("facts") or {}).get("hostname"),
               "presence": node["presence"], "last_seen_at": node["last_seen_at"], "last_report_at": node.get("last_report_at"),
               "health": self.node_health(node), "summary": self.node_summary(node),
               "units": {"up": sum(1 for u in us if u.get("active") == "active"), "down": sum(1 for u in us if u.get("active") != "active")},
               "agents": {"count": len(ag), "running": sum(1 for a in ag if a.get("active") == "active"), "failed": sum(1 for a in ag if a.get("active") == "failed")},
               "gateway": {"ok": bool(g.get("ok")), "backends_healthy": sum(1 for b in g.get("backends") or [] if b.get("healthy")), "backends": len(g.get("backends") or []),
                           "queued": (g.get("queue") or {}).get("queued", 0), "running": (g.get("queue") or {}).get("running", 0)} if rep.get("gateway") else None,
               "updates": {k: (rep.get("updates") or {}).get(k) for k in ("pending_count", "security_count", "reboot_required")} if rep.get("updates") else None,
               "disk_max_pct": max([d.get("used_pct") or 0 for d in rep.get("disk") or []] or [None]),
               "memory_available_pct": round(100 * m["available_mb"] / m["total_mb"]) if m.get("total_mb") else None,
               "load1": (rep.get("load") or [None])[0], "facts": node.get("facts") or {},
               "overlay": {"address": node["overlay_address"]} if node.get("overlay_address") and not node.get("overlay_freed_at") else None}
        if full:
            row["report"] = rep or None
        return row

    def desk_row(self, desk):
        return {"id": desk["id"], "kind": "desk", "name": desk["name"], "owner": desk["owner"], "presence": desk["presence"], "last_seen_at": desk["last_seen_at"],
                "health": "retired" if desk["status"] != "active" else "ok" if desk["presence"] == "online" else "offline", "summary": desk["presence"], "facts": desk["facts"],
                "overlay": {"address": desk["overlay_address"]} if desk.get("overlay_address") and not desk.get("overlay_freed_at") else None}

    def nodes_answer(self, base, node_id=None):
        if node_id is not None:
            n = self.nodes.get(node_id)
            return {"ok": True, "surface": SURFACE, "office": {"name": self.name, "url": base}, "fetched_at": now(), "node": self.node_row(n, full=True),
                    "alerts": [a for a in self.alerts if a["node_id"] == node_id and not a["cleared_at"]]} if n else None
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        return {"ok": True, "surface": SURFACE, "office": {"name": self.name, "url": base}, "fetched_at": now(),
                "nodes": [self.node_row(n) for n in self.nodes.values() if n["status"] == "active"] + [self.desk_row(d) for d in self.desks.values() if d["status"] == "active"],
                "alerts": [a for a in self.alerts if not a["cleared_at"] or a["cleared_at"] >= recent]}

    AGENTS = [{"id": "helpdesk", "name": "Help Desk agent", "description": "Triages cases and drafts answers from the knowledgebase.", "icon": "help-faq",
               "capabilities": ["helpdesk.triage", "kb.search"], "owner": "office", "node": "office-1", "presence": "online", "state": "idle"},
              {"id": "research", "name": "Research agent", "description": "Reads the records you may see and summarises them.", "icon": "system-search",
               "capabilities": ["research", "summarise"], "owner": "office", "node": "office-1", "presence": "online", "state": "idle"}]

    def agents_answer(self, base):
        out = []
        for a in self.AGENTS:
            d = dict(a, page=f"{base}/agents/{a['id']}", tasks=f"{base}/api/v1/desks/agents/{a['id']}/tasks", activity=f"{base}/api/v1/desks/agents/{a['id']}/activity")
            d["task_count"] = len(self.tasks.get(a["id"]) or [])
            out.append(d)
        return {"ok": True, "surface": SURFACE, "agents": out}

    def agent_activity(self, aid, desk):
        rows = [{"ts": t["ts"], "kind": "task", "actor": f"desk #{t['desk_id']}", "summary": f"task {t['id']} {t['state']}: {t['input']['text'][:60]}"} for t in reversed(self.tasks.get(aid) or [])]
        rows.append({"ts": now(), "kind": "directory", "actor": "office", "summary": f"agent {aid} listed for desk #{desk['id']} ({desk['owner']['email']})"})
        return {"ok": True, "surface": SURFACE, "activity": rows[:50]}

    def agent_rpc(self, aid, b, desk):
        a = next((x for x in self.AGENTS if x["id"] == aid), None)
        method, rid, params = b.get("method"), b.get("id"), b.get("params") or {}
        if method == "agent/card":
            return {"jsonrpc": "2.0", "id": rid, "result": dict(a, protocol="maluos-tasks/0.1", principal=f"agent:{aid}")}
        if method == "tasks/send":
            parts = (params.get("message") or {}).get("parts") or []
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if not text:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "tasks/send needs message.parts with text"}}
            t = {"id": secrets.token_hex(6), "state": "completed", "ts": now(), "desk_id": desk["id"], "input": {"text": text, "parts": parts},
                 "output": {"text": f"office agent {aid} reply to: {text}", "artifacts": []}, "error": None, "done_ts": now()}
            self.tasks.setdefault(aid, []).append(t)
            return {"jsonrpc": "2.0", "id": rid, "result": t}
        if method == "tasks/get":
            t = next((x for x in self.tasks.get(aid) or [] if x["id"] == params.get("id")), None)
            return {"jsonrpc": "2.0", "id": rid, "result": t} if t else {"jsonrpc": "2.0", "id": rid, "error": {"code": -32004, "message": "no such task"}}
        if method == "tasks/list":
            mine = [t for t in self.tasks.get(aid) or [] if t["desk_id"] == desk["id"]]
            return {"jsonrpc": "2.0", "id": rid, "result": {"tasks": list(reversed(mine))[:int(params.get("limit") or 50)]}}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}

    # -- Phase 13 slice 2: the directory, envelopes, tasks, the node's inbox, actions, the person's inbox
    def dg_node_ref(self, m):
        return "desk:%d" % m["id"] if "owner" in m and "kind" not in m else "%s:%d" % (m["kind"], m["id"])

    def dg_keys_table(self):
        t = {"coordinator": self.coordinator_pub}
        for n in self.nodes.values():
            if n["status"] == "active" and n.get("public_key"):
                t[self.dg_node_ref(n)] = n["public_key"]
        for d in self.desks.values():
            if d["status"] == "active" and d.get("public_key"):
                t[self.dg_node_ref(d)] = d["public_key"]
        return t

    def dg_keys_answer(self):
        keys = []
        for n in list(self.nodes.values()) + list(self.desks.values()):
            if n["status"] == "active" and n.get("public_key"):
                keys.append({"node": self.dg_node_ref(n), "kind": n.get("kind", "desk"), "name": n["name"], "public_key": n["public_key"], "presence": n["presence"]})
        return {"ok": True, "surface": SURFACE, "coordinator": {"node": "coordinator", "public_key": self.coordinator_pub}, "keys": keys, "fetched_at": now()}

    def dg_register(self, node, manifests):
        seen = set(); n = 0
        for m in manifests:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", m["name"]):
                continue
            row = next((a for a in self.agents.values() if a["location_id"] == node["id"] and a["name"] == m["name"]), None)
            if row is None:
                row = {"id": self.next_agent_id, "location_id": node["id"]}; self.next_agent_id += 1; self.agents[row["id"]] = row
            row.update({"name": m["name"], "principal": m.get("principal") or "agent:" + m["name"], "display_name": m.get("display") or m.get("display_name"), "description": m.get("description") or "",
                        "capabilities": sorted({str(c).lower() for c in (m.get("capabilities") or []) if c}), "owner": m.get("owner") if m.get("owner") not in ("", "none") else None,
                        "accept_from": [str(x) for x in (m.get("accept_from") or [])], "max_classification": m.get("max_classification"), "approve": [str(x) for x in (m.get("approve") or [])],
                        "tasks": m.get("tasks", True) is not False, "unit_state": m.get("unit_state") or m.get("active"), "status": "active", "last_seen_at": now()})
            seen.add(m["name"]); n += 1
        removed = 0
        for a in self.agents.values():
            if a["location_id"] == node["id"] and a["status"] == "active" and a["name"] not in seen:
                a["status"], a["removed_at"] = "removed", now(); removed += 1
        return {"registered": n, "removed": removed}

    def dg_deregister(self, node):
        for a in self.agents.values():
            if a["location_id"] == node["id"] and a["status"] == "active":
                a["status"], a["removed_at"] = "removed", now()

    def dg_present_agent(self, a, base):
        n = self.nodes.get(a["location_id"]) or {}
        node = {"id": n.get("id"), "kind": n.get("kind"), "name": n.get("name"), "presence": n.get("presence"), "ref": self.dg_node_ref(n) if n else None}
        online = node["presence"] == "online" and (a.get("unit_state") or "active") == "active"
        return {"id": a["id"], "name": a["name"], "principal": a["principal"], "display_name": a.get("display_name"), "description": a.get("description") or "",
                "capabilities": a["capabilities"], "owner": a.get("owner"), "accept_from": a["accept_from"], "max_classification": a.get("max_classification"), "approve": a.get("approve") or [],
                "node": node, "status": a["status"], "unit_state": a.get("unit_state"), "presence": "removed" if a["status"] != "active" else ("online" if online else "offline"),
                "state": "failed" if a.get("unit_state") == "failed" else "idle", "tasks": f"{base}/api/v1/estate/agents/{a['id']}/tasks" if a["tasks"] and a["status"] == "active" else None,
                "card": None, "hired": False, "first_seen_at": a.get("last_seen_at"), "last_seen_at": a.get("last_seen_at")}

    def dg_agents_answer(self, base, capability=None, node_id=None):
        rows = [a for a in self.agents.values() if a["status"] == "active" and (not capability or capability.lower() in a["capabilities"]) and (node_id is None or a["location_id"] == node_id)]
        return {"ok": True, "surface": SURFACE, "agents": [self.dg_present_agent(a, base) for a in sorted(rows, key=lambda a: (a["location_id"], a["name"]))], "fetched_at": now()}

    def dg_desk_agents(self, base):
        """The directory in the slice 8 shape, beside the office's own agents."""
        out = []
        for a in self.agents.values():
            if a["status"] != "active":
                continue
            p = self.dg_present_agent(a, base)
            out.append({"id": str(a["id"]), "name": p["display_name"] or p["name"], "agent": p["name"], "description": p["description"], "icon": "maluos-logo", "capabilities": p["capabilities"],
                        "owner": p["owner"], "accept_from": p["accept_from"], "max_classification": p["max_classification"], "node": p["node"]["name"], "node_ref": p["node"]["ref"], "node_kind": p["node"]["kind"],
                        "presence": p["presence"], "state": p["state"], "principal": p["principal"], "hired": False,
                        "tasks": f"{base}/api/v1/desks/agents/{a['id']}/tasks" if p["tasks"] else None, "activity": f"{base}/api/v1/desks/agents/{a['id']}/activity", "page": f"{base}/settings/desks"})
        return out

    def dg_accepts(self, a, originator):
        return self.E.accepts(a["accept_from"], a.get("owner"), originator)

    def dg_verify(self, env, expect_signer):
        return self.E.verify(env, self.dg_keys_table(), expect_signer, self.nonces)

    def dg_present_task(self, t):
        res = t.get("result") or {}
        return {"id": t["id"], "state": "queued" if t["state"] == "leased" else t["state"], "ts": t["created_at"], "input": t["input"], "output": res.get("output"),
                "error": res.get("error") or (t.get("reason") if t["state"] in ("refused", "failed") else None), "done_ts": t.get("done_at"), "envelope_id": t["envelope"]["id"], "hop": t["hop"],
                "agent": {"id": t["agent_id"], "name": t["agent_name"], "principal": t["agent_principal"]}, "node": t["node"], "originator": t["originator"], "sender": t["sender"],
                "reason": t.get("reason"), "leases": t["leases"], "provenance": res.get("provenance"), "usage": res.get("usage"), "ask": res.get("ask") if t["state"] == "pending_approval" else None}

    def dg_rpc(self, a, req, member, base):
        """agent/card, tasks/send (with the envelope), tasks/get, tasks/list for a directory agent; member is the caller's desk or node row."""
        err = lambda code, msg, reason=None: {"error": {"code": code, "message": msg, **({"data": {"reason": reason}} if reason else {})}}
        method, params = req.get("method"), req.get("params") or {}
        signer = self.dg_node_ref(member)
        if method == "agent/card":
            p = self.dg_present_agent(a, base)
            return {"result": {"name": p["display_name"] or p["name"], "description": p["description"], "capabilities": p["capabilities"], "principal": p["principal"], "owner": p["owner"],
                               "node": p["node"]["ref"], "accept_from": p["accept_from"], "protocol": "maluos-tasks/0.3"}}
        if method == "tasks/send":
            if a["status"] != "active" or not a["tasks"]:
                return err(-32004, "This agent takes no tasks.", "not_available")
            parts = (params.get("message") or {}).get("parts") or ([{"type": "text", "text": params["text"]}] if params.get("text") else [])
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if not text:
                return err(-32602, "tasks/send needs message.parts with text")
            env = params.get("envelope")
            if not isinstance(env, dict):
                return err(-32602, "tasks/send to an estate agent needs an envelope", "envelope_required")
            ok, reason, msg = self.dg_verify(env, signer)
            if not ok:
                return err(-32001, msg, reason)
            tgt = env.get("target") or {}
            if tgt.get("agent") and tgt["agent"] != a["name"]:
                return err(-32602, "envelope.target.agent is not this agent", "bad_envelope")
            if tgt.get("node") and tgt["node"] != self.dg_node_ref(self.nodes[a["location_id"]]):
                return err(-32602, "envelope.target.node is not this agent's node", "bad_envelope")
            hop = max(1, len(env.get("chain") or []))
            old = next((t for t in self.estate_tasks.values() if t["envelope"]["id"] == env["id"] and t["hop"] == hop), None)
            if old:
                return {"result": self.dg_present_task(old)}
            tid = "t_" + secrets.token_hex(8)
            t = {"id": tid, "envelope": env, "hop": hop, "agent_id": a["id"], "agent_name": a["name"], "agent_principal": a["principal"], "location_id": a["location_id"],
                 "node": self.dg_node_ref(self.nodes[a["location_id"]]), "originator": (env.get("originator") or {}).get("principal"), "originator_member": 1 if "owner" in member else None,
                 "sender": {"principal": (env.get("sender") or {}).get("principal"), "node": signer}, "input": {"text": text, "parts": parts}, "state": "queued", "lease_until": None, "leases": 0,
                 "result": None, "reason": None, "created_at": now(), "done_at": None}
            self.estate_tasks[tid] = t
            if params.get("wait", True) is not False:
                deadline = time.time() + min(float(params.get("timeout") or 30), 60)
                while t["state"] in ("queued", "leased", "running") and time.time() < deadline:
                    self.lock.release()
                    try:
                        time.sleep(0.25)
                    finally:
                        self.lock.acquire()
            return {"result": self.dg_present_task(t)}
        if method == "tasks/get":
            t = self.estate_tasks.get(params.get("id") or "")
            if not t or t["agent_id"] != a["id"]:
                return err(-32004, "no such task")
            return {"result": self.dg_present_task(t)}
        if method == "tasks/list":
            rows = sorted((t for t in self.estate_tasks.values() if t["agent_id"] == a["id"]), key=lambda t: t["created_at"], reverse=True)
            return {"result": {"tasks": [self.dg_present_task(t) for t in rows[:int(params.get("limit") or 50)]]}}
        return err(-32601, f"unknown method {method}")

    def dg_lease_sweep(self):
        for tbl in (self.estate_tasks, self.estate_actions):
            for t in tbl.values():
                if t["state"] == "leased" and t["lease_until"] and t["lease_until"] < time.time():
                    if t["leases"] >= 3:
                        t.update(state="failed", reason="node_unresponsive", done_at=now(), lease_until=None)
                    else:
                        t.update(state="queued", lease_until=None)

    def dg_inbox_take(self, node):
        self.dg_lease_sweep()
        items = []
        for t in sorted(self.estate_tasks.values(), key=lambda t: t["created_at"]):
            if t["location_id"] == node["id"] and t["state"] == "queued":
                t.update(state="leased", lease_until=time.time() + 120, leases=t["leases"] + 1)
                items.append({"id": t["id"], "kind": "task", "agent": t["agent_name"], "envelope": t["envelope"], "message": {"role": "user", "parts": t["input"]["parts"]},
                              "answer": (t.get("result") or {}).get("answer"), "lease_until": now(), "leases": t["leases"]})
        for x in sorted(self.estate_actions.values(), key=lambda t: t["created_at"]):
            if x["location_id"] == node["id"] and x["state"] == "queued":
                x.update(state="leased", lease_until=time.time() + 120, leases=x["leases"] + 1)
                items.append({"id": x["id"], "kind": "action", "action": x["action"], "agent": x.get("agent"), "envelope": x["envelope"], "lease_until": now(), "leases": x["leases"]})
        return items

    def dg_inbox_post(self, kind, subject, body, from_principal, from_node, task_id=None, options=None):
        item = {"id": self.next_inbox_id, "kind": kind, "subject": subject[:300] or "(no subject)", "body": (body or "")[:20000], "from": {"principal": from_principal, "node": from_node},
                "task_id": task_id, "options": options, "status": "unread", "decision": None, "decision_note": None, "reply": None, "created_at": now(), "read_at": None, "done_at": None}
        self.next_inbox_id += 1; self.inbox.append(item)
        return item

    def dg_result(self, node, item_id, body):
        res = body.get("result") if isinstance(body.get("result"), dict) else {}
        if item_id.startswith("t_"):
            t = self.estate_tasks.get(item_id)
            if not t or t["location_id"] != node["id"]:
                return 404, {"error": "not_found", "message": "no such task of this node"}
            if t["state"] in ("completed", "failed", "refused"):
                return 200, {"ok": True, "task": self.dg_present_task(t), "note": "already done"}
            state = res.get("state") or ("refused" if body.get("refused") else "failed")
            reason = body.get("refused") if isinstance(body.get("refused"), str) else res.get("reason")
            if state in ("working",):
                state = "running"
            if state not in ("completed", "failed", "refused", "pending_approval", "running"):
                state = "failed"
            keep = {k: res[k] for k in ("output", "error", "provenance", "usage", "ask", "answer") if k in res}
            if state == "pending_approval":
                ask = res.get("ask") or {}
                self.dg_inbox_post("question" if ask.get("kind") == "question" else "decision_needed", ask.get("subject") or f"{t['agent_name']} asks to run a task", ask.get("body") or "",
                                   t["agent_principal"], t["node"], t["id"], ask.get("options") or ["approve", "deny"])
            t.update(state=state, reason=reason, result=keep, lease_until=None, done_at=now() if state in ("completed", "failed", "refused") else None)
            if state in ("failed", "refused") and t.get("originator_member"):
                self.dg_inbox_post("fyi", f"{t['agent_name']} {state}: {reason or keep.get('error') or 'the task did not complete'}", "", t["agent_principal"], t["node"], t["id"])
            return 200, {"ok": True, "task": self.dg_present_task(t)}
        if item_id.startswith("a_"):
            x = self.estate_actions.get(item_id)
            if not x or x["location_id"] != node["id"]:
                return 404, {"error": "not_found", "message": "no such action of this node"}
            if x["state"] in ("completed", "failed", "refused"):
                return 200, {"ok": True, "action": self.dg_present_action(x), "note": "already done"}
            state = res.get("state") or ("completed" if res.get("ok") else ("refused" if body.get("refused") else "failed"))
            reason = body.get("refused") if isinstance(body.get("refused"), str) else (res.get("reason") or res.get("error"))
            x.update(state=state if state in ("completed", "failed", "refused") else "failed", reason=reason, result={k: res.get(k) for k in ("ok", "output", "error", "state") if k in res}, lease_until=None, done_at=now())
            self.dg_inbox_post("result", f"{x['action']}{' ' + x['agent'] if x.get('agent') else ''} on {node['name']}: {x['state']}" + (f" ({reason})" if reason else ""), str(res.get("output") or "")[:4000], "node", self.dg_node_ref(node))
            return 200, {"ok": True, "action": self.dg_present_action(x)}
        return 404, {"error": "not_found", "message": "an item id is t_… or a_…"}

    def dg_present_action(self, x):
        n = self.nodes.get(x["location_id"]) or {}
        return {"id": x["id"], "node": {"id": x["location_id"], "name": n.get("name")}, "action": x["action"], "agent": x.get("agent"), "state": x["state"], "reason": x.get("reason"),
                "result": x.get("result"), "requested_by": 1, "envelope_id": x["envelope"]["id"], "created_at": x["created_at"], "done_at": x.get("done_at")}

    def dg_action_create(self, node, desk, b):
        action = b.get("action"); agent = b.get("agent")
        if action not in ("restart_agent", "start_agent", "stop_agent", "apply_updates", "reboot"):
            return 400, {"error": "invalid", "message": "action is one of restart_agent, start_agent, stop_agent, apply_updates, reboot"}
        if action.endswith("_agent") and not (isinstance(agent, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,30}", agent)):
            return 400, {"error": "invalid", "message": "the agent actions need agent"}
        env = b.get("envelope")
        if not isinstance(env, dict):
            return 400, {"error": "envelope_required", "message": "a node action carries the desk's envelope"}
        ok, reason, msg = self.dg_verify(env, self.dg_node_ref(desk))
        if not ok:
            return 403, {"error": reason, "message": msg}
        if (env.get("target") or {}).get("node") != self.dg_node_ref(node):
            return 400, {"error": "bad_envelope", "message": "envelope.target.node is not this node"}
        x = {"id": "a_" + secrets.token_hex(8), "location_id": node["id"], "action": action, "agent": agent if action.endswith("_agent") else None, "envelope": env, "state": "queued",
             "lease_until": None, "leases": 0, "result": None, "reason": None, "created_at": now(), "done_at": None}
        self.estate_actions[x["id"]] = x
        if b.get("wait"):
            deadline = time.time() + min(float(b["wait"]), 60)
            while x["state"] in ("queued", "leased") and time.time() < deadline:
                self.lock.release()
                try:
                    time.sleep(0.25)
                finally:
                    self.lock.acquire()
        return 201, {"ok": True, "surface": SURFACE, "action": self.dg_present_action(x)}

    def dg_desk_inbox(self, all_items=False, since=0):
        rows = [i for i in self.inbox if i["id"] > since and (all_items or i["status"] == "unread")]
        rows.sort(key=lambda i: i["id"], reverse=True)
        return {"ok": True, "surface": SURFACE, "unread": sum(1 for i in self.inbox if i["status"] == "unread"), "items": rows[:50], "fetched_at": now()}

    def dg_inbox_answer(self, desk, item_id, what, b):
        item = next((i for i in self.inbox if i["id"] == item_id), None)
        if not item:
            return 404, {"error": "not_found", "message": "no such inbox item of yours"}
        if what == "read":
            if item["status"] == "unread":
                item.update(status="read", read_at=now())
            return 200, {"ok": True, "surface": SURFACE, "read": 1}
        if item["status"] == "done":
            return 409, {"error": "conflict", "message": "this item was answered already"}
        env = b.get("envelope")
        if not isinstance(env, dict):
            return 400, {"error": "envelope_required", "message": "a reply or decision carries the desk's envelope"}
        ok, reason, msg = self.dg_verify(env, self.dg_node_ref(desk))
        if not ok:
            return 403, {"error": reason, "message": msg}
        decision = note = reply = None
        if what == "decide":
            decision = str(b.get("decision") or "").lower()
            if decision not in (item.get("options") or ["approve", "deny"]):
                return 400, {"error": "invalid", "message": "decision is one of " + ", ".join(item.get("options") or ["approve", "deny"])}
            note = b.get("note")
        else:
            reply = str(b.get("text") or "").strip()
            if not reply:
                return 400, {"error": "invalid", "message": "text is required"}
        item.update(status="done", decision=decision, decision_note=note, reply=reply, answer_envelope=env, read_at=item["read_at"] or now(), done_at=now())
        task = None
        t = self.estate_tasks.get(item.get("task_id") or "")
        if t and t["state"] == "pending_approval":
            res = dict(t.get("result") or {})
            res["answer"] = {"kind": "decision" if what == "decide" else "reply", "decision": decision, "note": note, "text": reply, "by": (env.get("sender") or {}).get("principal"), "envelope": env, "ts": now()}
            t.update(state="queued", result=res, lease_until=None)
            task = self.dg_present_task(t)
        return 200, {"ok": True, "surface": SURFACE, "item": {k: v for k, v in item.items() if k != "answer_envelope"}, "task": task}

    def dg_public(self):
        return {"agents": [self.dg_present_agent(a, "") for a in self.agents.values()], "tasks": [self.dg_present_task(t) for t in self.estate_tasks.values()],
                "actions": [self.dg_present_action(x) for x in self.estate_actions.values()],
                "inbox": [{k: v for k, v in i.items() if k != "answer_envelope"} | {"answered_by": ((i.get("answer_envelope") or {}).get("sig") or {}).get("key")} for i in self.inbox],
                "keys": self.dg_keys_table(), "nonces": len(self.nonces.seen)}

    def dg_inject_task(self, b, base):
        """/mock/task: a task from a named originator to a directory agent, signed valid|tampered|expired|replay|stranger (the office's own key, as the coordinator)."""
        name = str(b.get("agent") or "")
        a = next((x for x in self.agents.values() if x["status"] == "active" and (x["name"] == name or str(x["id"]) == name)), None)
        if not a:
            return 404, {"error": "not_found", "message": f"no agent {name!r} in the directory"}
        E = self.E
        sign = b.get("sign") or "valid"
        originator = {"principal": b.get("originator") or "user:mock", "kind": "human", "node": "coordinator"}
        cls = b.get("classification") or "internal"
        env = E.make(originator, {"principal": b.get("sender") or originator["principal"], "node": "coordinator"}, {"agent": a["name"], "node": self.dg_node_ref(self.nodes[a["location_id"]])},
                     b.get("purpose") or "injected by the mock", {"scopes": [], "classification": cls, "budget": {"usd": 0.1, "calls": 5}})
        if sign == "expired":
            env["issued_at"] = E.utc(time.time() - 7200); env["expires_at"] = E.utc(time.time() - 3600)
        if sign == "replay" and getattr(self, "_last_nonce", None):
            env["nonce"] = self._last_nonce
        env = E.sign(env, "coordinator", self.coordinator_priv)
        if sign == "tampered":
            env["purpose"] = "tampered after signing"
        self._last_nonce = env["nonce"]
        text = b.get("text") or "injected task"
        tid = "t_" + secrets.token_hex(8)
        t = {"id": tid, "envelope": env, "hop": 1, "agent_id": a["id"], "agent_name": a["name"], "agent_principal": a["principal"], "location_id": a["location_id"],
             "node": self.dg_node_ref(self.nodes[a["location_id"]]), "originator": originator["principal"], "originator_member": 1, "sender": {"principal": env["sender"]["principal"], "node": "coordinator"},
             "input": {"text": text, "parts": [{"type": "text", "text": text}]}, "state": "queued", "lease_until": None, "leases": 0, "result": None, "reason": None, "created_at": now(), "done_at": None}
        self.estate_tasks[tid] = t
        if b.get("wait"):
            deadline = time.time() + min(float(b["wait"]), 60)
            while t["state"] in ("queued", "leased", "running") and time.time() < deadline:
                self.lock.release()
                try:
                    time.sleep(0.25)
                finally:
                    self.lock.acquire()
        return 201, {"ok": True, "task": self.dg_present_task(t), "envelope": env}

    APPS = [{"id": "malumail", "name": "MaluMail", "description": "Mail for the office, with agents that read and draft with you.", "icon": "mail-unread", "kind": "web", "path": "/apps/mail", "version": "1"},
            {"id": "helpdesk", "name": "Help Desk", "description": "Cases, queues and the Help Desk agent.", "icon": "help-faq", "kind": "web", "path": "/apps/helpdesk", "version": "1"},
            {"id": "crm", "name": "CRM", "description": "Accounts, contacts, deals.", "icon": "x-office-address-book", "kind": "web", "path": "/apps/crm", "version": "1"},
            {"id": "knowledgebase", "name": "Knowledgebase", "description": "Articles and procedures, searched by agents and people.", "icon": "accessories-dictionary", "kind": "web", "path": "/apps/kb", "version": "1"}]

    def apps_answer(self, base):
        return {"ok": True, "surface": SURFACE, "apps": [dict(a, url=base + a["path"]) for a in self.APPS]}

    def answer(self, desk, base):
        ov = self.ov_block(desk)
        return {"ok": True, "surface": SURFACE,
                "desk": {k: desk[k] for k in ("id", "name", "status", "presence", "last_seen_at")},
                "office": {"name": self.name, "url": base}, "owner": desk["owner"],
                "endpoints": {**self.endpoints(base), "overlay": f"{base}/api/v1/desks/overlay" if ov else None}, "heartbeat_s": self.heartbeat_s, "overlay": ov}

    def public(self):
        return {"office": self.name, "codes": {c: v for c, v in self.codes.items()},
                "desks": [dict(d, token_sha256=hashlib.sha256(d["token"].encode()).hexdigest()[:16], token=None) for d in self.desks.values()],
                "heartbeats": self.heartbeats[-50:], "chats": self.chats[-50:], "mcp": self.mcp[-50:],
                "nodes": [dict({k: v for k, v in n.items() if not k.startswith("_")}, token_sha256=hashlib.sha256(n["token"].encode()).hexdigest()[:16], token=None)
                          for n in self.nodes.values()], "alerts": self.alerts[-50:]}


class Handler(BaseHTTPRequestHandler):
    office: Office = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("mock-office: " + (fmt % args) + "\n")

    # -- plumbing
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"_bad": True}

    def send(self, status, obj, extra=None):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def err(self, status, code, message):
        self.send(status, {"error": code, "message": message})

    def base(self):
        return f"http://{self.headers.get('Host') or 'localhost'}"

    def desk_from_bearer(self):
        """(desk, None) for a live token; (None, (status, code, message)) otherwise."""
        auth = self.headers.get("Authorization") or ""
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        o = self.office
        with o.lock:
            did = o.tokens.get(tok)
            desk = o.desks.get(did) if did else None
        if not desk:
            return None, (401, "unauthorized", "provide a valid desk token as a Bearer token")
        if desk["status"] == "retired":
            return None, (410, "retired", f"desk #{desk['id']} was retired by the office")
        return desk, None

    def node_from_bearer(self):
        """(node, None) for a live node token; (None, (status, code, message)) otherwise."""
        auth = self.headers.get("Authorization") or ""
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        o = self.office
        with o.lock:
            nid = o.node_tokens.get(tok)
            node = o.nodes.get(nid) if nid else None
        if not node:
            return None, (401, "unauthorized", "provide a valid node token as a Bearer token")
        if node["status"] == "retired":
            return None, (410, "retired", f"node #{node['id']} was retired by the office")
        return node, None

    def estate_viewer(self):
        """A node token or a desk token opens the estate: (ok, error)."""
        node, e = self.node_from_bearer()
        if node:
            return True, None
        desk, e2 = self.desk_from_bearer()
        return (True, None) if desk else (False, e if e[0] != 401 else e2)

    # -- routes
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        o = self.office
        if p == "/api/v1/health":
            return self.send(200, {"ok": True, "office": o.name, "surface": SURFACE})
        if p == "/api/v1/estate/me":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                return self.send(200, o.node_answer(node, self.base()))
        if p == "/api/v1/estate/nodes" or p.startswith("/api/v1/estate/nodes/") or p == "/api/v1/desks/estate":
            ok, e = self.estate_viewer()
            if not ok:
                return self.err(*e)
            nid = None
            if p.startswith("/api/v1/estate/nodes/"):
                try:
                    nid = int(p.rsplit("/", 1)[1])
                except ValueError:
                    return self.err(404, "not_found", p)
            with o.lock:
                ans = o.nodes_answer(self.base(), nid)
            return self.send(200, ans) if ans else self.err(404, "not_found", f"no node #{nid}")
        if p == "/mock/nodes":
            with o.lock:
                return self.send(200, {"nodes": [o.node_row(n) for n in o.nodes.values()], "alerts": o.alerts})
        if p == "/api/v1/estate/overlay":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                return self.send(200, o.ov_answer(node))
        if p == "/api/v1/desks/overlay":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                return self.send(200, o.ov_answer(desk))
        if p == "/mock/overlay":
            with o.lock:
                return self.send(200, o.ov_public())
        if p == "/api/v1/desks/me":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.send(200, o.answer(desk, self.base()))
        if p == "/api/v1/desks/apps":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.send(200, o.apps_answer(self.base()))
        if p == "/api/v1/desks/agents":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                ans = o.agents_answer(self.base())
                ans["agents"] = o.dg_desk_agents(self.base()) + ans["agents"]     # slice 2: the directory first, the office's own agents after
                return self.send(200, ans)
        if p == "/api/v1/estate/keys":
            ok, e = self.estate_viewer()
            if not ok:
                return self.err(*e)
            with o.lock:
                return self.send(200, o.dg_keys_answer())
        if p == "/api/v1/estate/agents" or re.fullmatch(r"/api/v1/estate/agents/[0-9]+", p):
            ok, e = self.estate_viewer()
            if not ok:
                return self.err(*e)
            q = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in x)
            with o.lock:
                if p != "/api/v1/estate/agents":
                    a = o.agents.get(int(p.rsplit("/", 1)[1]))
                    return self.send(200, {"ok": True, "surface": SURFACE, "agent": o.dg_present_agent(a, self.base())}) if a else self.err(404, "not_found", "no such agent")
                return self.send(200, o.dg_agents_answer(self.base(), q.get("capability"), int(q["node"]) if q.get("node", "").isdigit() else None))
        if p == "/api/v1/estate/inbox":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            q = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in x)
            wait = min(float(q.get("wait") or 0), 25)
            deadline = time.time() + wait
            while True:
                with o.lock:
                    items = o.dg_inbox_take(node)
                if items or time.time() >= deadline:
                    return self.send(200, {"ok": True, "surface": SURFACE, "items": items, "lease_s": 120, "fetched_at": now()})
                time.sleep(0.25)
        if m := re.fullmatch(r"/api/v1/estate/tasks/(t_[0-9a-f]+)", p):
            ok, e = self.estate_viewer()
            if not ok:
                return self.err(*e)
            q = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in x)
            deadline = time.time() + min(float(q.get("wait") or 0), 60)
            while True:
                with o.lock:
                    t = o.estate_tasks.get(m.group(1))
                    if not t:
                        return self.err(404, "not_found", "no such task")
                    if t["state"] not in ("queued", "leased", "running") or time.time() >= deadline:
                        return self.send(200, {"ok": True, "surface": SURFACE, "task": o.dg_present_task(t)})
                time.sleep(0.25)
        if p == "/api/v1/estate/actions" or (m := re.fullmatch(r"/api/v1/estate/actions/(a_[0-9a-f]+)", p)):
            ok, e = self.estate_viewer()
            if not ok:
                return self.err(*e)
            q = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in x)
            with o.lock:
                if p == "/api/v1/estate/actions":
                    return self.send(200, {"ok": True, "surface": SURFACE, "actions": [o.dg_present_action(x) for x in o.estate_actions.values()]})
            deadline = time.time() + min(float(q.get("wait") or 0), 60)
            while True:
                with o.lock:
                    x = o.estate_actions.get(m.group(1))
                    if not x:
                        return self.err(404, "not_found", "no such action")
                    if x["state"] not in ("queued", "leased") or time.time() >= deadline:
                        return self.send(200, {"ok": True, "surface": SURFACE, "action": o.dg_present_action(x)})
                time.sleep(0.25)
        if p == "/api/v1/desks/inbox":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            q = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in x)
            deadline = time.time() + min(float(q.get("wait") or 0), 25)
            while True:
                with o.lock:
                    ans = o.dg_desk_inbox(bool(q.get("all")), int(q.get("since") or 0))
                if ans["items"] or time.time() >= deadline:
                    return self.send(200, ans)
                time.sleep(0.25)
        if p == "/mock/delegation":
            with o.lock:
                return self.send(200, o.dg_public())
        if p.startswith("/api/v1/desks/agents/") and p.endswith("/activity"):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            aid = p.split("/")[5]
            if aid.isdigit():
                with o.lock:
                    rows = [{"ts": t["created_at"], "kind": "task", "actor": t["originator"], "summary": f"task {t['id']} {t['state']}: {t['input']['text'][:60]}"}
                            for t in sorted(o.estate_tasks.values(), key=lambda t: t["created_at"], reverse=True) if t["agent_id"] == int(aid)]
                    return self.send(200, {"ok": True, "surface": SURFACE, "activity": rows[:50]})
            if aid not in o.tasks:
                return self.err(404, "not_found", f"no agent {aid}")
            with o.lock:
                return self.send(200, o.agent_activity(aid, desk))
        if p.startswith("/agents/"):
            aid = p.split("/")[2]
            a = next((x for x in o.AGENTS if x["id"] == aid), None)
            if not a:
                return self.err(404, "not_found", f"no agent {aid}")
            # Slice 9: the desk token on the first request signs the page in; a session cookie keeps it signed in.
            desk, cookie = None, None
            if (self.headers.get("Authorization") or "").lower().startswith("bearer "):
                desk, _e = self.desk_from_bearer()
                if desk:
                    cookie = secrets.token_hex(12)
                    with o.lock:
                        o.sessions[cookie] = desk["id"]
            if not desk:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "office_session":
                        with o.lock:
                            did = o.sessions.get(v)
                        desk = o.desks.get(did) if did else None
            who = (f"<p>signed in as {desk['owner']['email']} at desk #{desk['id']} ({desk['name']})</p>" if desk
                   else "<p>not signed in (open this page from the Agents app on an enrolled desk)</p>")
            html = (f"<!doctype html><html><head><meta charset='utf-8'><title>{a['name']} · {o.name}</title></head>"
                    f"<body style='font-family:sans-serif;margin:2em'><h1>{a['name']}</h1><p>{a['description']}</p>{who}"
                    f"<p>This is {o.name}'s page for agent <code>{aid}</code> (mock). Capabilities: {', '.join(a['capabilities'])}.</p></body></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(html)))
            if cookie:
                self.send_header("Set-Cookie", f"office_session={cookie}; Path=/; HttpOnly; SameSite=Lax")
            self.end_headers()
            self.wfile.write(html); return
        if p in ("/desk-models", "/desk-models/"):
            return self.send(200, {"ok": True, "office": o.name})
        if p == "/desk-models/v1/models":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "office"} for m in o.models]})
        if p == "/mock/state":
            with o.lock:
                return self.send(200, o.public())
        return self.err(404, "not_found", p)

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        o = self.office
        b = self.body()
        if b.get("_bad"):
            return self.err(400, "invalid", "malformed JSON")
        if p == "/api/v1/desks/enroll":
            return self.enroll(b)
        if p == "/api/v1/estate/join":
            return self.join(b)
        if p == "/api/v1/estate/heartbeat":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            presence = b.get("presence") or "online"
            if presence not in ("online", "offline"):
                return self.err(400, "invalid", "presence must be online or offline")
            with o.lock:
                node["last_seen_at"], node["_seen"] = now(), time.time()
                if b.get("app_version"):
                    node["app_version"] = b["app_version"]
                if isinstance(b.get("facts"), dict):
                    node["facts"].update(b["facts"])
                if isinstance(b.get("report"), dict):
                    if len(json.dumps(b["report"])) > 32 * 1024:
                        return self.err(400, "invalid", "the report is over 32 KB")
                    node["report"], node["last_report_at"] = b["report"], now()
                    o.evaluate(node)
                o.set_presence(node, presence)
                o.heartbeats.append({"ts": node["last_seen_at"], "node_id": node["id"], "presence": presence, "report": isinstance(b.get("report"), dict)})
                registered = None
                if isinstance(b.get("agents"), list):              # slice 2: the manifests, with the report's unit states
                    units = {a.get("name"): a.get("active") for a in ((b.get("report") or {}).get("agents") or []) if isinstance(a, dict)}
                    registered = o.dg_register(node, [dict(m, unit_state=units.get(m.get("name"), m.get("unit_state"))) for m in b["agents"] if isinstance(m, dict)])
                return self.send(200, {**o.node_answer(node, self.base()), "overlay_changed": o.ov_changed(node), "agents_registered": registered})
        if p == "/api/v1/estate/leave":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                node["status"], node["retired_at"] = "retired", now()
                o.set_presence(node, "offline")
                o.clear_alerts(node, set())
                o.ov_free(node)
                o.dg_deregister(node)
                o.node_tokens = {t: n for t, n in o.node_tokens.items() if n != node["id"]}
            return self.send(200, {"ok": True, "surface": SURFACE, "node": {"id": node["id"], "status": "retired"}})
        if p == "/api/v1/estate/overlay/key":
            auth = self.headers.get("Authorization") or ""
            tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            member, e = (self.desk_from_bearer() if tok.startswith("desk_") else self.node_from_bearer())
            if e:
                return self.err(*e)
            import re as _re
            key = b.get("overlay_public_key")
            if not isinstance(key, str) or not _re.fullmatch(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=", key):
                return self.err(400, "invalid", "overlay_public_key is a WireGuard public key (32 bytes, base64)")
            with o.lock:
                o.ov_rotate(member, key)
                return self.send(200, {"ok": True, "surface": SURFACE, "overlay": o.ov_block(member)})
        if p == "/mock/report":
            with o.lock:
                node = o.nodes.get(b.get("node_id"))
                if not node:
                    return self.err(404, "not_found", "no such node")
                node["report"], node["last_report_at"] = b.get("report") or {}, now()
                o.evaluate(node)
                return self.send(200, {"ok": True, "node": o.node_row(node), "alerts": o.open_alerts(node)})
        if p == "/mock/alert":
            with o.lock:
                node = o.nodes.get(b.get("node_id"))
                if not node:
                    return self.err(404, "not_found", "no such node")
                a = o.raise_alert(node, b.get("kind") or "manual", b.get("severity") or "warning", b.get("title") or "raised by hand", key=b.get("key"))
                return self.send(200, {"ok": True, "alert": a})
        if p == "/api/v1/desks/heartbeat":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            presence = b.get("presence") or "online"
            if presence not in ("online", "offline"):
                return self.err(400, "invalid", "presence must be online or offline")
            with o.lock:
                desk["presence"], desk["last_seen_at"] = presence, now()
                for k in ("app_version", "mcp_surface_version"):
                    if b.get(k):
                        desk[k] = b[k]
                if isinstance(b.get("facts"), dict):
                    desk["facts"].update(b["facts"])
                o.heartbeats.append({"ts": desk["last_seen_at"], "desk_id": desk["id"], "presence": presence})
                return self.send(200, {**o.answer(desk, self.base()), "overlay_changed": o.ov_changed(desk), "inbox_unread": sum(1 for i in o.inbox if i["status"] == "unread")})
        if p == "/api/v1/desks/leave":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                desk["status"], desk["retired_at"], desk["presence"] = "retired", now(), "offline"
                o.ov_free(desk)
                o.tokens = {t: d for t, d in o.tokens.items() if d != desk["id"]}
            return self.send(200, {"ok": True, "surface": SURFACE, "desk": {"id": desk["id"], "status": "retired"}})
        if p == "/desk-models/v1/chat/completions":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.chat(b, desk)
        if p in ("/mcp/records", "/mcp/activity", "/mcp/memory"):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.mcp(p, b, desk)
        if p.startswith("/api/v1/desks/agents/") and p.endswith("/tasks"):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            aid = p.split("/")[5]
            if aid.isdigit():
                with o.lock:
                    a = o.agents.get(int(aid))
                    if not a:
                        return self.err(404, "not_found", f"no agent {aid}")
                    return self.send(200, {"jsonrpc": "2.0", "id": b.get("id"), **o.dg_rpc(a, b, desk, self.base())})
            if aid not in o.tasks:
                return self.err(404, "not_found", f"no agent {aid}")
            with o.lock:
                return self.send(200, o.agent_rpc(aid, b, desk))
        if m := re.fullmatch(r"/api/v1/estate/agents/([0-9]+)/tasks", p):
            auth = self.headers.get("Authorization") or ""
            tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            member, e = (self.desk_from_bearer() if tok.startswith("desk_") else self.node_from_bearer())
            if e:
                return self.err(*e)
            with o.lock:
                a = o.agents.get(int(m.group(1)))
                if not a:
                    return self.err(404, "not_found", "no such agent")
                return self.send(200, {"jsonrpc": "2.0", "id": b.get("id"), **o.dg_rpc(a, b, member, self.base())})
        if p == "/api/v1/estate/agents":
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            if not isinstance(b.get("agents"), list):
                return self.err(400, "invalid", "agents is a list of manifests")
            with o.lock:
                r = o.dg_register(node, [m for m in b["agents"] if isinstance(m, dict)])
                return self.send(200, {"ok": True, "surface": SURFACE, **r, "agents": o.dg_agents_answer(self.base(), None, node["id"])["agents"]})
        if p == "/api/v1/estate/tasks":
            auth = self.headers.get("Authorization") or ""
            tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            member, e = (self.desk_from_bearer() if tok.startswith("desk_") else self.node_from_bearer())
            if e:
                return self.err(*e)
            env = (b.get("params") or {}).get("envelope") or {}
            tgt = env.get("target") or {} if isinstance(env, dict) else {}
            with o.lock:
                a = None
                if isinstance(tgt.get("agent"), str):
                    a = next((x for x in o.agents.values() if x["status"] == "active" and x["name"] == tgt["agent"] and (not tgt.get("node") or o.dg_node_ref(o.nodes[x["location_id"]]) == tgt["node"])), None)
                elif isinstance(tgt.get("capability"), str):
                    orig = dict(env.get("originator") or {}, member_id=1 if "owner" in member else None)
                    for x in sorted(o.agents.values(), key=lambda x: (o.nodes[x["location_id"]]["presence"] != "online", x["name"])):
                        if x["status"] == "active" and x["tasks"] and tgt["capability"].lower() in x["capabilities"] and o.dg_accepts(x, orig):
                            a = x; break
                if not a:
                    return self.send(200, {"jsonrpc": "2.0", "id": b.get("id"), "error": {"code": -32004, "message": "No agent in the directory answers that target.", "data": {"reason": "no_agent"}}})
                return self.send(200, {"jsonrpc": "2.0", "id": b.get("id"), **o.dg_rpc(a, b, member, self.base())})
        if m := re.fullmatch(r"/api/v1/estate/inbox/([ta]_[0-9a-f]+)/result", p):
            node, e = self.node_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                st, ans = o.dg_result(node, m.group(1), b)
            return self.send(st, ans)
        if m := re.fullmatch(r"/api/v1/estate/nodes/([0-9]+)/actions", p):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                node = o.nodes.get(int(m.group(1)))
                if not node or node["status"] != "active":
                    return self.err(404, "not_found", "no such node")
                st, ans = o.dg_action_create(node, desk, b)
            return self.send(st, ans)
        if m := re.fullmatch(r"/api/v1/desks/inbox/([0-9]+)/(reply|decide|read)", p):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                st, ans = o.dg_inbox_answer(desk, int(m.group(1)), m.group(2), b)
            return self.send(st, ans)
        if p == "/api/v1/desks/key":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            key = b.get("public_key")
            if not isinstance(key, str) or not o.E.raw_public(key):
                return self.err(400, "invalid", "public_key is an ssh-ed25519 line")
            with o.lock:
                desk["public_key"] = key.strip()
            return self.send(200, {"ok": True, "surface": SURFACE, "node": o.dg_node_ref(desk), "public_key": key.strip()})
        if p == "/mock/task":
            with o.lock:
                st, ans = o.dg_inject_task(b, self.base())
            return self.send(st, ans)
        if p == "/mock/inbox":
            with o.lock:
                item = o.dg_inbox_post(b.get("kind") or "decision_needed", b.get("subject") or "a question from the office", b.get("body") or "", b.get("from") or "agent:helpdesk", "coordinator", b.get("task_id"), b.get("options") or ["approve", "deny"])
            return self.send(201, {"ok": True, "item": item})
        if p == "/mock/retire":
            with o.lock:
                targets = [o.desks[b["desk_id"]]] if b.get("desk_id") in o.desks else list(o.desks.values())
                for d in targets:
                    d["status"], d["retired_at"], d["presence"] = "retired", now(), "offline"
                    o.ov_free(d)
            return self.send(200, {"ok": True, "retired": [d["id"] for d in targets]})
        if p == "/mock/code":
            with o.lock:
                o.codes[str(b.get("code") or secrets.token_hex(4))] = {"used": False, "kind": "node" if b.get("kind") in ("node", "server", "inference") else "desk"}
            return self.send(200, {"ok": True, "codes": list(o.codes)})
        return self.err(404, "not_found", p)

    def enroll(self, b):
        o = self.office
        if b.get("surface") not in (None, SURFACE):
            return self.err(400, "invalid", f"surface {b.get('surface')} is not served; this office speaks surface {SURFACE}")
        code = str(b.get("code") or "")
        with o.lock:
            c = o.codes.get(code)
            if not c or c["used"] or c.get("kind", "desk") != "desk":
                return self.err(403, "bad_code", "the enrolment code is unknown, expired, already used or minted for a node")
            c["used"] = True
            did = o.next_id; o.next_id += 1
            name = (b.get("name") or "").strip() or f"{b.get('hostname') or 'a'}'s desk"
            if any(d["name"] == name and d["status"] == "active" for d in o.desks.values()):
                return self.err(409, "name_taken", f"a desk named {name!r} already exists")
            tok = "desk_" + secrets.token_hex(24)
            facts = {k: b.get(k) for k in ("hostname", "os_platform", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb", "machine_id") if b.get(k) is not None}
            desk = {"id": did, "name": name, "status": "active", "presence": "online", "last_seen_at": now(), "enrolled_at": now(),
                    "owner": {"member_id": 1, "email": "person@mock.office", "display_name": "Mock Person"},
                    "principal": b.get("principal"), "app_version": b.get("app_version"), "mcp_surface_version": b.get("mcp_surface_version"),
                    "facts": facts, "token": tok, "code": code}
            e = o.ov_join(desk, b, allow_hub=False)
            if e:
                return self.err(*e)
            if isinstance(b.get("public_key"), str) and o.E.raw_public(b["public_key"]):
                desk["public_key"] = b["public_key"].strip()           # slice 2: the desk's signing key
            o.desks[did] = desk; o.tokens[tok] = did
            ans = o.answer(desk, self.base()); ans["token"] = tok
        return self.send(201, ans)

    def join(self, b):
        """A server or inference node joins (the estate contract): the code must be a node code."""
        o = self.office
        if b.get("surface") not in (None, SURFACE):
            return self.err(400, "invalid", f"surface {b.get('surface')} is not served; this office speaks surface {SURFACE}")
        kind = b.get("kind") or "server"
        if kind not in ("server", "inference"):
            return self.err(400, "invalid", "kind must be server or inference (a desk enrols at /api/v1/desks/enroll)")
        code = str(b.get("code") or "")
        with o.lock:
            c = o.codes.get(code)
            if not c or c["used"] or c.get("kind") != "node":
                return self.err(403, "bad_code", "the code is unknown, expired, already used or minted for a desk")
            c["used"] = True
            nid = o.next_node_id; o.next_node_id += 1
            name = (b.get("name") or "").strip() or b.get("hostname") or f"node-{nid}"
            if any(n["name"] == name and n["status"] == "active" for n in o.nodes.values()):
                return self.err(409, "name_taken", f"a node named {name!r} already exists")
            tok = "node_" + secrets.token_hex(24)
            facts = {k: b.get(k) for k in ("hostname", "os_platform", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb", "machine_id") if b.get(k) is not None}
            node = {"id": nid, "kind": kind, "name": name, "status": "active", "presence": "online", "last_seen_at": now(), "_seen": time.time(), "enrolled_at": now(),
                    "last_report_at": None, "report": None, "principal": b.get("principal"), "public_key": b.get("public_key"), "app_version": b.get("app_version"),
                    "components": b.get("components") or [], "facts": facts, "token": tok, "code": code,
                    "enrolled_by": {"member_id": 1, "email": "person@mock.office", "display_name": "Mock Person"}}
            e = o.ov_join(node, b, allow_hub=True)
            if e:
                return self.err(*e)
            o.nodes[nid] = node; o.node_tokens[tok] = nid
            ans = o.node_answer(node, self.base()); ans["token"] = tok; ans["enrolled_by"] = node["enrolled_by"]
        return self.send(201, ans)

    def chat(self, b, desk):
        o = self.office
        model = b.get("model") or (o.models[0] if o.models else "office")
        if o.models and model not in o.models:
            return self.err(404, "model_not_found", f"no model {model!r} at this office")
        msgs = b.get("messages") or []
        last = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
        if isinstance(last, list):
            last = " ".join(x.get("text", "") for x in last if isinstance(x, dict))
        text = f"office reply to: {last}"
        n_in = sum(len(str(m.get("content") or "")) // 4 + 1 for m in msgs); n_out = len(text) // 4 + 1
        rid = "chatcmpl-" + secrets.token_hex(6)
        with o.lock:
            o.chats.append({"ts": now(), "desk_id": desk["id"], "model": model, "prompt": str(last)[:120], "stream": bool(b.get("stream"))})
        usage = {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out}
        if not b.get("stream"):
            return self.send(200, {"id": rid, "object": "chat.completion", "created": int(time.time()), "model": model,
                                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}], "usage": usage},
                             {"x-request-id": rid})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.send_header("x-request-id", rid); self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(obj):
            data = ("data: " + json.dumps(obj) + "\n\n").encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        head = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
        for piece in (text[:len(text) // 2], text[len(text) // 2:]):
            chunk(dict(head, choices=[{"index": 0, "delta": {"role": "assistant", "content": piece}, "finish_reason": None}]))
        chunk(dict(head, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]))
        chunk(dict(head, choices=[], usage=usage))
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode() + done + b"\r\n0\r\n\r\n")

    def mcp(self, path, b, desk):
        o = self.office
        server = path.rsplit("/", 1)[1]
        method, mid = b.get("method"), b.get("id")
        with o.lock:
            o.mcp.append({"ts": now(), "desk_id": desk["id"], "server": server, "method": method})
        if method == "initialize":
            res = {"protocolVersion": "2025-06-18", "serverInfo": {"name": f"mock-office-{server}", "version": "0"}, "capabilities": {"tools": {}}}
        elif method == "tools/list":
            res = {"tools": [{"name": "office.ping", "description": "answers pong, as the desk's owner", "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            res = {"content": [{"type": "text", "text": f"pong from {o.name} ({server}) for {desk['owner']['email']} at desk #{desk['id']}"}]}
        elif method == "notifications/initialized":
            self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers(); return
        else:
            return self.send(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})
        return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": res})


def main(argv=None):
    ap = argparse.ArgumentParser(description="mock Business OS office for desk tests")
    ap.add_argument("--port", type=int, default=18080); ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--code", action="append", default=[]); ap.add_argument("--name", default="Mock Office")
    ap.add_argument("--models", default="office-7b,office-embed"); ap.add_argument("--heartbeat-s", type=int, default=300)
    ap.add_argument("--node-code", action="append", default=[]); ap.add_argument("--report-s", type=int, default=300)
    ap.add_argument("--node-heartbeat-s", type=int, default=None, help="nodes' heartbeat interval (default: --heartbeat-s)")
    ap.add_argument("--overlay-range", default="100.100.0.0/16", help="the estate's overlay range (slice 1b)"); ap.add_argument("--no-overlay", action="store_true")
    ap.add_argument("--overlay-spoke", action="append", default=[], help="NAME=PUBKEY: a fake spoke with an address, so a hub under test has a peer")
    a = ap.parse_args(argv)
    Handler.office = Office(a.name, a.code or ["mock-code"], [m.strip() for m in a.models.split(",") if m.strip()], a.heartbeat_s, a.node_code, a.report_s, a.node_heartbeat_s,
                            None if a.no_overlay else a.overlay_range, a.overlay_spoke)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True

    def sweeper():
        while True:
            time.sleep(2)
            try:
                Handler.office.sweep()
            except Exception as e:
                sys.stderr.write(f"mock-office: sweep: {e}\n")
    threading.Thread(target=sweeper, daemon=True).start()
    sys.stderr.write(f"mock-office: {a.name} on http://{a.host}:{a.port} codes={list(Handler.office.codes)} models={Handler.office.models}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
