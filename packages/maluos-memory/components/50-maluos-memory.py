"""MaluOS first-boot component: the memory face (maluos-memory).

Creates the face's PostgreSQL role (peer-authenticated as the system user maluos-memory) with the tenant's memory
facades, the two service principals it works through (estate:guest, what this host shares; estate:sync, the writer
of replicated copies), the read grant on the vault's ledger and the agent registry, writes /etc/maluos/memory.yaml
(database, tenant), and starts the socket. Nothing is shared or exposed until the operator says so (`maluctl memory
share`, `maluctl memory expose`), and the face signs its estate queries only once `maluctl memory keys` (or a join or
enrolment after this package) grants it this host's signing keys.
"""
import json, os, pwd, subprocess, sys, time

ROLE = "maluos-memory"
CONF = "/etc/maluos/memory.yaml"
DAEMON = "/usr/lib/maluos/maluos_memory/server.py"
GUEST = "estate:guest"
SYNC = "estate:sync"


def provision(ctx):
    log, psql, exists, qi, ql = ctx["log"], ctx["psql"], ctx["exists"], ctx["qi"], ctx["ql"]
    db, tenant = ctx["db"], ctx["tenant"]
    if not os.path.exists(DAEMON):
        return None
    try:
        pwd.getpwnam(ROLE)
    except KeyError:
        raise RuntimeError(f"system user {ROLE} missing (package postinst did not run?)")
    ensure_schema(psql, exists, qi, ql, db, tenant)
    ensure_principals(psql, qi, ql, db, tenant)
    log(f"memory: role {ROLE} with the tenant's memory facades; principals {GUEST} (shares nothing yet) and {SYNC}")
    import yaml
    conf = {}
    if os.path.exists(CONF):
        with open(CONF) as f:
            conf = yaml.safe_load(f) or {}
    want = dict(conf); want.update({"database": db, "tenant": tenant, "guest": GUEST, "sync_principal": SYNC})
    want.setdefault("tcp", {"enabled": False, "host": "overlay", "port": 11437})
    ccfg = (ctx["cfg"].get("components") or {}).get("maluos-memory") or {}
    if isinstance(ccfg.get("tcp"), dict):
        want["tcp"] = {**want["tcp"], **ccfg["tcp"]}
    if want != conf:
        with open(CONF, "w") as f:
            f.write("# MaluOS memory face (maluos-memory). database/tenant are set by first boot; tcp by `maluctl memory expose`.\n"
                    "# See docs/phase13-slice4-memory.md. What the host shares is the guest principal's grants: `maluctl memory share`.\n"
                    "# ask_self: true lets the face ask its own identities (a one-host test); a host never asks itself otherwise.\n")
            yaml.safe_dump(want, f, sort_keys=True)
        os.chmod(CONF, 0o644)
    os.makedirs("/var/lib/maluos/memory", exist_ok=True)
    u = pwd.getpwnam(ROLE); os.chown("/var/lib/maluos/memory", u.pw_uid, u.pw_gid); os.chmod("/var/lib/maluos/memory", 0o750)
    subprocess.run(["systemctl", "enable", "--quiet", "maluos-memory.socket"], check=False)
    subprocess.run(["systemctl", "start", "maluos-memory.socket"], check=False)
    subprocess.run(["systemctl", "restart", "maluos-memory.service"], check=False)
    healthy = False
    for _ in range(30):
        try:
            if face_get("/v1/health").get("ok"):
                healthy = True; break
        except Exception:
            pass
        time.sleep(1)
    if not healthy:
        log("warning: memory face not healthy (journalctl -u maluos-memory)")
        return {"healthy": False, "socket": "/run/maluos/memory.sock"}
    if isinstance(ccfg.get("share"), list) and ccfg["share"]:
        r = subprocess.run(["maluctl", "memory", "share", *[str(s) for s in ccfg["share"]]], capture_output=True, text=True)
        log(f"memory: share from firstboot.yaml: {(r.stdout or r.stderr).strip()[-160:]}")
    log(f"memory face healthy at /run/maluos/memory.sock; shares nothing until `maluctl memory share`")
    return {"healthy": True, "socket": "/run/maluos/memory.sock", "role": ROLE, "guest": GUEST}


def ensure_schema(psql, exists, qi, ql, db, tenant, role=ROLE):
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(role)}"):
        psql(f"CREATE ROLE {qi(role)} LOGIN")
    t, rl = qi(tenant), qi(role)
    psql(f"""GRANT CONNECT ON DATABASE {qi(db)} TO {rl};
             GRANT USAGE ON SCHEMA maludb_core TO {rl};
             GRANT USAGE ON SCHEMA {t} TO {rl};
             GRANT SELECT ON maludb_core."malu$principal", maludb_core."malu$principal_scope" TO {rl};
             GRANT SELECT ON {t}.maludb_principal, {t}.maludb_principal_scope TO {rl};
             GRANT SELECT, INSERT, UPDATE ON {t}.maludb_memory TO {rl};
             GRANT USAGE, SELECT ON SEQUENCE maludb_core."malu$memory_memory_id_seq" TO {rl};""", db)
    # the engine's executor access (the triggers behind a write read the payload schemas and the kind registry): maludb_user through the engine's own grant
    psql(f"SELECT maludb_core.grant_memory_access({ql(role)}, 'write')", db)
    # the memory facade view is extension-owned: its row policies hold for the face as for any non-owner; the stamp trigger forces the principal
    psql(f"""SET ROLE {t};
             GRANT SELECT, INSERT ON {t}.maluos_ledger TO {rl};
             GRANT USAGE, SELECT ON {t}.maluos_ledger_ledger_id_seq TO {rl};""", db)
    try:
        psql(f"SET ROLE {t}; GRANT SELECT ON {t}.maluos_agent TO {rl};", db)
    except Exception as e:
        print(f"maluos-memory: no grant on maluos_agent ({e.__class__.__name__}): --as an owned agent needs the vault's registry", file=sys.stderr)


def ensure_principals(psql, qi, ql, db, tenant):
    pre = f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public; "
    psql(pre + f"SELECT maludb_principal_upsert({ql(GUEST)}, 'service', 'MaluOS memory face: the estate''s guest (what this host shares)', {ql(GUEST)}, NULL, true);", db)
    psql(pre + f"SELECT maludb_principal_upsert({ql(SYNC)}, 'service', 'MaluOS memory face: replicated copies of other holders'' summaries', {ql(SYNC)}, NULL, true);", db)
    # the face's own identity at the vault (user:maluos-memory): the memberships grant it a read on their signing keys
    psql(pre + f"SELECT maludb_principal_upsert({ql('user:' + ROLE)}, 'service', 'MaluOS memory face (signs this host''s memory queries)', 'org', NULL, true);", db)


def face_get(path):
    import http.client, socket as so
    sock = "/run/maluos/memory.sock"

    class U(http.client.HTTPConnection):
        def connect(self):
            s = so.socket(so.AF_UNIX, so.SOCK_STREAM); s.settimeout(10); s.connect(sock); self.sock = s
    c = U("maluos-memory"); c.request("GET", path); r = c.getresponse(); data = json.loads(r.read() or b"{}"); c.close()
    return data
