#!/usr/bin/env python3
"""The watching agents' checks (db/196; mcp/agent_runner/system_one/watch.py) on fixture reports: every finding the
design names is raised by exactly the report that should raise it, a healthy node raises none, and nothing in a
check's words is a statement, a command or a log line. Pure: no database, no runner, no model.

    python3 mcp/agent_runner/tests/test_watch.py
"""
import copy, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("watch", os.path.join(HERE, "..", "system_one", "watch.py"))
W = importlib.util.module_from_spec(spec)
sys.modules["watch"] = W
spec.loader.exec_module(W)

fails = 0
NOW = 1_800_000_000.0


def ok(cond, label):
    global fails
    fails += 0 if cond else 1
    print(("  ok   " if cond else "  FAIL ") + label)


def bad(checks):
    return {c.check: c.status for c in checks if c.status != "ok"}


PG = {"version": "18.6", "max_connections": 100, "connections": 12, "connections_pct": 12, "idle_in_transaction": 0, "longest_transaction": None,
      "lock_waiters": 0, "longest_lock_wait": None, "xid_age": 43502, "databases": [{"name": "maludb_os", "size_mb": 300}], "wal_mb": 80, "replicas": 0,
      "replication_lag_mb": None, "deadlocks": 0, "superusers": ["edward"], "dead_tuples": [], "log": {"error": 0, "fatal": 0, "panic": 0}, "certificate_days": 700}
LX = {"failed_units": [], "clock_synced": True, "inodes": {"mount": "/", "used_pct": 12}, "reboot_required_days": None}
SEC = {"failed_logins": 2, "failed_sources": [{"address": "203.0.113.7", "count": 2}], "failed_source_count": 1, "logins": 1, "new_addresses": [], "sudo": 3,
       "sudo_users": ["edward"], "window_s": 300, "listening": [{"proto": "tcp", "port": 22, "scope": "any"}, {"proto": "tcp", "port": 5432, "scope": "any"}],
       "config": {"digest": "aaaa", "files": 40, "changed_at": None}, "firewall": {"ufw": "disabled", "nftables": "inactive"}}
REP = {"disk": [{"mount": "/", "size_gb": 100, "used_pct": 41}], "memory": {"total_mb": 16000, "available_mb": 9000}, "load": [0.2, 0.1, 0.1],
       "updates": {"pending_count": 3, "security_count": 0, "reboot_required": False}, "postgres": PG, "linux": LX, "security": SEC}


def node(**over):
    n = {"location_id": 7, "name": "db-1", "kind": "server", "node_role": "database-server", "presence": "online", "silent_s": 20, "report": copy.deepcopy(REP)}
    rep = over.pop("report", None)
    n.update(over)
    for k, v in (rep or {}).items():
        if isinstance(v, dict) and isinstance(n["report"].get(k), dict):
            n["report"][k].update(v)
        else:
            n["report"][k] = v
    return n


print("== a healthy database server")
h = node()
allc = W.postgres_checks(h, [], {}, {}, NOW) + W.linux_checks(h, [], {}, {}, NOW) + W.security_checks(h, [], {}, {}, NOW)
ok(bad(allc) == {} and len(allc) >= 15, f"no finding on a healthy node ({len(allc)} checks)")
ok(all(c.area in ("pg", "linux", "sec") and c.detail.startswith("db-1") for c in allc), "every check names its node")
ok(len({W.probe_key(h, c) for c in allc}) == len(allc) and W.probe_key(h, allc[0]).startswith("node:7:pg:"), "probe keys are unique: node:<id>:<area>:<check>")

