"""The node's collectors (Phase 14 slice 4b, docs/phase14-watching-agents.md): three parts of the report that the
watching agents on the kernel server read. Plain code, not agents; numbers and short facts only.

  postgres   a node that runs a cluster others use (a database server, a single host): connections against the limit,
             the longest transaction and lock wait (seconds and the pid, never the query), WAL, replication, sizes,
             dead tuples and vacuum age, transaction-id age, ERROR/FATAL/PANIC counts in the server log since the
             last report, the server certificate's days left, superusers other than postgres
  linux      every node: failed units, a pending reboot and since when, clock sync, inode use
  security   every node: failed logins (counts, the top sources), logins from addresses not seen before, sudo use
             (count, the users), what listens beyond loopback, a digest of /etc/maluos and of the units, the firewall

Nothing here is a secret, a query's text or a log line. Each part answers None when it does not apply and raises when
it cannot be read (the report names it in `errors`). PostgreSQL is read as the node service's own user by peer
authentication: a login role of its name that holds pg_monitor and nothing else (first boot makes it). The journal
and the server log are read through the groups systemd-journal and adm.

What a collector remembers between reports (a log's offset, the addresses seen, the last digest) is one file,
collect.json, in the node service's state directory.
"""
import hashlib, json, os, re, socket, subprocess, time

STATE_DIR = os.environ.get("MALUOS_ESTATE_STATE_DIR", "/var/lib/maluos/estate")
STATE = os.path.join(STATE_DIR, "collect.json")
PROVISIONED = os.environ.get("MALUOS_PROVISIONED", "/var/lib/maluos/firstboot/done")
PG_VERSION = os.environ.get("MALUOS_PG_VERSION", "18")
PG_CLUSTER = os.environ.get("MALUOS_PG_CLUSTER", "main")
PG_PORT = os.environ.get("MALUOS_PG_PORT", "")
PG_LOG = os.environ.get("MALUOS_PG_LOG", f"/var/log/postgresql/postgresql-{PG_VERSION}-{PG_CLUSTER}.log")
PG_CERT = os.environ.get("MALUOS_PG_CERT", "/etc/maluos/database-server/server.crt")
CONFIG_DIRS = [d for d in os.environ.get("MALUOS_COLLECT_CONFIG_DIRS", "/etc/maluos:/etc/systemd/system").split(":") if d]
PROC_NET = os.environ.get("MALUOS_PROC_NET", "/proc/net")
LOG_READ_MAX = 4 * 2 ** 20            # of the server log per report; a larger burst is counted from its tail
WINDOW_MAX_S = 86400                  # the journal is never read further back than a day
SEEN_MAX = 200                        # login addresses remembered


