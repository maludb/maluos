#!/usr/bin/env python3
"""database-server.py: where this server keeps its data (MaluOS Phase 14).

A MaluOS server keeps its data in its own PostgreSQL cluster unless /etc/maluos/firstboot.yaml carries a
database_server block naming another MaluOS server (one installed with role: database-server). This script
shows which it is, tests a database server before anything is written, and writes the block.

  database-server.py --show
  database-server.py --check --host db-1.example.com --credential /path/db-admin.txt --ca /path/db-ca.pem
  database-server.py --apply --host db-1.example.com --credential /path/db-admin.txt --ca /path/db-ca.pem
                     [--port 5432] [--admin maluos_admin] [--data-not-moved]

The two files come from the database server: `sudo maluctl db export DIR` there writes db-admin.txt (the
admin role's password; root-only, never shown here) and db-ca.pem (its certificate, public).

--check connects as the admin role over TLS with the certificate verified (verify-full) and says, when it
cannot, which side to fix: the name is not in the certificate, this server's address is not admitted, the
password is wrong, nothing listens. --apply runs the same check first and writes nothing when it fails.

--apply does not move data. On a server whose kernel was already provisioned on its own cluster it refuses
unless --data-not-moved is given: the next `maluctl provision --force` then starts empty on the database
server (new kernel database, a new administrator password, an empty vault store).

The host must be a name the office resolves on its own network at first boot (a LAN name or DNS name), and
the certificate must carry it: the estate's overlay name cannot be used for this connection, because the
overlay's members are rows of the kernel's database.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys

PATH = "/etc/maluos/firstboot.yaml"
DONE = "/var/lib/maluos/firstboot/done"
TEMPLATE = "maludb_template"
try:
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_provision as _mp
    TEMPLATE = getattr(_mp, "DB_TEMPLATE", TEMPLATE)
except Exception:
    _mp = None


def say(kind, msg): print(f"{kind:<5} {msg}")
def die(msg, code=1): print(f"ERROR {msg}", file=sys.stderr); sys.exit(code)


def need_root(argv):
    if os.geteuid() == 0:
        return
    if subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0:
        os.execvp("sudo", ["sudo", "-n", os.path.realpath(__file__), *argv])
    die(f"needs root: sudo {os.path.realpath(__file__)} {' '.join(argv)}", 97)


def load_yaml(text):
    import yaml
    return yaml.safe_load(text) or {}


def state():
    try:
        return json.load(open(DONE))
    except Exception:
        return {}


def current():
    cfg = load_yaml(open(PATH).read()) if os.path.exists(PATH) else {}
    blk = cfg.get("database_server") if isinstance(cfg.get("database_server"), dict) else {}
    return cfg, blk


def show():
    cfg, blk = current()
    st = state()
    role = str(cfg.get("role") or "").strip()
    if role == "database-server":
        say("NOTE", "this host is a database server (role: database-server): other servers keep their data here")
    elif blk.get("host"):
        say("NOTE", f"configured: data on the database server {blk['host']}:{blk.get('port') or 5432} as {blk.get('admin') or 'maluos_admin'} ({blk.get('sslmode') or 'verify-full'})")
    else:
        say("NOTE", "configured: data in this server's own PostgreSQL cluster (no database_server block)")
    done = st.get("database_server")
    if st:
        if isinstance(done, dict) and done.get("host"):
            say("NOTE", f"provisioned: against {done.get('host')}:{done.get('port')} ({done.get('tls') or done.get('sslmode') or 'tls'})")
        elif role != "database-server":
            say("NOTE", "provisioned: on this server's own cluster")
        k = (st.get("components") or {}).get("maludb-os-core") or {}
        if k.get("domain"):
            say("NOTE", f"the kernel is provisioned for {k.get('domain')}")
    else:
        say("NOTE", "first boot has not finished: nothing is provisioned yet")
    if os.path.exists("/usr/lib/maluos/maluctl.d") or shutil.which("maluctl"):
        r = subprocess.run(["maluctl", "db", "status"], capture_output=True, text=True)
        for line in (r.stdout or "").splitlines():
            if line.startswith("reached:"):
                say("PASS" if "yes" in line.split(":", 1)[1][:6] else "FAIL", line)
    return 0


def cert_names(ca):
    r = subprocess.run(["openssl", "x509", "-in", ca, "-noout", "-ext", "subjectAltName"], capture_output=True, text=True)
    names = re.findall(r"(?:DNS|IP Address):([^,\s]+)", r.stdout or "")
    r2 = subprocess.run(["openssl", "x509", "-in", ca, "-noout", "-fingerprint", "-sha256"], capture_output=True, text=True)
    return names, (r2.stdout or "").strip().split("=", 1)[-1]


def explain(err, a, names):
    e = err.lower()
    if "does not match host name" in e or "certificate verify failed" in e or "hostname mismatch" in e:
        return (f"the certificate does not vouch for the name {a.host}. It carries: {', '.join(names) or 'no names'}. "
                f"Either use one of those names here, or add this one on the database server "
                f"(database_server.names in its /etc/maluos/firstboot.yaml, then `sudo maluctl provision --force` and `maluctl db export` again)")
    if "no pg_hba.conf entry" in e:
        return ("the database server does not admit this server's address. Add this server's network to database_server.clients "
                "in the database server's /etc/maluos/firstboot.yaml and run `sudo maluctl provision --force` there")
    if "password authentication failed" in e:
        return f"the password in {a.credential} is not the role {a.admin}'s. Run `sudo maluctl db export DIR` on the database server again and use its db-admin.txt"
    if "could not translate host name" in e or "name or service not known" in e:
        return (f"this server cannot resolve {a.host}. Use a name your LAN's DNS answers (or an /etc/hosts line on this server); "
                "the estate's overlay name is not usable for this connection")
    if "connection refused" in e or "timeout" in e or "no route" in e or "timed out" in e:
        return (f"nothing answers at {a.host}:{a.port}. On the database server check `sudo maluctl db status` (it must listen on its "
                "network address: database_server.listen) and any firewall between the two")
    if "ssl" in e and "not supported" in e or "server does not support ssl" in e:
        return "the server at that address does not offer TLS: it is not a MaluOS database server, or its first boot has not run with role: database-server"
    return "see the message above"


def check(a):
    for label, p in (("--credential", a.credential), ("--ca", a.ca)):
        if not p or not os.path.isfile(p):
            say("FAIL", f"{label}: {p or '(not given)'} is not a file"); return 1
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", a.host):
        say("FAIL", f"--host {a.host!r} is not a host name or address"); return 1
    if a.host.endswith(".internal"):
        say("NOTE", f"{a.host} is an overlay name: an office cannot reach its own database over the overlay at first boot. Prefer the LAN name")
    pw = open(a.credential).read().strip()
    if not pw:
        say("FAIL", f"{a.credential} is empty"); return 1
    names, fp = cert_names(a.ca)
    say("NOTE", f"certificate {fp or '(unreadable)'} for: {', '.join(names) or 'no names'}")
    conn = f"host={a.host} port={a.port} user={a.admin} dbname=postgres sslmode=verify-full sslrootcert={a.ca} connect_timeout=12"
    sql = ("SELECT current_user || '|' || r.rolcreaterole || '|' || r.rolcreatedb || '|' || r.rolsuper || '|' || current_setting('server_version') "
           "|| '|' || coalesce((SELECT version FROM pg_stat_ssl WHERE pid = pg_backend_pid() AND ssl), 'no TLS') "
           f"|| '|' || EXISTS (SELECT 1 FROM pg_database WHERE datname = '{TEMPLATE}') FROM pg_roles r WHERE r.rolname = current_user")
    env = {**os.environ, "PGPASSWORD": pw, "PGCONNECT_TIMEOUT": "12"}
    r = subprocess.run(["psql", "-X", "-At", "-d", conn, "-c", sql], capture_output=True, text=True, env=env, timeout=40)
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()[-1][:300] if (r.stderr or "").strip() else "psql failed"
        say("FAIL", f"cannot connect to {a.host}:{a.port} as {a.admin}: {msg}")
        say("NOTE", explain(r.stderr or "", a, names))
        return 1
    user, createrole, createdb, sup, ver, tls, tmpl = ((r.stdout or "").strip().split("|") + [""] * 7)[:7]
    say("PASS", f"connected to {a.host}:{a.port} as {user} over {tls}, the certificate verified; PostgreSQL {ver}")
    bad = 0
    if createrole.startswith("t") and createdb.startswith("t"):
        say("PASS", f"{user} may create roles and databases" + ("" if sup.startswith("f") else " (and is a superuser, which the admin role should not be)"))
    else:
        say("FAIL", f"{user} may not create roles and databases: it is not the admin role a MaluOS database server makes"); bad = 1
    if tmpl.startswith("t"):
        say("PASS", f"the server has the template {TEMPLATE} (the engine, ready to copy)")
    else:
        say("FAIL", f"the server has no {TEMPLATE} template: was its first boot run with role: database-server?"); bad = 1
    return bad


def top_level_block(lines, key):
    """(start, end) of the top-level `key:` block, or None."""
    for i, l in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", l):
            j = i + 1
            while j < len(lines) and (lines[j].strip() == "" or lines[j][0] in " \t" or lines[j].lstrip().startswith("#") and lines[j][0] in " \t"):
                j += 1
            while j > i + 1 and lines[j - 1].strip() == "":
                j -= 1
            return i, j
    return None


def apply(a):
    if not os.path.exists(PATH):
        die(f"{PATH} is missing: this is not a MaluOS server")
    cfg, _ = current()
    if str(cfg.get("role") or "").strip() == "database-server":
        die("this host is itself a database server (role: database-server); it keeps its data here")
    st = state()
    k = (st.get("components") or {}).get("maludb-os-core") or {}
    was_remote = isinstance(st.get("database_server"), dict) and st["database_server"].get("host")
    if k.get("domain") and not k.get("error") and not was_remote and not a.data_not_moved:
        die(f"the kernel is already provisioned on this server's own cluster (for {k.get('domain')}). Pointing it at a database server "
            "does not move that data: the next provisioning starts empty there. Give --data-not-moved to accept that on a server with nothing to keep.")
    if check(a) != 0:
        die("the database server did not pass the check: nothing was written")
    text = open(PATH).read()
    lines = text.splitlines()
    block = ["database_server:", f"  host: {a.host}", f"  port: {a.port}", f"  admin: {a.admin}",
             f"  credential: file:{os.path.abspath(a.credential)}", "  sslmode: verify-full", f"  ca: file:{os.path.abspath(a.ca)}"]
    ext = top_level_block(lines, "database_server")
    if ext:
        lines[ext[0]:ext[1]] = block
    else:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines += ["# where this server keeps its data: a MaluOS database server (written by maluos-office-setup)"] + block
    new = "\n".join(lines) + "\n"
    try:
        got = load_yaml(new).get("database_server") or {}
        assert got.get("host") == a.host and int(got.get("port")) == int(a.port)
    except Exception as e:
        die(f"the edited file would not parse as intended ({e}); nothing was written")
    backup = f"{PATH}.bak-{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    shutil.copy2(PATH, backup)
    with open(PATH, "w") as f:
        f.write(new)
    say("PASS", f"{PATH}: database_server set to {a.host}:{a.port} (backup {backup})")
    say("NOTE", "nothing is provisioned yet: provision.sh (maluctl provision --force) makes this server's databases and roles on the database server")
    say("NOTE", f"keep {a.credential} and {a.ca} in place until provisioning has run once; first boot then keeps its own root-only copies")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true"); g.add_argument("--check", action="store_true"); g.add_argument("--apply", action="store_true")
    ap.add_argument("--host"); ap.add_argument("--port", type=int, default=5432); ap.add_argument("--admin", default="maluos_admin")
    ap.add_argument("--credential"); ap.add_argument("--ca"); ap.add_argument("--data-not-moved", action="store_true")
    a = ap.parse_args()
    need_root(sys.argv[1:])
    if a.show:
        return show()
    if not a.host:
        die("--host is required with --check and --apply")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", a.admin):
        die(f"--admin {a.admin!r} is not a role name")
    return check(a) if a.check else apply(a)


if __name__ == "__main__":
    sys.exit(main())