print("== PostgreSQL")
P = lambda rep, prev=None, samples=None, thr=None: bad(W.postgres_checks(node(report={"postgres": rep}), samples or [], thr or {}, prev or {}, NOW))
ok(P({"connections": 85, "connections_pct": 85}) == {"connections": "warning"} and P({"connections": 97, "connections_pct": 97}) == {"connections": "failed"}, "connections at 85 % warn, at 97 % fail")
lt = {"seconds": 4000, "pid": 4242, "database": "maludb_os", "role": "app_rw", "state": "idle in transaction"}
ok(P({"longest_transaction": lt}) == {"long_transaction": "warning"} and P({"longest_transaction": dict(lt, seconds=20000)}) == {"long_transaction": "failed"}, "a transaction open over an hour warns, over four fails")
c = [x for x in W.postgres_checks(node(report={"postgres": {"longest_transaction": lt}}), [], {}, {}, NOW) if x.check == "long_transaction"][0]
ok("pid 4242" in c.detail and c.measured == {"seconds": 4000, "pid": 4242, "state": "idle in transaction"}, "the finding carries the pid (what a cancel will need) and the seconds")
ok(P({"longest_lock_wait": {"seconds": 90, "pid": 9, "database": "maludb"}, "lock_waiters": 2}) == {"lock_wait": "warning"}, "a lock wait over a minute warns")
dead = {"table": "public.t", "database": "maludb_os", "live": 1000, "dead": 9000, "dead_pct": 31, "vacuum_age_s": 200000}
ok(P({"dead_tuples": [dead]}) == {"dead_tuples": "warning"} and P({"dead_tuples": [dict(dead, vacuum_age_s=3600)]}) == {}
   and P({"dead_tuples": [dict(dead, vacuum_age_s=None)]}) == {"dead_tuples": "warning"} and P({"dead_tuples": [dict(dead, dead_pct=5)]}) == {},
   "dead rows over 20 % with no vacuum in a day (or ever) warn; a recent vacuum or a small share does not")
ok(P({"xid_age": 1_100_000_000}) == {"xid_age": "warning"} and P({"xid_age": 1_600_000_000}) == {"xid_age": "failed"}, "transaction-id age past half the limit warns, later fails")
ok(P({"certificate_days": 20}) == {"certificate": "warning"} and P({"certificate_days": 3}) == {"certificate": "failed"} and P({"certificate_days": -2}) == {"certificate": "failed"}, "the certificate under thirty days warns, under seven or expired fails")
ok(P({"log": {"error": 60, "fatal": 0, "panic": 0}}) == {"log": "warning"} and P({"log": {"error": 1, "fatal": 2, "panic": 0}}) == {"log": "warning"} and P({"log": {"error": 0, "fatal": 0, "panic": 1}}) == {"log": "failed"}
   and P({"log": {"error": 10, "fatal": 0, "panic": 0}}) == {}, "the log: many errors or any FATAL warn, a PANIC fails, a few errors are nothing")
had = [{"age_s": 3600, "numbers": {"pg.replicas": 1}}]
ok(P({"replicas": 0}, samples=had) == {"replication": "warning"} and P({"replicas": 1, "replication_lag_mb": 2000}) == {"replication": "warning"} and P({"replicas": 1, "replication_lag_mb": 5}) == {}, "a replica that went away or lags over 1 GB warns")
first = W.postgres_checks(node(), [], {}, {}, NOW)
su = [x for x in first if x.check == "superusers"][0]
ok(su.status == "ok" and su.measured["known"] == ["edward"], "the first pass learns the superusers: none is new")
second = [x for x in W.postgres_checks(node(report={"postgres": {"superusers": ["edward", "mallory"]}}), [], {}, {"superusers": su.measured}, NOW + 600) if x.check == "superusers"][0]
ok(second.status == "warning" and "mallory" in second.detail and "edward" not in second.detail.split("postgres:")[1], "a superuser that appears later is a finding, named")
third = [x for x in W.postgres_checks(node(report={"postgres": {"superusers": ["edward", "mallory"]}}), [], {}, {"superusers": second.measured}, NOW + 3600) if x.check == "superusers"][0]
later = [x for x in W.postgres_checks(node(report={"postgres": {"superusers": ["edward", "mallory"]}}), [], {}, {"superusers": third.measured}, NOW + 90000) if x.check == "superusers"][0]
ok(third.status == "warning" and later.status == "ok" and later.measured["known"] == ["edward", "mallory"], "it stays a finding for a day, then is known")
ok(W.postgres_checks(node(report={"postgres": None}), [], {}, {}, NOW) == [] and not W.applies("watch_postgres", node(report={"postgres": None})), "a node without a postgres part is not the database administrator's")
ok(P({"connections": 85, "connections_pct": 85}, thr={"pg_connections_pct_warn": 90}) == {}, "a threshold from the agent's config overrides the default")