def _state():
    try:
        with open(STATE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(st):
    try:
        tmp = STATE + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(st, f)
        os.replace(tmp, STATE)
    except OSError:
        pass


def _provisioned():
    try:
        with open(PROVISIONED) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _run(argv, timeout=20):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------------------------------------- PostgreSQL
PG_SQL = """
SELECT json_build_object(
  'version', current_setting('server_version'),
  'in_recovery', pg_is_in_recovery(),
  'max_connections', current_setting('max_connections')::int,
  'connections', (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'),
  'idle_in_transaction', (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND state LIKE 'idle in transaction%'),
  'longest_transaction', (SELECT json_build_object('seconds', extract(epoch FROM now() - xact_start)::int, 'pid', pid, 'database', datname, 'role', usename, 'state', state)
       FROM pg_stat_activity WHERE backend_type = 'client backend' AND xact_start IS NOT NULL AND pid <> pg_backend_pid() ORDER BY xact_start LIMIT 1),
  'lock_waiters', (SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'),
  'longest_lock_wait', (SELECT json_build_object('seconds', extract(epoch FROM now() - state_change)::int, 'pid', pid, 'database', datname)
       FROM pg_stat_activity WHERE wait_event_type = 'Lock' ORDER BY state_change LIMIT 1),
  'xid_age', (SELECT max(age(datfrozenxid)) FROM pg_database),
  'databases', (SELECT json_agg(d) FROM (SELECT datname AS name, pg_database_size(datname) / 1048576 AS size_mb FROM pg_database
       WHERE NOT datistemplate ORDER BY pg_database_size(datname) DESC LIMIT 20) d),
  'wal_mb', (SELECT coalesce(sum(size), 0) / 1048576 FROM pg_ls_waldir()),
  'replicas', (SELECT count(*) FROM pg_stat_replication),
  'replication_lag_mb', (SELECT max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) / 1048576 FROM pg_stat_replication WHERE NOT pg_is_in_recovery()),
  'deadlocks', (SELECT coalesce(sum(deadlocks), 0) FROM pg_stat_database),
  'superusers', (SELECT coalesce(json_agg(rolname ORDER BY rolname), '[]'::json) FROM pg_roles WHERE rolsuper AND rolname <> 'postgres')
)"""
PG_TABLES_SQL = """
SELECT coalesce(json_agg(t), '[]'::json) FROM (
  SELECT schemaname || '.' || relname AS "table", n_live_tup AS live, n_dead_tup AS dead,
         round(100.0 * n_dead_tup / greatest(n_live_tup + n_dead_tup, 1))::int AS dead_pct,
         extract(epoch FROM now() - greatest(last_autovacuum, last_vacuum))::bigint AS vacuum_age_s
    FROM pg_stat_user_tables WHERE n_dead_tup >= 1000 ORDER BY n_dead_tup DESC LIMIT 3) t"""
# the first level word of a line is its level: a STATEMENT or DETAIL line that quotes "ERROR:  " is not an error
PG_LEVEL = re.compile(r"\b(DEBUG\d?|INFO|NOTICE|WARNING|LOG|ERROR|FATAL|PANIC|STATEMENT|DETAIL|HINT|CONTEXT|QUERY|LOCATION):  ")


def _psql(sql, db="postgres", timeout=20):
    argv = ["psql", "-AtqX", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql]
    if PG_PORT:
        argv[1:1] = ["-p", PG_PORT]
    env = dict(os.environ, PGCONNECT_TIMEOUT="8", PGOPTIONS="-c statement_timeout=15000 -c application_name=maluos-estate")
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:160] if (r.stderr or r.stdout).strip() else f"psql exit {r.returncode}")
    return r.stdout.strip()


def pg_applies(prov=None):
    """A database server, or a host whose own cluster holds its data. Not an office whose data is on a database
    server: its own cluster is idle and the database server reports for itself."""
    prov = _provisioned() if prov is None else prov
    if prov.get("role") == "database-server":
        return True
    if isinstance(prov.get("database_server"), dict):
        return False
    return bool(prov.get("database") or prov.get("components"))


def log_counts(path, st, limit=LOG_READ_MAX):
    """ERROR, FATAL and PANIC lines in the server log since the last report: the offset and the inode are remembered;
    a rotated or truncated log is read from its start, a burst over `limit` from its tail."""
    out = {"error": 0, "fatal": 0, "panic": 0}
    try:
        s = os.stat(path)
    except OSError:
        return None
    key = "pg_log"
    prev = st.get(key) if isinstance(st.get(key), dict) else {}
    start = prev.get("offset", s.st_size) if prev.get("inode") == s.st_ino and prev.get("offset", 0) <= s.st_size else (0 if prev else s.st_size)
    if s.st_size - start > limit:
        start = s.st_size - limit; out["truncated"] = True
    with open(path, "rb") as f:
        f.seek(start)
        for raw in f.read(s.st_size - start).splitlines():
            m = PG_LEVEL.search(raw.decode("utf-8", "replace"))
            if m and m.group(1) in ("ERROR", "FATAL", "PANIC"):
                out[m.group(1).lower()] += 1
    st[key] = {"inode": s.st_ino, "offset": s.st_size}
    return out


