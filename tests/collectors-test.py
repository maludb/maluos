#!/usr/bin/env python3
"""The node's collectors (Phase 14 slice 4b, docs/phase14-watching-agents.md) on fixture data: the journal's login
and sudo lines into counts, /proc/net into what listens, the server log's levels with rotation, the configuration's
digest, when the postgres part applies, what the security part remembers, and that nothing of a log line, a query
or a secret reaches a part. No root, no cluster, no journal.

  python3 tests/collectors-test.py
"""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = tempfile.mkdtemp(prefix="collectors-test-")
os.environ.update(MALUOS_ESTATE_STATE_DIR=D, MALUOS_PROVISIONED=os.path.join(D, "done"), MALUOS_COLLECT_CONFIG_DIRS=os.path.join(D, "etc"),
                  MALUOS_PG_LOG=os.path.join(D, "pg.log"), MALUOS_PG_CERT=os.path.join(D, "none.crt"), MALUOS_PROC_NET=os.path.join(D, "net"))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-estate/lib"))
from maluos_estate import collectors as C

fails = 0


def ok(cond, label):
    global fails
    fails += 0 if cond else 1
    print(("  ok   " if cond else "  FAIL ") + label)


# ---- the journal: sshd and sudo
AUTH = """Failed password for invalid user admin from 203.0.113.7 port 51122 ssh2
Failed password for root from 203.0.113.7 port 51123 ssh2
Invalid user oracle from 203.0.113.9 port 40000
Failed publickey for edward from 198.51.100.4 port 2222 ssh2
pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=203.0.113.7  user=root
Accepted publickey for edward from 192.0.2.10 port 50000 ssh2: ED25519 SHA256:abcdefg
Accepted password for edward from 192.0.2.44 port 50001 ssh2
  edward : TTY=pts/0 ; PWD=/home/edward ; USER=root ; COMMAND=/usr/bin/maluctl secret show system/db-password
  deploy : TTY=pts/1 ; PWD=/srv ; USER=root ; COMMAND=/usr/bin/systemctl restart apache2
pam_unix(sudo:session): session opened for user root(uid=0) by edward(uid=1000)
Connection closed by 203.0.113.7 port 51122 [preauth]""".splitlines()
seen = ["192.0.2.10"]
a = C.parse_auth(AUTH, seen)
ok(a["failed_logins"] == 5 and a["failed_source_count"] == 3 and a["failed_sources"][0] == {"address": "203.0.113.7", "count": 3},
   f"failed logins counted with their sources, the busiest first ({a['failed_logins']}, {a['failed_sources'][:1]})")
ok(a["logins"] == 2 and a["new_addresses"] == [{"address": "192.0.2.44", "user": "edward", "method": "password"}] and "192.0.2.44" in seen,
   "two logins; the address not seen before is named once and remembered")
ok(a["sudo"] == 2 and a["sudo_users"] == ["deploy", "edward"], "sudo uses counted with their users")
blob = json.dumps(a)
ok("maluctl secret show" not in blob and "db-password" not in blob and "SHA256" not in blob and "COMMAND" not in blob, "no command, key fingerprint or log line in the part")
ok(C.parse_auth([], [])["failed_logins"] == 0, "an empty window is zeros")

# ---- /proc/net: what listens beyond loopback
TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1 x
   1: 0100007F:1538 00000000:0000 0A 00000000:00000000 00:00000000 00000000   115        0 2 1 x
   2: C664A8C0:1F91 00000000:0000 0A 00000000:00000000 00:00000000 00000000    33        0 3 1 x
   3: C664A8C0:D431 0A00A8C0:1538 01 00000000:00000000 00:00000000 00000000  1000        0 4 1 x
   4: 3500007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000   101        0 5 1 x"""
UDP = """   sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  100: 00000000:CA6C 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 6 2 x 0
  101: 3500007F:0035 00000000:0000 07 00000000:00000000 00:00000000 00000000   101        0 7 2 x 0"""
TCP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 8 1 x
   1: 00000000000000000000000001000000:1538 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000   115        0 9 1 x"""
got = C.parse_listening(TCP, UDP)
ok(got == {("tcp", 22, "any"), ("tcp", 8081, "address"), ("udp", 51820, "any")}, f"IPv4: the wildcard and the LAN listeners, no loopback, no connection ({sorted(got)})")
ok(C.parse_listening(TCP6, "", v6=True) == {("tcp", 80, "any")}, "IPv6: the wildcard listener, not ::1")
os.makedirs(os.path.join(D, "net"))
for n, t in (("tcp", TCP), ("udp", UDP), ("tcp6", TCP6)):
    open(os.path.join(D, "net", n), "w").write(t)
ok(C.listening() == [{"proto": "tcp", "port": 22, "scope": "any"}, {"proto": "tcp", "port": 80, "scope": "any"}, {"proto": "tcp", "port": 8081, "scope": "address"},
                     {"proto": "udp", "port": 51820, "scope": "any"}], "listening(): merged and sorted")