print("== Linux")
L = lambda samples=None, **over: bad(W.linux_checks(node(**over), samples or [], {}, {}, NOW))
ok(L(presence="offline") == {"reachable": "failed"} and L(silent_s=400) == {"reachable": "failed"} and len(W.linux_checks(node(presence="offline"), [], {}, {}, NOW)) == 1, "a silent node fails `reachable` and nothing else is judged on its old report")
ok(L(report={"disk": [{"mount": "/", "used_pct": 88}]}) == {"disk:/": "warning"} and L(report={"disk": [{"mount": "/", "used_pct": 96}]}) == {"disk:/": "failed"}, "a disk at 88 % warns, at 96 % fails")
grow = [{"age_s": 86400 - i * 3600, "numbers": {"disk./": 50 + i * 0.25}} for i in range(25)]         # +6 points a day from 50 %: about 8 days left
d = W.disk_forecast(grow, "disk./", 6)
ok(d is not None and 7 < d < 9.5, f"the forecast: a disk growing six points a day from 56 % fills in about eight days ({d and round(d, 1)})")
ok(L(samples=grow, report={"disk": [{"mount": "/", "used_pct": 56}]}) == {"disk:/": "warning"}, "a disk that fills within fourteen days warns before it is full")
fast = [{"age_s": 43200 - i * 3600, "numbers": {"disk./": 40 + i * 2}} for i in range(13)]
ok(L(samples=fast, report={"disk": [{"mount": "/", "used_pct": 64}]}) == {"disk:/": "failed"}, "one that fills within three days fails")
flat = [{"age_s": 86400 - i * 3600, "numbers": {"disk./": 50}} for i in range(25)]
ok(W.disk_forecast(flat, "disk./", 6) is None and W.disk_forecast(grow[:3], "disk./", 6) is None and W.disk_forecast(grow[-5:], "disk./", 6) is None, "no forecast from a flat disk, three samples or under six hours of history")
ok(L(report={"linux": {"failed_units": ["apache2.service", "x.service"]}}) == {"failed_units": "warning"}, "failed units warn")
ok(L(report={"linux": {"reboot_required_days": 9}}) == {"reboot": "warning"} and L(report={"linux": {"reboot_required_days": 2}}) == {}, "a reboot pending over seven days warns")
ok(L(report={"linux": {"clock_synced": False}}) == {"clock": "warning"} and L(report={"linux": {"clock_synced": None}}) == {}, "an unsynchronised clock warns; an unknown one does not")
ok(L(report={"linux": {"inodes": {"mount": "/var", "used_pct": 93}}}) == {"inodes": "warning"}, "inodes over 90 % warn")
ok(L(report={"memory": {"total_mb": 16000, "available_mb": 400}}) == {"memory": "warning"}, "memory under 5 % available warns")
ok(W.applies("watch_linux", node()) and not W.applies("watch_linux", node(kind="inference")), "the Linux administrator watches server nodes")

print("== security")
S = lambda samples=None, prev=None, ports=None, **over: bad(W.security_checks(node(**over), samples or [], {}, prev or {}, NOW, ports))
ok(S(report={"security": {"failed_logins": 40, "failed_source_count": 9}}) == {"failed_logins": "warning"} and S(report={"security": {"failed_logins": 400}}) == {"failed_logins": "failed"}, "failed logins: 40 in a window warn, 400 fail")
ok(S(report={"security": {"failed_logins": 12, "failed_sources": [{"address": "203.0.113.7", "count": 12}]}}) == {"failed_logins": "warning"}, "a burst from one address warns below the total's threshold")
new = [{"address": "198.51.100.4", "user": "edward", "method": "publickey"}]
c = [x for x in W.security_checks(node(report={"security": {"new_addresses": new}}), [], {}, {}, NOW) if x.check == "new_login_address"][0]
ok(c.status == "warning" and "198.51.100.4" in c.detail and "edward" in c.detail, "a login from a new address is a finding with who and from where")
odd = SEC["listening"] + [{"proto": "tcp", "port": 4444, "scope": "any"}]
ok(S(report={"security": {"listening": odd}}) == {"listening": "warning"}, "a port outside the role's set is a finding")
ok(S(report={"security": {"listening": odd}}, ports={"database-server": ["tcp/4444"]}) == {} and S(report={"security": {"listening": odd}}, ports={"kernel": ["tcp/4444"]}) == {"listening": "warning"},
   "adding it to the agent's expected_ports for that role settles it; for another role does not")
ok(S(node_role="kernel", report={"security": {"listening": [{"proto": "tcp", "port": 8081, "scope": "address"}, {"proto": "tcp", "port": 443, "scope": "any"}]}}) == {}
   and S(node_role="kernel", report={"security": {"listening": [{"proto": "tcp", "port": 5432, "scope": "any"}]}}) == {"listening": "warning"},
   "a kernel server's door is expected; PostgreSQL open on a kernel server is not")