def cert_days(path, now=None):
    if not os.path.exists(path):
        return None
    rc, out, _ = _run(["openssl", "x509", "-enddate", "-noout", "-in", path])
    m = re.search(r"notAfter=(.+)", out)
    if rc != 0 or not m:
        return None
    end = time.mktime(time.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z")) - time.timezone
    return int((end - (now or time.time())) // 86400)


def postgres(st=None):
    if not pg_applies():
        return None
    own = st is None
    st = _state() if own else st
    d = json.loads(_psql(PG_SQL))
    d["connections_pct"] = round(100 * d["connections"] / d["max_connections"]) if d.get("max_connections") else None
    for k in ("wal_mb", "replication_lag_mb"):
        if d.get(k) is not None:
            d[k] = int(d[k])
    tables, skipped = [], []
    for db in [x["name"] for x in (d.get("databases") or [])][:8]:
        if db == "postgres":
            continue
        try:
            for t in json.loads(_psql(PG_TABLES_SQL, db)):
                t["database"] = db; tables.append(t)
        except Exception:
            skipped.append(db)          # no CONNECT for the monitor there: named, not fatal
    tables.sort(key=lambda t: -t["dead"])
    d["dead_tuples"] = tables[:8]
    if skipped:
        d["tables_unread"] = skipped
    d["log"] = log_counts(PG_LOG, st)
    d["certificate_days"] = cert_days(PG_CERT)
    if own:
        _save(st)
    return d


# ---------------------------------------------------------------------------------------------- Linux
def failed_units():
    rc, out, _ = _run(["systemctl", "list-units", "--state=failed", "--no-legend", "--plain"])
    return [l.split()[0] for l in out.splitlines() if l.split()][:20]


def clock_synced():
    if os.path.exists("/run/systemd/timesync/synchronized"):
        return True
    try:
        rc, out, _ = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=10)
        return out.strip() == "yes" if rc == 0 and out.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def inodes():
    worst = None
    try:
        for line in open("/proc/mounts"):
            dev, mount, fstype = line.split()[:3]
            if not dev.startswith("/dev/") or fstype in ("squashfs", "iso9660", "vfat") or mount.startswith(("/snap/", "/boot/efi", "/tmp/")):
                continue
            s = os.statvfs(mount)
            if s.f_files:
                pct = round(100 * (s.f_files - s.f_ffree) / s.f_files)
                if worst is None or pct > worst["used_pct"]:
                    worst = {"mount": mount, "used_pct": pct}
    except OSError:
        pass
    return worst


def linux():
    out = {"failed_units": failed_units(), "clock_synced": clock_synced(), "inodes": inodes()}
    try:
        out["reboot_required_days"] = int((time.time() - os.stat("/run/reboot-required").st_mtime) // 86400)
    except OSError:
        out["reboot_required_days"] = None
    return out


# ---------------------------------------------------------------------------------------------- security
SSH_FAILED = re.compile(r"(?:Failed \w+ for (?:invalid user )?\S+|Invalid user \S+|authentication failure.*rhost=)\s*(?:from )?([0-9A-Fa-f:.]+)?")
SSH_ACCEPTED = re.compile(r"Accepted (\w+) for (\S+) from ([0-9A-Fa-f:.]+)")
SUDO_CMD = re.compile(r"^\s*(\S+) : .*COMMAND=")


def parse_auth(lines, seen):
    """The journal's sshd and sudo lines since the last report into counts. `seen` is the list of addresses that
    logged in before; the ones new in these lines are returned and added."""
    failed, sources, accepted, new, sudo, users = 0, {}, 0, [], 0, {}
    for l in lines:
        m = SSH_ACCEPTED.search(l)
        if m:
            accepted += 1
            if m.group(3) not in seen:
                seen.append(m.group(3)); new.append({"address": m.group(3), "user": m.group(2), "method": m.group(1)})
            continue
        m = SUDO_CMD.search(l)
        if m:
            sudo += 1; users[m.group(1)] = users.get(m.group(1), 0) + 1
            continue
        m = SSH_FAILED.search(l)
        if m:
            failed += 1
            if m.group(1):
                sources[m.group(1)] = sources.get(m.group(1), 0) + 1
    top = sorted(sources.items(), key=lambda kv: -kv[1])[:10]
    del seen[:-SEEN_MAX]
    return {"failed_logins": failed, "failed_sources": [{"address": a, "count": n} for a, n in top], "failed_source_count": len(sources),
            "logins": accepted, "new_addresses": new[:10], "sudo": sudo, "sudo_users": sorted(users)[:10]}


def journal_auth(since_s):
    rc, out, err = _run(["journalctl", "-q", "--no-pager", "-o", "cat", "--since", f"-{int(since_s)}s", "-t", "sshd", "-t", "sshd-session", "-t", "sudo"], timeout=30)
    if rc != 0:
        raise RuntimeError(f"journalctl: {(err or out).strip()[:120]}")
    return out.splitlines()


def parse_listening(tcp_text, udp_text="", v6=False):
    """/proc/net/tcp[6] and udp[6] into what listens beyond loopback: [{proto, port, scope}]; scope `any` for a
    wildcard address, else `address`."""
    out = set()
    for proto, text in (("tcp", tcp_text), ("udp", udp_text)):
        for line in text.splitlines()[1:]:
            f = line.split()
            if len(f) < 4 or (proto == "tcp" and f[3] != "0A"):
                continue
            addr, _, port = f[1].rpartition(":")
            port = int(port, 16)
            if not port:
                continue
            if v6:
                if addr == "0" * 31 + "1" or addr == "00000000000000000000000001000000":
                    continue
                scope = "any" if set(addr) == {"0"} else "address"
            else:
                if addr.endswith("7F"):                 # little-endian 127.x.y.z
                    continue
                scope = "any" if addr == "00000000" else "address"
            out.add((proto, port, scope))
    return out


def listening():
    found = set()
    for name, v6 in (("", False), ("6", True)):
        try:
            tcp = open(os.path.join(PROC_NET, "tcp" + name)).read()
        except OSError:
            tcp = ""
        try:
            udp = open(os.path.join(PROC_NET, "udp" + name)).read()
        except OSError:
            udp = ""
        found |= parse_listening(tcp, udp, v6)
    merged = {}
    for proto, port, scope in found:
        k = (proto, port)
        merged[k] = "any" if scope == "any" or merged.get(k) == "any" else scope
    return [{"proto": p, "port": n, "scope": s} for (p, n), s in sorted(merged.items())][:60]


def config_digest(dirs=None):
    """One digest over the configuration's files: the path, the mode, the owner and the content's hash (or, for a file
    the node service may not read, its size and mtime). A change of any of them changes the digest."""
    h, n = hashlib.sha256(), 0
    for top in (CONFIG_DIRS if dirs is None else dirs):
        for root, ds, fs in os.walk(top):
            ds.sort()
            for name in sorted(fs):
                p = os.path.join(root, name)
                try:
                    s = os.lstat(p)
                except OSError:
                    continue
                if os.path.islink(p):
                    body = "link:" + os.readlink(p)
                else:
                    try:
                        with open(p, "rb") as f:
                            body = hashlib.sha256(f.read(2 ** 20)).hexdigest()
                    except OSError:
                        body = f"unread:{s.st_size}:{int(s.st_mtime)}"
                h.update(f"{p}\0{s.st_mode:o}\0{s.st_uid}:{s.st_gid}\0{body}\n".encode()); n += 1
    return h.hexdigest()[:32], n


def firewall():
    out = {"ufw": None, "nftables": None}
    try:
        for line in open("/etc/ufw/ufw.conf"):
            if line.strip().startswith("ENABLED="):
                out["ufw"] = "enabled" if line.split("=", 1)[1].strip().lower() == "yes" else "disabled"
    except OSError:
        pass
    try:
        rc, o, _ = _run(["systemctl", "is-active", "nftables.service"], timeout=10)
        out["nftables"] = o.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def security(st=None, now=None):
    own = st is None
    st = _state() if own else st
    now = now or time.time()
    since = min(WINDOW_MAX_S, max(60, now - float(st.get("auth_at") or (now - 300))))
    seen = st.get("seen") if isinstance(st.get("seen"), list) else []
    first = "seen" not in st            # the first report learns the addresses instead of calling each one new
    out = parse_auth(journal_auth(since), seen)
    if first:
        out["new_addresses"] = []
    out["window_s"] = int(since)
    st["seen"], st["auth_at"] = seen, now
    out["listening"] = listening()
    digest, files = config_digest()
    prev = st.get("config") if isinstance(st.get("config"), dict) else {}
    if prev.get("digest") != digest:
        st["config"] = {"digest": digest, "changed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "first": not prev}
    out["config"] = {"digest": digest, "files": files, "changed_at": None if st["config"].get("first") else st["config"]["changed_at"]}
    out["firewall"] = firewall()
    if own:
        _save(st)
    return out
