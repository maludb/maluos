"""The watching agents' checks (db/196; MaluOS Phase 14 slice 4c, maluos docs/phase14-watching-agents.md).

Three playbooks read what the kernel already holds about the estate's nodes: each node's last report (its postgres,
linux and security parts, written by the node's collectors) and the samples of its numbers over time (db/195).
Nothing here connects to another server, asks a model or reads a log line: a check is a number against a threshold.

    watch_postgres   the database administrator   every node whose report has a postgres part
    watch_linux      the Linux administrator      every server node
    watch_security   the security officer         every server node

This module is the pure half: (node, samples, thresholds, what the last pass knew) -> checks. playbooks.py stores
them as probes (`node:<id>:<area>:<check>`) and records a decision when a status changes, as `health` does.
Thresholds live in the agent's versioned runtime_config (`thresholds`, `expected_ports`); the defaults are here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HEARTBEAT_S = 60

DEFAULTS = {
    # PostgreSQL
    "pg_connections_pct_warn": 80, "pg_connections_pct_fail": 95,
    "pg_transaction_s_warn": 3600, "pg_transaction_s_fail": 14400,
    "pg_lock_wait_s_warn": 60, "pg_lock_wait_s_fail": 600,
    "pg_dead_pct_warn": 20, "pg_vacuum_age_s": 86400,
    "pg_xid_age_warn": 1_000_000_000, "pg_xid_age_fail": 1_500_000_000,
    "pg_certificate_days_warn": 30, "pg_certificate_days_fail": 7,
    "pg_log_errors_warn": 50, "pg_replication_lag_mb_warn": 1024,
    "pg_superuser_hours": 24,
    # Linux
    "silent_heartbeats": 3,
    "disk_pct_warn": 85, "disk_pct_fail": 95, "disk_days_warn": 14, "disk_days_fail": 3, "disk_trend_min_hours": 6,
    "inodes_pct_warn": 90, "reboot_days_warn": 7, "memory_available_pct_warn": 5,
    # security
    "failed_logins_warn": 20, "failed_logins_fail": 200, "failed_logins_one_source_warn": 10,
    "security_updates_days_warn": 3,
}

# What may listen beyond loopback, by the node's role ("proto/port" or "proto/low-high"). A port outside its set is a
# finding until a person adds it to the agent's runtime_config.expected_ports (a versioned change).
EXPECTED_PORTS = {
    "*": ["tcp/22", "udp/68", "udp/546", "udp/5353", "udp/51820"],
    "kernel": ["tcp/80", "tcp/443", "tcp/8081"],
    "application-server": ["tcp/80", "tcp/443", "tcp/9000-9999"],
    "database-server": ["tcp/5432", "tcp/5329"],
}


@dataclass
class Check:
    area: str                     # pg | linux | sec
    check: str                    # the check's name within the area; with a subject: "disk:/var"
    status: str                   # ok | warning | failed
    detail: str                   # one sentence for a person; numbers, names of units, roles, mounts, addresses
    measured: dict = field(default_factory=dict)


def _thr(thr: dict, name: str) -> float:
    return float(thr.get(name, DEFAULTS[name]))


def _level(value, warn, fail=None, low=False) -> str:
    """ok | warning | failed for a value against its thresholds; `low`: smaller is worse."""
    if value is None:
        return "ok"
    if low:
        return "failed" if fail is not None and value <= fail else "warning" if value <= warn else "ok"
    return "failed" if fail is not None and value >= fail else "warning" if value >= warn else "ok"


def _hm(seconds) -> str:
    s = int(seconds or 0)
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min" if s >= 120 else f"{s} s"


def _node(node: dict) -> str:
    return str(node.get("name") or f"node {node.get('location_id')}")


# ------------------------------------------------------------------------------------------- PostgreSQL
def postgres_checks(node: dict, samples: list[dict], thr: dict, prev: dict, now_s: float) -> list[Check]:
    """`prev`: check name -> the measured dict the last pass stored (the superusers known, when a new one was seen)."""
    pg = (node.get("report") or {}).get("postgres")
    if not isinstance(pg, dict):
        return []
    n, out = _node(node), []
    pct = pg.get("connections_pct")
    out.append(Check("pg", "connections", _level(pct, _thr(thr, "pg_connections_pct_warn"), _thr(thr, "pg_connections_pct_fail")),
                     f"{n}: {pg.get('connections')} of {pg.get('max_connections')} connections in use ({pct} %).", {"connections_pct": pct}))
    lt = pg.get("longest_transaction") if isinstance(pg.get("longest_transaction"), dict) else None
    secs = lt.get("seconds") if lt else 0
    out.append(Check("pg", "long_transaction", _level(secs, _thr(thr, "pg_transaction_s_warn"), _thr(thr, "pg_transaction_s_fail")),
                     (f"{n}: a transaction has been open for {_hm(secs)} (pid {lt.get('pid')}, database {lt.get('database')}, role {lt.get('role')}, {lt.get('state')})."
                      if lt else f"{n}: no open transaction."), {"seconds": secs, "pid": lt.get("pid") if lt else None, "state": lt.get("state") if lt else None}))
    lw = pg.get("longest_lock_wait") if isinstance(pg.get("longest_lock_wait"), dict) else None
    secs = lw.get("seconds") if lw else 0
    out.append(Check("pg", "lock_wait", _level(secs, _thr(thr, "pg_lock_wait_s_warn"), _thr(thr, "pg_lock_wait_s_fail")),
                     (f"{n}: a session has waited {_hm(secs)} for a lock (pid {lw.get('pid')}, database {lw.get('database')}); {pg.get('lock_waiters')} waiting in all."
                      if lw else f"{n}: nobody waits for a lock."), {"seconds": secs, "waiters": pg.get("lock_waiters")}))
    worst = None
    for t in pg.get("dead_tuples") or []:
        if not isinstance(t, dict):
            continue
        age = t.get("vacuum_age_s")
        if (t.get("dead_pct") or 0) >= _thr(thr, "pg_dead_pct_warn") and (age is None or age >= _thr(thr, "pg_vacuum_age_s")):
            if worst is None or (t.get("dead_pct") or 0) > (worst.get("dead_pct") or 0):
                worst = t
    out.append(Check("pg", "dead_tuples", "warning" if worst else "ok",
                     (f"{n}: {worst.get('dead_pct')} % of {worst.get('database')}.{worst.get('table')} is dead rows and it was "
                      + ("never vacuumed." if worst.get("vacuum_age_s") is None else f"last vacuumed {_hm(worst.get('vacuum_age_s'))} ago.")
                      if worst else f"{n}: no table with many dead rows and an old vacuum."),
                     {"dead_pct": worst.get("dead_pct") if worst else 0}))
    age = pg.get("xid_age")
    out.append(Check("pg", "xid_age", _level(age, _thr(thr, "pg_xid_age_warn"), _thr(thr, "pg_xid_age_fail")),
                     f"{n}: the oldest transaction id is {age:,} transactions old (wraparound protection starts near 2,000,000,000)." if isinstance(age, int)
                     else f"{n}: transaction-id age not reported.", {"xid_age": age}))
    days = pg.get("certificate_days")
    if days is not None:
        out.append(Check("pg", "certificate", _level(days, _thr(thr, "pg_certificate_days_warn"), _thr(thr, "pg_certificate_days_fail"), low=True),
                         f"{n}: the server certificate expires in {days} days." if days >= 0 else f"{n}: the server certificate expired {-days} days ago.", {"days": days}))
    lg = pg.get("log") if isinstance(pg.get("log"), dict) else None
    if lg is not None:
        bad = (lg.get("fatal") or 0) + (lg.get("panic") or 0)
        st = "failed" if lg.get("panic") else "warning" if bad or (lg.get("error") or 0) >= _thr(thr, "pg_log_errors_warn") else "ok"
        out.append(Check("pg", "log", st, f"{n}: the server log gained {lg.get('error') or 0} ERROR, {lg.get('fatal') or 0} FATAL and {lg.get('panic') or 0} PANIC lines since the last report.",
                         {"error": lg.get("error") or 0, "fatal": lg.get("fatal") or 0, "panic": lg.get("panic") or 0}))
    lag = pg.get("replication_lag_mb")
    had = any((s.get("numbers") or {}).get("pg.replicas", 0) > 0 for s in samples)
    reps = pg.get("replicas") or 0
    st = "warning" if (had and reps == 0) or (lag is not None and lag >= _thr(thr, "pg_replication_lag_mb_warn")) else "ok"
    if had or reps:
        out.append(Check("pg", "replication", st, f"{n}: {reps} replica(s) attached" + (f", the furthest {lag} MB behind." if lag is not None else ".")
                         + (" There was one in the last day." if had and reps == 0 else ""), {"replicas": reps, "lag_mb": lag}))
    # superusers: the first pass learns them; one that appears later is a finding for pg_superuser_hours, then known
    su = sorted(x for x in (pg.get("superusers") or []) if isinstance(x, str))
    before = prev.get("superusers") if isinstance(prev.get("superusers"), dict) else None
    known = list(before.get("known") or []) if before else su
    fresh = {k: v for k, v in ((before or {}).get("new") or {}).items() if k in su and now_s - float(v) < _thr(thr, "pg_superuser_hours") * 3600}
    known += [k for k in ((before or {}).get("new") or {}) if k not in fresh]        # its day as a finding is over: known from now on
    for name in su:
        if name not in known and name not in fresh:
            fresh[name] = now_s
    known = sorted(set(x for x in known if x in su) | set(x for x in su if x not in fresh))
    out.append(Check("pg", "superusers", "warning" if fresh else "ok",
                     (f"{n}: a superuser appeared beside postgres: {', '.join(sorted(fresh))}." if fresh
                      else f"{n}: {len(su)} superuser(s) beside postgres, none new."), {"known": known, "new": fresh}))
    return out


# ------------------------------------------------------------------------------------------- Linux
def disk_forecast(samples: list[dict], key: str, min_hours: float) -> float | None:
    """Days until `key` (a used percentage) reaches 100 at the pace of the samples: a least-squares line over them.
    None when there is too little history, or it does not grow."""
    pts = [(-float(s["age_s"]), float(s["numbers"][key])) for s in samples
           if isinstance(s.get("numbers"), dict) and isinstance(s["numbers"].get(key), (int, float)) and s.get("age_s") is not None]
    if len(pts) < 4 or (max(p[0] for p in pts) - min(p[0] for p in pts)) < min_hours * 3600:
        return None
    mx, my = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / den          # percent per second
    if slope <= 0:
        return None
    return max(0.0, (100.0 - pts[-1][1]) / slope / 86400)


def linux_checks(node: dict, samples: list[dict], thr: dict, prev: dict, now_s: float) -> list[Check]:
    n, rep, out = _node(node), node.get("report") or {}, []
    silent = node.get("silent_s")
    limit = _thr(thr, "silent_heartbeats") * HEARTBEAT_S
    gone = node.get("presence") != "online" or (silent is not None and silent > limit)
    out.append(Check("linux", "reachable", "failed" if gone else "ok",
                     f"{n} has been silent for {_hm(silent)}." if gone and silent is not None else f"{n} is offline." if gone else f"{n} is online.",
                     {"silent_s": silent}))
    if gone:
        return out                      # a silent node's last report is old news: nothing else is judged on it
    for d in rep.get("disk") or []:
        if not isinstance(d, dict) or not isinstance(d.get("mount"), str):
            continue
        used = d.get("used_pct")
        days = disk_forecast(samples, "disk." + d["mount"], _thr(thr, "disk_trend_min_hours"))
        st = _level(used, _thr(thr, "disk_pct_warn"), _thr(thr, "disk_pct_fail"))
        if days is not None and st != "failed":
            st = "failed" if days <= _thr(thr, "disk_days_fail") else "warning" if days <= _thr(thr, "disk_days_warn") else st
        out.append(Check("linux", "disk:" + d["mount"], st,
                         f"{n}: {d['mount']} is {used} % full" + (f" and fills in about {days:.0f} day(s) at this pace." if days is not None and days <= _thr(thr, "disk_days_warn") else "."),
                         {"used_pct": used, "days_left": round(days, 1) if days is not None else None}))
    lx = rep.get("linux") if isinstance(rep.get("linux"), dict) else None
    if lx is not None:
        failed = [u for u in lx.get("failed_units") or [] if isinstance(u, str)]
        out.append(Check("linux", "failed_units", "warning" if failed else "ok",
                         f"{n}: {len(failed)} failed unit(s): {', '.join(failed[:6])}." if failed else f"{n}: no failed unit.", {"failed": failed[:20]}))
        days = lx.get("reboot_required_days")
        out.append(Check("linux", "reboot", "warning" if days is not None and days >= _thr(thr, "reboot_days_warn") else "ok",
                         f"{n}: a reboot has been pending for {days} day(s)." if days is not None else f"{n}: no reboot pending.", {"days": days}))
        sync = lx.get("clock_synced")
        out.append(Check("linux", "clock", "warning" if sync is False else "ok",
                         f"{n}: the clock is not synchronised." if sync is False else f"{n}: the clock is synchronised." if sync else f"{n}: clock sync not reported.", {"synced": sync}))
        ino = lx.get("inodes") if isinstance(lx.get("inodes"), dict) else None
        if ino:
            out.append(Check("linux", "inodes", _level(ino.get("used_pct"), _thr(thr, "inodes_pct_warn")),
                             f"{n}: {ino.get('used_pct')} % of the inodes on {ino.get('mount')} are used.", {"used_pct": ino.get("used_pct")}))
    m = rep.get("memory") if isinstance(rep.get("memory"), dict) else None
    if m and m.get("total_mb"):
        avail = round(100 * float(m.get("available_mb") or 0) / float(m["total_mb"]))
        out.append(Check("linux", "memory", _level(avail, _thr(thr, "memory_available_pct_warn"), low=True),
                         f"{n}: {avail} % of memory is available.", {"available_pct": avail}))
    return out


# ------------------------------------------------------------------------------------------- security
def _port_ok(proto: str, port: int, allowed: list[str]) -> bool:
    for a in allowed:
        p, _, r = str(a).partition("/")
        if p != proto:
            continue
        lo, _, hi = r.partition("-")
        try:
            if int(lo) <= port <= int(hi or lo):
                return True
        except ValueError:
            continue
    return False


def expected_ports(role: str | None, override: dict | None) -> list[str]:
    src = dict(EXPECTED_PORTS)
    for k, v in (override or {}).items():
        if isinstance(v, list):
            src[k] = list(src.get(k, [])) + [str(x) for x in v]
    return list(src.get("*", [])) + list(src.get(role or "", []))


def security_checks(node: dict, samples: list[dict], thr: dict, prev: dict, now_s: float, ports: dict | None = None) -> list[Check]:
    n, rep, out = _node(node), node.get("report") or {}, []
    if node.get("presence") != "online":
        return out
    sec = rep.get("security") if isinstance(rep.get("security"), dict) else None
    if sec is not None:
        failed = sec.get("failed_logins") or 0
        top = (sec.get("failed_sources") or [{}])[0] if sec.get("failed_sources") else {}
        st = _level(failed, _thr(thr, "failed_logins_warn"), _thr(thr, "failed_logins_fail"))
        if st == "ok" and (top.get("count") or 0) >= _thr(thr, "failed_logins_one_source_warn"):
            st = "warning"
        out.append(Check("sec", "failed_logins", st,
                         f"{n}: {failed} failed login(s) from {sec.get('failed_source_count') or 0} address(es) in {_hm(sec.get('window_s'))}"
                         + (f"; {top.get('count')} from {top.get('address')}." if top.get("address") else "."),
                         {"failed": failed, "sources": sec.get("failed_source_count") or 0}))
        new = [a for a in sec.get("new_addresses") or [] if isinstance(a, dict)]
        out.append(Check("sec", "new_login_address", "warning" if new else "ok",
                         (f"{n}: a login from an address not seen before: " + ", ".join(f"{a.get('user')} from {a.get('address')} ({a.get('method')})" for a in new[:5]) + "."
                          if new else f"{n}: no login from a new address in the last report."), {"count": len(new)}))
        allowed = expected_ports(node.get("node_role"), ports)
        odd = [f"{l.get('proto')}/{l.get('port')}" for l in sec.get("listening") or []
               if isinstance(l, dict) and isinstance(l.get("port"), int) and not _port_ok(str(l.get("proto")), l["port"], allowed)]
        out.append(Check("sec", "listening", "warning" if odd else "ok",
                         (f"{n}: listening beyond what a {node.get('node_role') or 'server'} is expected to: {', '.join(odd[:10])}." if odd
                          else f"{n}: nothing listens outside the expected set."), {"unexpected": odd[:20]}))
        cfg = sec.get("config") if isinstance(sec.get("config"), dict) else {}
        before = prev.get("config") if isinstance(prev.get("config"), dict) else None
        changed = cfg.get("changed_at")
        is_new = bool(changed) and before is not None and before.get("changed_at") != changed and before.get("digest") != cfg.get("digest")
        out.append(Check("sec", "config", "warning" if is_new else "ok",
                         (f"{n}: /etc/maluos or a unit changed at {changed}." if is_new else f"{n}: the configuration is as it was at the last pass."),
                         {"digest": cfg.get("digest"), "changed_at": changed}))
    upd = rep.get("updates") if isinstance(rep.get("updates"), dict) else None
    if upd is not None:
        pending = upd.get("security_count") or 0
        span = [s for s in samples if isinstance(s.get("numbers"), dict) and "updates.security" in s["numbers"]]
        need = _thr(thr, "security_updates_days_warn") * 86400
        old = bool(pending) and bool(span) and max(s["age_s"] for s in span) >= need and all(s["numbers"]["updates.security"] > 0 for s in span if s["age_s"] <= need)
        out.append(Check("sec", "security_updates", "warning" if old else "ok",
                         (f"{n}: {pending} security update(s) have been pending for more than {int(_thr(thr, 'security_updates_days_warn'))} days." if old
                          else f"{n}: {pending} security update(s) pending."), {"pending": pending}))
    return out


# ------------------------------------------------------------------------------------------- remedies (db/197)
# The units a watching agent may ask a node to restart, by the node's role. The node has its own list and the last word.
RESTARTABLE = {
    "database-server": ["postgresql@18-main.service", "maludb-mc2dbd.service"],
    "kernel": ["apache2.service", "maludb-api.service", "maludb-os-agent-runner.service", "maludb-os-actions-mcp.service", "maludb-os-records-mcp.service",
               "maludb-os-activity-mcp.service", "maludb-os-memory-mcp.service", "maludb-os-web.service"],
    "application-server": ["apache2.service"],
}


def remedy(c: Check, node: dict, config: dict | None = None) -> dict | None:
    """The one node action that answers a check, or None: the arguments of the kernel action estate_node_action.
    Only for a check that has an obvious, bounded answer; every one pauses for the agent's approver, and the node
    runs it only if its own lists allow. `remedies: false` in the agent's config turns them off."""
    if (config or {}).get("remedies") is False or c.status == "ok":
        return None
    base = {"location": int(node["location_id"]), "reason": c.detail[:280]}
    if c.area == "pg" and c.check == "long_transaction" and c.status == "failed" and isinstance(c.measured.get("pid"), int):
        idle = str(c.measured.get("state") or "").startswith("idle in transaction")
        return {**base, "action": "postgres_terminate" if idle else "postgres_cancel", "pid": c.measured["pid"]}
    if c.area == "linux" and c.check == "failed_units":
        allowed = RESTARTABLE.get(node.get("node_role") or "", [])
        for unit in c.measured.get("failed") or []:
            if unit in allowed:
                return {**base, "action": "restart_unit", "unit": unit}
        return None
    if c.area == "sec" and c.check == "security_updates":
        return {**base, "action": "apply_updates"}
    return None


def remedy_words(r: dict) -> str:
    return {"postgres_cancel": f"cancel the statement of backend {r.get('pid')}", "postgres_terminate": f"end the session of backend {r.get('pid')}",
            "restart_unit": f"restart {r.get('unit')}", "apply_updates": "apply the pending updates"}.get(r["action"], r["action"])


AREAS = {"watch_postgres": ("pg", postgres_checks), "watch_linux": ("linux", linux_checks), "watch_security": ("sec", security_checks)}


def applies(playbook: str, node: dict) -> bool:
    if playbook == "watch_postgres":
        return isinstance((node.get("report") or {}).get("postgres"), dict) and node.get("presence") == "online"
    return node.get("kind") == "server"


def probe_key(node: dict, c: Check) -> str:
    return f"node:{node['location_id']}:{c.area}:{c.check}"[:200]