ok(S(node_role="application-server", report={"security": {"listening": [{"proto": "tcp", "port": 9100, "scope": "address"}]}}) == {}, "an application server's relay ports are expected")
cfg = {"digest": "bbbb", "files": 40, "changed_at": "2026-11-13T05:00:00Z"}
ok(S(report={"security": {"config": cfg}}) == {} , "a first pass learns the configuration: a dated change with nothing to compare is not a finding")
ok(S(report={"security": {"config": cfg}}, prev={"config": {"digest": "aaaa", "changed_at": None}}) == {"config": "warning"}
   and S(report={"security": {"config": cfg}}, prev={"config": {"digest": "bbbb", "changed_at": "2026-11-13T05:00:00Z"}}) == {}, "a change since the last pass is a finding once, then known")
old = [{"age_s": a, "numbers": {"updates.security": 2}} for a in (4 * 86400, 3 * 86400, 2 * 86400, 86400, 600)]
ok(S(samples=old, report={"updates": {"security_count": 2}}) == {"security_updates": "warning"}, "security updates pending for more than three days warn")
gap = [{"age_s": 4 * 86400, "numbers": {"updates.security": 2}}, {"age_s": 86400, "numbers": {"updates.security": 0}}, {"age_s": 600, "numbers": {"updates.security": 2}}]
ok(S(samples=gap, report={"updates": {"security_count": 2}}) == {} and S(samples=old[-2:], report={"updates": {"security_count": 2}}) == {}, "not when they were applied in between, nor with under three days of history")
ok(W.security_checks(node(presence="offline"), [], {}, {}, NOW) == [], "an offline node's old report is not judged")

print("== remedies (db/197)")
R = lambda checks, n, cfg=None: [r for r in (W.remedy(c, n, cfg) for c in checks) if r]
n1 = node(report={"postgres": {"longest_transaction": dict(lt, seconds=20000)}})
ok(R(W.postgres_checks(n1, [], {}, {}, NOW), n1) == [{"location": 7, "reason": [c for c in W.postgres_checks(n1, [], {}, {}, NOW) if c.check == "long_transaction"][0].detail[:280], "action": "postgres_terminate", "pid": 4242}],
   "a transaction idle for over four hours: ask to end that session, by pid")
n2 = node(report={"postgres": {"longest_transaction": dict(lt, seconds=20000, state="active")}})
ok([r["action"] for r in R(W.postgres_checks(n2, [], {}, {}, NOW), n2)] == ["postgres_cancel"], "an active statement running that long: ask to cancel it")
n3 = node(report={"postgres": {"longest_transaction": lt, "connections_pct": 97, "connections": 97}})
ok(R(W.postgres_checks(n3, [], {}, {}, NOW), n3) == [], "a warning-level transaction and full connections have no remedy: a person looks")
n4 = node(report={"linux": {"failed_units": ["cups.service", "maludb-mc2dbd.service"]}})
ok([(r["action"], r["unit"]) for r in R(W.linux_checks(n4, [], {}, {}, NOW), n4)] == [("restart_unit", "maludb-mc2dbd.service")], "a failed unit of the role's list: ask to restart it; another unit is left to a person")
n5 = node(node_role="kernel", report={"linux": {"failed_units": ["postgresql@18-main.service"]}})
ok(R(W.linux_checks(n5, [], {}, {}, NOW), n5) == [], "a unit that is not in this role's list is never asked for")
ok([r["action"] for r in R(W.security_checks(node(report={"updates": {"security_count": 2}}), old, {}, {}, NOW), node())] == ["apply_updates"], "security updates left for days: ask to apply updates")
ok(R(W.postgres_checks(n1, [], {}, {}, NOW), n1, {"remedies": False}) == [], "`remedies: false` in the agent's config turns them off")
ok(all(set(r) <= {"location", "reason", "action", "pid", "unit"} for r in R(W.postgres_checks(n1, [], {}, {}, NOW), n1) + R(W.linux_checks(n4, [], {}, {}, NOW), n4)), "a remedy is a fixed verb with a pid or a unit: nothing else travels")

print("== what a check may say")
loud = node(report={"postgres": {"longest_transaction": lt, "superusers": ["edward", "mallory"], "dead_tuples": [dead]}, "security": {"new_addresses": new, "listening": odd, "failed_logins": 400},
                    "linux": {"failed_units": ["x.service"]}})
text = json.dumps([[c.detail, c.measured] for c in W.postgres_checks(loud, [], {}, {}, NOW) + W.linux_checks(loud, [], {}, {}, NOW) + W.security_checks(loud, [], {}, {}, NOW)])
ok(not any(w in text for w in ("SELECT", "COMMAND=", "password", "ERROR:")) and len(text) < 6000, "no statement, command or log line in any detail")

print("PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