# ---- the server log
log = os.path.join(D, "pg.log")
open(log, "w").write("2026-11-13 05:00:00.000 UTC [100] LOG:  database system is ready\n2026-11-13 05:00:01.000 UTC [101] app_rw@maludb_os ERROR:  duplicate key value violates unique constraint \"x\"\n")
st = {}
first = C.log_counts(log, st)
ok(first == {"error": 0, "fatal": 0, "panic": 0}, "the first report starts at the log's end: old lines are not counted")
open(log, "a").write("2026-11-13 05:01:00.000 UTC [102] app_rw@maludb_os ERROR:  canceling statement due to statement timeout\n"
                     "2026-11-13 05:01:01.000 UTC [102] app_rw@maludb_os STATEMENT:  SELECT secret FROM vault WHERE note = 'ERROR:  not a level'\n"
                     "2026-11-13 05:01:02.000 UTC [103] [unknown]@[unknown] FATAL:  password authentication failed for user \"app_rw\"\n")
second = C.log_counts(log, st)
ok(second["error"] == 1 and second["fatal"] == 1 and second["panic"] == 0, f"new ERROR and FATAL lines counted ({second}); a STATEMENT line quoting a level is not one")
ok(C.log_counts(log, st) == {"error": 0, "fatal": 0, "panic": 0}, "nothing new: zeros")
os.rename(log, log + ".1"); open(log, "w").write("2026-11-13 06:00:00.000 UTC [200] PANIC:  could not write to file\n")
ok(C.log_counts(log, st)["panic"] == 1, "a rotated log is read from its start")
ok(C.log_counts(os.path.join(D, "absent.log"), {}) is None, "no log: None")

# ---- the configuration's digest
etc = os.path.join(D, "etc"); os.makedirs(os.path.join(etc, "sub"))
open(os.path.join(etc, "a.yaml"), "w").write("a: 1\n"); open(os.path.join(etc, "sub", "b.conf"), "w").write("b\n")
d1, n1 = C.config_digest()
ok(n1 == 2 and C.config_digest() == (d1, 2), "the digest is stable over two files")
open(os.path.join(etc, "a.yaml"), "w").write("a: 2\n")
d2, _ = C.config_digest()
os.chmod(os.path.join(etc, "sub", "b.conf"), 0o600)
d3, _ = C.config_digest()
open(os.path.join(etc, "new.service"), "w").write("[Unit]\n")
d4, n4 = C.config_digest()
ok(len({d1, d2, d3, d4}) == 4 and n4 == 3, "a changed content, a changed mode and a new file each change it")

# ---- when the postgres part applies
ok(C.pg_applies({"role": "database-server", "database_server": {"port": 5432}}), "postgres applies on a database server")
ok(C.pg_applies({"database": "maludb", "components": {"maluos-vault": {}}}), "and on a host whose own cluster holds its data")
ok(not C.pg_applies({"database": "maludb", "database_server": {"host": "db-1"}, "components": {}}), "not on a server whose data is on a database server")
ok(not C.pg_applies({}), "not on a host that was never provisioned")
ok(C.postgres() is None, "postgres() is None there (no cluster is asked)")

# ---- the security part: what it remembers
C.journal_auth = lambda since: AUTH
C.firewall = lambda: {"ufw": "enabled", "nftables": "inactive"}
st = {}
s1 = C.security(st, now=1_800_000_000)
ok(s1["new_addresses"] == [] and s1["logins"] == 2 and s1["window_s"] == 300 and s1["config"]["changed_at"] is None,
   "the first report learns the login addresses and the configuration: nothing is called new or changed")
C.journal_auth = lambda since: ["Accepted publickey for edward from 192.0.2.10 port 1 ssh2", "Accepted publickey for mallory from 203.0.113.50 port 2 ssh2"]
open(os.path.join(etc, "a.yaml"), "w").write("a: 3\n")
s2 = C.security(st, now=1_800_000_900)
ok(s2["new_addresses"] == [{"address": "203.0.113.50", "user": "mallory", "method": "publickey"}] and s2["window_s"] == 900,
   "the next report names the one address not seen before; its window is the time since the last")
ok(s2["config"]["changed_at"] == "2027-01-15T08:15:00Z" and s2["config"]["digest"] != s1["config"]["digest"], "a changed configuration is dated")
s3 = C.security(st, now=1_800_100_000)
ok(s3["window_s"] == 86400 and s3["config"]["changed_at"] == s2["config"]["changed_at"], "a long silence reads a day of journal at most; the change keeps its date")
C._save(st)
ok(oct(os.stat(C.STATE).st_mode & 0o777) == "0o600" and C._state().get("seen"), "what the collectors remember is one 0600 file")
ok(len(json.dumps({"security": s2})) < 4000, f"the security part is small ({len(json.dumps(s2))} bytes)")

print("PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
