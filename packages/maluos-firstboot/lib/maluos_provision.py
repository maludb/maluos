#!/usr/bin/python3
"""MaluOS provisioning engine.

Creates the MaluDB database, the tenant, the administrator principal, the
listener and operator PostgreSQL roles, the listener bearer token, and starts
the MC2DB listener. Every step checks the current state first, so the whole
run is idempotent and `maluctl provision` can repeat it at any time.
"""
import json, os, pwd, re, secrets, shutil, subprocess, sys, time, urllib.request

CONFIG = os.environ.get("MALUOS_FIRSTBOOT_CONFIG", "/etc/maluos/firstboot.yaml")  # override for tests
STATE_DIR = os.environ.get("MALUOS_STATE_DIR", "/var/lib/maluos/firstboot")  # override for tests
DONE = os.path.join(STATE_DIR, "done")
SECRETS_DIR = os.environ.get("MALUOS_SECRETS_DIR", "/var/lib/maluos/secrets")  # override for tests
TOKEN_FILE = os.path.join(SECRETS_DIR, "mc2dbd.token")
LISTENER_UNIT = "maludb-mc2dbd.service"
LISTENER_CONF = "/etc/maludb/maludb-mc2dbd.conf"
# Phase 14: the database on another MaluOS server (docs/phase14-database-server.md)
DB_ADMIN_FILE = os.path.join(SECRETS_DIR, "db-admin.password")   # the admin role's password, root-only
DB_PGPASS = os.path.join(SECRETS_DIR, "db-admin.pgpass")         # the same as a PGPASSFILE, never on a command line
DB_CA = os.environ.get("MALUOS_DB_CA", "/etc/maluos/database-server-ca.pem")                     # the database server's certificate (public; the services read it)
DB_TEMPLATE = "maludb_template"                                  # a database with the engine in it, for the office's admin to copy
DB_SERVER_DIR = os.environ.get("MALUOS_DB_SERVER_DIR", "/etc/maluos/database-server")                    # on the database server: its certificate and key

DEFAULTS = {
    "database": "maludb",
    "tenant": {"name": "maluos"},
    "admin_principal": {"ref": "human:admin", "kind": "human",
                        "display_name": "Administrator", "home_scope": "org"},
    "listener": {"enabled": True, "host": "127.0.0.1", "port": 5329, "token": "generate"},
    "operators": "auto",
}


def log(msg):
    print(f"maluos-firstboot: {msg}", flush=True)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(CONFIG):
        import yaml
        with open(CONFIG) as f:
            user = yaml.safe_load(f) or {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ---------------------------------------------------------------- SQL helpers
def qi(s):  # quote identifier
    return '"' + str(s).replace('"', '""') + '"'


def ql(s):  # quote literal
    return "'" + str(s).replace("'", "''") + "'"


_TARGET = {}


def is_database_server(cfg):
    return str(cfg.get("role") or "").strip() == "database-server"


def is_application_server(cfg):
    """role: application-server (docs/phase14-application-servers.md): a MaluOS server with the platform services
    (the tenant, the vault, the gateway, the memory face, so agents can run on it) and applications, and no kernel."""
    return str(cfg.get("role") or "").strip() == "application-server"


_SUFFIX = {}


def platform_suffix(cfg=None):
    """Gap 8 of the split topology: every MaluOS server makes the same database and service roles, so two servers
    on one database server would take each other's. An application server whose data is on a database server
    therefore uses names of its own there: the database maludb_<suffix> and the roles maluos-vault-<suffix>,
    maluos-gateway-<suffix>, maluos-memory-<suffix>. The suffix is database_server.suffix or the host's name.
    Empty everywhere else: a kernel server, a single host and a local cluster keep the plain names."""
    if "v" in _SUFFIX and cfg is None:
        return _SUFFIX["v"]
    c = cfg if cfg is not None else load_config()
    v = ""
    if is_application_server(c) and database_target(c):
        blk = c.get("database_server") or {}
        import re, socket
        v = re.sub(r"[^a-z0-9]+", "_", str(blk.get("suffix") or socket.gethostname().split(".")[0]).lower()).strip("_")[:24]
    _SUFFIX["v"] = v
    return v


def platform_db(cfg):
    """The engine database of this server's platform services: cfg.database, with the suffix on an application server."""
    s, db = platform_suffix(cfg), str(cfg["database"])
    return f"{db}_{s}" if s and not db.endswith("_" + s) else db


def db_role(name):
    """A platform service's role in the database: its own name, with the suffix on an application server (the
    system user and the vault's principal keep the plain name)."""
    s = platform_suffix()
    return f"{name}-{s}" if s else name


def _ref(value):
    """`file:PATH` or a bare path -> PATH."""
    v = str(value or "").strip()
    return v[5:] if v.startswith("file:") else v


def database_target(cfg=None, refresh=False):
    """Where the data is. None: the PostgreSQL cluster of this host, over its socket, as the local superuser
    (today's single host, and the database server itself). A dict {host, port, admin, sslmode, ca}: another
    MaluOS server, reached as the admin role its first boot made (not a superuser: decision 2 and the owner's 3)."""
    if "v" in _TARGET and not refresh and cfg is None:
        return _TARGET["v"]
    cfg = cfg if cfg is not None else load_config()
    blk = cfg.get("database_server") or {}
    t = None
    if is_database_server(cfg) and isinstance(blk, dict) and blk.get("cluster"):
        _TARGET["cluster"] = str(blk["cluster"])
    if isinstance(blk, dict) and blk.get("host") and str(blk.get("host")) not in ("local", "localhost-socket") and not is_database_server(cfg):
        ca = _ref(blk.get("ca"))
        t = {"host": str(blk["host"]), "port": int(blk.get("port") or 5432), "admin": str(blk.get("admin") or "maluos_admin"),
             "sslmode": str(blk.get("sslmode") or ("verify-full" if ca else "require")), "ca": ca or None,
             "credential": _ref(blk.get("credential")) or None}
    _TARGET["v"] = t
    return t


def _pgpass_escape(v):
    return str(v).replace("\\", "\\\\").replace(":", "\\:")


def prepare_remote(t):
    """The admin credential and the certificate, from the plan's medium to this host (once): the password to a
    root-only file and a PGPASSFILE, the certificate to /etc/maluos (it is public). The medium can go afterwards."""
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True); os.chmod(SECRETS_DIR, 0o700)
    src = t.get("credential")
    if src and os.path.exists(src) and os.path.abspath(src) != DB_ADMIN_FILE:
        pw = open(src).read().strip()
        if not pw:
            raise RuntimeError(f"database_server.credential: {src} is empty")
        with open(os.open(DB_ADMIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(pw + "\n")
    if not os.path.exists(DB_ADMIN_FILE):
        raise RuntimeError(f"database_server.credential: no admin password ({src or 'no file given'} not found, none stored in {DB_ADMIN_FILE})")
    pw = open(DB_ADMIN_FILE).read().strip()
    with open(os.open(DB_PGPASS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(":".join([_pgpass_escape(t["host"]), str(t["port"]), "*", _pgpass_escape(t["admin"]), _pgpass_escape(pw)]) + "\n")
    ca = t.get("ca")
    if ca and os.path.abspath(ca) != DB_CA:
        if os.path.exists(ca):
            shutil.copyfile(ca, DB_CA); os.chmod(DB_CA, 0o644)
        elif not os.path.exists(DB_CA):
            raise RuntimeError(f"database_server.ca: {ca} not found and no certificate stored in {DB_CA}")
    if ca:
        t["ca"] = DB_CA
    return t


def conninfo(t, db, user=None):
    """A libpq connection string for the remote database server (no password in it: PGPASSFILE or the caller's)."""
    parts = [f"host={t['host']}", f"port={t['port']}", f"user={user or t['admin']}", f"dbname={db}",
             f"sslmode={t['sslmode']}", "connect_timeout=15"]
    if t.get("ca"):
        parts.append(f"sslrootcert={t['ca']}")
    return " ".join(parts)


def service_target():
    """What a service's configuration needs to reach the database: {} for the local socket (peer authentication),
    or {pg_host, pg_port, pg_sslmode, pg_sslrootcert} for the database server (a password then: decision 3)."""
    t = database_target()
    if not t:
        return {}
    out = {"pg_host": t["host"], "pg_port": t["port"], "pg_sslmode": t["sslmode"]}
    if t.get("ca"):
        out["pg_sslrootcert"] = DB_CA
    return out


def _local_env():
    """The local cluster: the main one, or the one `database_server.cluster` names (VERSION/NAME) on a database server."""
    c = _TARGET.get("cluster")
    return {**os.environ, "PGCLUSTER": c} if c else None


def _psql_argv(db):
    """(argv prefix, env) for psql against the database: the local superuser over the socket, or the admin role
    over TLS with its password in PGPASSFILE."""
    t = database_target()
    if not t:
        return ["runuser", "-u", "postgres", "--", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", db], _local_env()
    if not os.path.exists(DB_PGPASS):
        prepare_remote(t)
    return ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", conninfo(t, db)], {**os.environ, "PGPASSFILE": DB_PGPASS}


def psql(sql, db="postgres", check=True):
    argv, env = _psql_argv(db)
    r = subprocess.run(argv + ["-qAt", "-c", sql], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}\n  sql: {sql[:200]}")
    return r.stdout.strip()


def psql_file(path, db="postgres", pre=None, check=True):
    """Run a file of SQL (a schema, a migration) through the same connection as psql(); `pre` is a statement run
    first in the same session (SET ROLE, a search_path). Returns the CompletedProcess."""
    argv, env = _psql_argv(db)
    r = subprocess.run(argv + ["-q"] + (["-c", pre] if pre else []) + ["-f", path], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"psql -f {path} failed: {r.stderr.strip()[-400:]}")
    return r


def exists(sql, db="postgres"):
    return psql(sql, db) == "1"


def cluster_port(version="18", name="main"):
    c = _TARGET.get("cluster")
    if c and "/" in c:
        version, name = c.split("/", 1)
    r = subprocess.run(["pg_lsclusters", "-h"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == version and f[1] == name:
            return f[2]
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 3:
            return f[2]
    return "5432"


def wait_for_postgres(timeout=180):
    t = database_target()
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if t:
            r = subprocess.run(["pg_isready", "-q", "-h", t["host"], "-p", str(t["port"]), "-t", "5"])
            if r.returncode == 0:
                try:
                    if psql("SELECT 1") == "1":
                        return
                except RuntimeError as e:   # it answers, but not to us: the credential, the certificate, pg_hba
                    last = str(e).splitlines()[0]
        elif subprocess.run(["runuser", "-u", "postgres", "--", "pg_isready", "-q"], env=_local_env()).returncode == 0:
            return
        time.sleep(2)
    if t:
        raise RuntimeError(f"the database server {t['host']}:{t['port']} did not answer as {t['admin']}" + (f" ({last})" if last else ""))
    raise RuntimeError("PostgreSQL did not become ready")


# ---------------------------------------------------------------- steps
def ensure_maludb_database(db):
    """A database with the engine in it. Local: created, then the extensions (a superuser's work). On a database
    server: copied from the template its first boot made, since the admin role cannot create the extensions."""
    if exists(f"SELECT 1 FROM pg_database WHERE datname={ql(db)}"):
        created = False
    elif database_target():
        if not exists(f"SELECT 1 FROM pg_database WHERE datname={ql(DB_TEMPLATE)} AND datistemplate"):
            raise RuntimeError(f"the database server has no {DB_TEMPLATE} template: was its first boot run with role: database-server?")
        psql(f"CREATE DATABASE {qi(db)} TEMPLATE {qi(DB_TEMPLATE)}")
        log(f"created database {db} on the database server (from {DB_TEMPLATE})"); created = True
    else:
        psql(f"CREATE DATABASE {qi(db)}")
        log(f"created database {db}"); created = True
    for ext in ("vector", "maludb_core"):
        if not exists(f"SELECT 1 FROM pg_extension WHERE extname={ql(ext)}", db):
            if database_target():
                raise RuntimeError(f"database {db} on the database server has no {ext} extension (not prepared by its first boot)")
            psql(f"CREATE EXTENSION {qi(ext)} CASCADE", db)
            log(f"created extension {ext} in {db}")
    psql(f"ALTER DATABASE {qi(db)} SET search_path TO maludb_core, public")
    return created


def ensure_database(db):
    ensure_maludb_database(db)
    return psql("SELECT extversion FROM pg_extension WHERE extname='maludb_core'", db)


def ensure_role(name, *attrs):
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(name)}"):
        psql(f"CREATE ROLE {qi(name)} {' '.join(attrs)}")
        log(f"created role {name}")
        return True
    return False


MONITOR_ROLE = "maluos_monitor"
MONITOR_USER = os.environ.get("MALUOS_ESTATE_USER", "maluos-estate")


def ensure_monitor():
    """Phase 14 slice 4b (docs/phase14-watching-agents.md): the node service reads this host's cluster for its
    report as its own user by peer authentication. maluos_monitor holds pg_monitor and nothing else; the login role
    named after the node service's user is its only member. Only on the cluster of this host."""
    import pwd
    try:
        pwd.getpwnam(MONITOR_USER)
    except KeyError:
        return False
    ensure_role(MONITOR_ROLE, "NOLOGIN")
    psql(f"GRANT pg_monitor, pg_signal_backend TO {qi(MONITOR_ROLE)}")      # slice 4d: postgres_cancel / postgres_terminate (never a superuser's session)
    ensure_role(MONITOR_USER, "LOGIN")
    psql(f"GRANT {qi(MONITOR_ROLE)} TO {qi(MONITOR_USER)}")
    return True


def unit_property(unit, prop):
    r = subprocess.run(["systemctl", "show", "-p", prop, "--value", unit], capture_output=True, text=True)
    return r.stdout.strip()


def grant_listener(db, role):
    # Mirrors scripts/maludb-bootstrap in maludb-core-26 (listener role grants).
    r = qi(role)
    psql(f"""
GRANT USAGE ON SCHEMA maludb_core TO {r};
GRANT USAGE ON SCHEMA mc2db TO {r};
GRANT SELECT ON ALL TABLES IN SCHEMA maludb_core TO {r};
GRANT INSERT ON maludb_core."malu$mc2db_invocation" TO {r};
GRANT INSERT, UPDATE, DELETE ON
    maludb_core."malu$account", maludb_core."malu$session", maludb_core."malu$session_context",
    maludb_core."malu$prompt_render", maludb_core."malu$model_request", maludb_core."malu$model_response",
    maludb_core."malu$model_provider", maludb_core."malu$model_alias", maludb_core."malu$prompt_template"
    TO {r};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA maludb_core TO {r};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA mc2db TO {r};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA maludb_core TO {r};
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA mc2db TO {r};
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='maludb_llm_admin') THEN
    EXECUTE format('GRANT maludb_llm_admin TO %I', {ql(role)});
    EXECUTE format('ALTER ROLE %I BYPASSRLS', {ql(role)});
  END IF;
END $$;
""", db)


def read_env_file(path):
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.read().splitlines()
    return lines


def set_env(lines, key, value):
    out, done = [], False
    for line in lines:
        if re.match(rf"^\s*#?\s*{re.escape(key)}=", line) and not done:
            out.append(f"{key}={value}"); done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    return out


def ensure_listener(cfg, db):
    lc = cfg["listener"]
    if not lc.get("enabled", True):
        log("listener disabled by configuration"); return None, None
    if not os.path.exists(f"/usr/lib/systemd/system/{LISTENER_UNIT}") and not os.path.exists(f"/etc/systemd/system/{LISTENER_UNIT}"):
        log("maludb-mc2dbd is not installed; skipping listener"); return None, None
    # The packaged unit runs as this OS user; peer auth needs a PG role of the same name.
    os_user = unit_property(LISTENER_UNIT, "User") or "maludb-mc2dbd"
    ensure_role(os_user, "LOGIN")
    grant_listener(db, os_user)
    # Token
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True); os.chmod(SECRETS_DIR, 0o700)
    want = lc.get("token", "generate")
    token = None
    if want == "generate":
        if os.path.exists(TOKEN_FILE):
            token = open(TOKEN_FILE).read().strip()
        else:
            token = secrets.token_hex(32)
    elif want and want != "none":
        token = str(want)
    if token:
        with open(os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(token + "\n")
    elif os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    # Config file (read by systemd as root)
    lines = read_env_file(LISTENER_CONF)
    lines = set_env(lines, "HOST", str(lc.get("host", "127.0.0.1")))
    lines = set_env(lines, "PORT", str(lc.get("port", 5329)))
    port = cluster_port()
    lines = set_env(lines, "PG_CONNINFO", f'"host=/var/run/postgresql port={port} user={os_user} dbname={db}"')
    lines = set_env(lines, "BEARER_TOKEN", token) if token else [l for l in lines if not re.match(r"^\s*BEARER_TOKEN=", l)]
    os.makedirs(os.path.dirname(LISTENER_CONF), exist_ok=True)
    with open(os.open(LISTENER_CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.run(["systemctl", "enable", "--quiet", LISTENER_UNIT], check=False)
    subprocess.run(["systemctl", "restart", "--no-block", LISTENER_UNIT], check=False)
    host = "127.0.0.1" if lc.get("host") in (None, "0.0.0.0", "::") else lc.get("host")
    url = f"http://{host}:{lc.get('port', 5329)}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=3) as r:
                if r.status == 200:
                    log(f"listener healthy at {url}"); return url, os_user
        except Exception:
            time.sleep(2)
    log(f"warning: listener did not answer at {url}/healthz within 60s (see: systemctl status {LISTENER_UNIT})")
    return url, os_user


def ensure_tenant(db, tenant):
    ensure_role(tenant, "LOGIN")
    psql(f"GRANT maludb_user TO {qi(tenant)}", db)
    if not exists(f"SELECT 1 FROM pg_namespace WHERE nspname={ql(tenant)}", db):
        psql(f"CREATE SCHEMA {qi(tenant)} AUTHORIZATION {qi(tenant)}", db)
        log(f"created tenant schema {tenant}")
    psql(f"ALTER ROLE {qi(tenant)} IN DATABASE {qi(db)} SET search_path TO {qi(tenant)}, maludb_core, public", db)
    # enable_memory_schema is idempotent (also the documented upgrade step).
    psql(f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public; "
         f"SELECT count(*) FROM maludb_core.enable_memory_schema();", db)
    log(f"tenant {tenant} memory schema enabled")


def ensure_principal(db, tenant, p):
    ref, kind = p["ref"], p.get("kind", "human")
    name, home = p.get("display_name", ref), p.get("home_scope", ref)
    psql(f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public; "
         f"SELECT maludb_principal_upsert({ql(ref)}, {ql(kind)}, {ql(name)}, {ql(home)});", db)
    log(f"principal {ref} ({kind}) ready in tenant {tenant}, home scope {home}")


def operator_users(spec):
    if spec == "auto":
        return [u.pw_name for u in pwd.getpwall()
                if 1000 <= u.pw_uid < 60000 and not u.pw_shell.endswith(("nologin", "false"))]
    return list(spec or [])


def ensure_operators(db, tenant, users):
    """Every human account is an operator. On a host with its own cluster: a peer-authenticated superuser login
    (phase 4). On an office whose database is elsewhere: no role at all (the owner's decision 3: no superuser
    outside the database server); the operator reaches the data with `sudo maluctl db psql`, as the admin role."""
    remote = database_target() is not None
    for u in users:
        if not remote:
            ensure_role(u, "LOGIN", "SUPERUSER", "CREATEDB")
            psql(f"ALTER ROLE {qi(u)} IN DATABASE {qi(db)} SET search_path TO {qi(tenant)}, maludb_core, public")
        # Every human account is also a principal, so the vault (and later the
        # gateway) can tell who is asking: user:<login>, home scope user:<login>.
        ensure_principal(db, tenant, {"ref": f"user:{u}", "kind": "human", "display_name": u, "home_scope": f"user:{u}"})
    if users:
        log(f"operator {'principals (no database roles: the database is remote)' if remote else 'roles'}: {', '.join(users)}")


# ---------------------------------------------------------------- the database server (Phase 14)
def _run(argv, **kw):
    r = subprocess.run(argv, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip()


def local_cluster():
    """(version, name) of the cluster this host's provisioning works on."""
    c = _TARGET.get("cluster")
    if c and "/" in c:
        return tuple(c.split("/", 1))
    rows = [l.split() for l in subprocess.run(["pg_lsclusters", "-h"], capture_output=True, text=True).stdout.splitlines() if l.split()]
    for f in rows:
        if f[0] == "18" and f[1] == "main":
            return f[0], f[1]
    if not rows:
        raise RuntimeError("no PostgreSQL cluster on this host")
    return rows[0][0], rows[0][1]


def delegate_engine(db, admin):
    """Let the admin role hand the engine's objects in this database on to the roles it creates (a service's
    SELECT on the principals, the listener's tool): every grant it holds carries the grant option, and so does
    what the engine's owner creates later (the tenant facades of enable_memory_schema). No superuser needed after."""
    a = qi(admin)
    owner = psql("SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='maludb_core'", db)
    schemas = ["maludb_core"] + (["mc2db"] if exists("SELECT 1 FROM pg_namespace WHERE nspname='mc2db'", db) else [])
    sl = ", ".join(schemas)
    psql(f"""GRANT USAGE ON SCHEMA {sl} TO {a} WITH GRANT OPTION;
             GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA maludb_core TO {a} WITH GRANT OPTION;
             GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA maludb_core TO {a} WITH GRANT OPTION;
             GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {sl} TO {a} WITH GRANT OPTION;
             GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA {sl} TO {a} WITH GRANT OPTION;
             ALTER DEFAULT PRIVILEGES FOR ROLE {qi(owner)} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {a} WITH GRANT OPTION;
             ALTER DEFAULT PRIVILEGES FOR ROLE {qi(owner)} GRANT USAGE, SELECT ON SEQUENCES TO {a} WITH GRANT OPTION;
             ALTER DEFAULT PRIVILEGES FOR ROLE {qi(owner)} GRANT EXECUTE ON FUNCTIONS TO {a} WITH GRANT OPTION;""", db)


def hba_block(text, clients):
    """pg_hba.conf with this host's block of client addresses (TLS and a password, by address), replacing the last one."""
    begin, end = "# maluos database-server begin", "# maluos database-server end"
    out, skip = [], False
    for line in text.splitlines():
        if line.strip() == begin:
            skip = True
        elif line.strip() == end:
            skip = False
        elif not skip:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    block = [begin, "# written by first boot (role: database-server); edit database_server.clients in /etc/maluos/firstboot.yaml"]
    for c in clients:
        c = str(c).strip()
        if c:
            block.append(f"hostssl all all {c if '/' in c else c + ('/128' if ':' in c else '/32')} scram-sha-256")
    block.append(end)
    return "\n".join(out + [""] + block) + "\n"


def ensure_certificate(blk, confdir):
    """TLS for the cluster: the operator's certificate, or one made here (self-signed, ten years, the names this
    server answers to). Returns (cert, key, fingerprint)."""
    tls = blk.get("tls") or "self-signed"
    pg = pwd.getpwnam("postgres")
    if isinstance(tls, dict):
        cert, key = _ref(tls.get("cert")), _ref(tls.get("key"))
        if not (cert and key and os.path.exists(cert) and os.path.exists(key)):
            raise RuntimeError("database_server.tls: cert and key must both name existing files")
    else:
        os.makedirs(DB_SERVER_DIR, mode=0o755, exist_ok=True)
        cert, key = os.path.join(DB_SERVER_DIR, "server.crt"), os.path.join(DB_SERVER_DIR, "server.key")
        if not (os.path.exists(cert) and os.path.exists(key)):
            import socket
            host = socket.gethostname().split(".")[0]
            names = [host, f"{host}.internal", socket.getfqdn(), "localhost"] + [str(n) for n in (blk.get("names") or [])]
            ips = ["127.0.0.1"] + [str(a) for a in [blk.get("listen")] + list(blk.get("addresses") or []) if a and re.match(r"^[0-9a-fA-F:.]+$", str(a)) and str(a) not in ("0.0.0.0", "::")]
            san = ",".join([f"DNS:{n}" for n in dict.fromkeys(names) if n] + [f"IP:{a}" for a in dict.fromkeys(ips)])
            _run(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "3650", "-subj", f"/CN={host}",
                  "-addext", f"subjectAltName={san}", "-keyout", key, "-out", cert])
            log(f"database server: made a certificate for {san}")
    os.chown(key, pg.pw_uid, pg.pw_gid); os.chmod(key, 0o600); os.chmod(cert, 0o644)
    fp = _run(["openssl", "x509", "-in", cert, "-noout", "-fingerprint", "-sha256"]).split("=", 1)[-1]
    return cert, key, fp


def ensure_database_server(cfg, db):
    """role: database-server. The cluster of this host becomes the estate's database: an admin role for the
    office (create roles and databases, the engine's delegated administrator, not a superuser), the engine's
    objects delegated to it in the MaluDB database and in a template it can copy, TLS, the client addresses in
    pg_hba, the listen address. Every step checks first; a restart only when the configuration changed."""
    blk = cfg.get("database_server") if isinstance(cfg.get("database_server"), dict) else {}
    admin = str(blk.get("admin") or "maluos_admin")
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True); os.chmod(SECRETS_DIR, 0o700)
    # 1. the admin role; its password from the plan (credential: file:…), kept from the last run, or minted here
    src = _ref(blk.get("credential"))
    if src and os.path.exists(src) and os.path.abspath(src) != DB_ADMIN_FILE:
        pw = open(src).read().strip()
    elif os.path.exists(DB_ADMIN_FILE):
        pw = open(DB_ADMIN_FILE).read().strip()
    else:
        pw = secrets.token_urlsafe(32)
    with open(os.open(DB_ADMIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(pw + "\n")
    # BYPASSRLS: only a role that has it may give it, and the gateway's role needs it (the engine's queue holds
    # every account's requests). It is the one attribute beyond create-role and create-database; never SUPERUSER.
    if ensure_role(admin, "LOGIN", "CREATEROLE", "CREATEDB", "BYPASSRLS"):
        log(f"database server: admin role {admin} (its password in {DB_ADMIN_FILE}; `sudo maluctl db export DIR` for the office's plan)")
    psql(f"ALTER ROLE {qi(admin)} WITH LOGIN CREATEROLE CREATEDB BYPASSRLS NOSUPERUSER PASSWORD {ql(pw)}")
    psql(f"ALTER ROLE {qi(admin)} SET createrole_self_grant TO 'set, inherit'")
    psql(f"GRANT maludb_admin, maludb_user, maludb_read TO {qi(admin)} WITH ADMIN OPTION")
    # 2. the MaluDB database is the admin's; a template with the engine for the databases it makes later
    psql(f"ALTER DATABASE {qi(db)} OWNER TO {qi(admin)}")
    delegate_engine(db, admin)
    if not exists(f"SELECT 1 FROM pg_database WHERE datname={ql(DB_TEMPLATE)}"):
        psql(f"CREATE DATABASE {qi(DB_TEMPLATE)}")
        log(f"database server: created the template {DB_TEMPLATE}")
    for ext in ("vector", "maludb_core"):
        if not exists(f"SELECT 1 FROM pg_extension WHERE extname={ql(ext)}", DB_TEMPLATE):
            psql(f"CREATE EXTENSION {qi(ext)} CASCADE", DB_TEMPLATE)
    delegate_engine(DB_TEMPLATE, admin)
    psql(f"ALTER DATABASE {qi(DB_TEMPLATE)} IS_TEMPLATE true")
    # 3. TLS, the listen address, the clients
    ver, name = local_cluster()
    confdir = f"/etc/postgresql/{ver}/{name}"
    cert, key, fp = ensure_certificate(blk, confdir)
    listen = str(blk.get("listen") or "*")
    listen = "*" if listen in ("0.0.0.0", "::", "*") else ("localhost," + listen if "localhost" not in listen else listen)
    lines = ["# written by first boot (role: database-server); edit database_server in /etc/maluos/firstboot.yaml",
             f"listen_addresses = '{listen}'", "ssl = on", f"ssl_cert_file = '{cert}'", f"ssl_key_file = '{key}'",
             "password_encryption = scram-sha-256"]
    if blk.get("port"):
        lines.append(f"port = {int(blk['port'])}")
    conf = os.path.join(confdir, "conf.d", "maluos-database-server.conf")
    os.makedirs(os.path.dirname(conf), exist_ok=True)
    changed = False
    want = "\n".join(lines) + "\n"
    if not os.path.exists(conf) or open(conf).read() != want:
        with open(conf, "w") as f:
            f.write(want)
        changed = True
    clients = blk.get("clients") if blk.get("clients") is not None else ["100.100.0.0/16"]
    clients = [clients] if isinstance(clients, str) else list(clients)
    hba = os.path.join(confdir, "pg_hba.conf")
    cur = open(hba).read()
    new = hba_block(cur, clients)
    if new != cur:
        with open(hba, "w") as f:
            f.write(new)
        changed = True
    pg = pwd.getpwnam("postgres")
    for pth in (conf, hba):
        os.chown(pth, pg.pw_uid, pg.pw_gid)
    if changed:
        subprocess.run(["systemctl", "restart", f"postgresql@{ver}-{name}.service"], check=False)
        wait_for_postgres()
        log(f"database server: listening on {listen}, TLS on, clients {', '.join(map(str, clients)) or 'none'}")
    port = int(cluster_port(ver, name))
    return {"admin": admin, "credential": DB_ADMIN_FILE, "listen": listen, "port": port, "clients": [str(c) for c in clients],
            "tls": "self-signed" if not isinstance(blk.get("tls"), dict) else "provided", "certificate": cert,
            "fingerprint": fp, "template": DB_TEMPLATE, "cluster": f"{ver}/{name}"}


def provision_database_server(cfg):
    """First boot of a database server: the cluster, the MaluDB database with the engine, the listener (the
    engine's own face stays with the data), the operators' peer logins, then the server's side of decision 5.
    No tenant and no components: those belong to the office that uses it."""
    blk = cfg.get("database_server") if isinstance(cfg.get("database_server"), dict) else {}
    if blk.get("cluster"):
        _TARGET["cluster"] = str(blk["cluster"])
    _TARGET["v"] = None
    db = cfg["database"]
    log(f"provisioning a database server: database={db}")
    wait_for_postgres()
    version = ensure_database(db)
    url, listener_user = ensure_listener(cfg, db)
    ops = operator_users(cfg.get("operators", "auto"))
    for u in ops:
        ensure_role(u, "LOGIN", "SUPERUSER", "CREATEDB")
    ds = ensure_database_server(cfg, db)
    ensure_monitor()
    os.makedirs(STATE_DIR, exist_ok=True)
    summary = {"provisioned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "role": "database-server",
               "database": db, "maludb_core": version, "tenant": None, "admin_principal": None, "listener": url,
               "listener_user": listener_user, "token_file": TOKEN_FILE if os.path.exists(TOKEN_FILE) else None,
               "operators": ops, "components": {}, "enroll": run_enroll(cfg), "database_server": ds}
    with open(DONE, "w") as f:
        json.dump(summary, f, indent=2); f.write("\n")
    log("done: " + json.dumps(summary))
    return 0


def store_system_secret(name, value, kind="token", provider=None, env_var=None):
    """Keep a copy of a provisioning credential in the vault's shared `system`
    compartment (component 40-maluos-vault). No-op when the vault is absent."""
    try:
        sys.path.insert(0, "/usr/lib/maluos")
        from maluos_vault_client import Vault, VaultError
    except ImportError:
        return False
    v = Vault()
    if not v.available():
        log(f"vault: not available, {name} not stored"); return False
    try:
        v.add(name, value, compartment="system", kind=kind, provider=provider, env_var=env_var, upsert=True)
        return True
    except VaultError as e:
        log(f"vault: could not store {name}: {e}"); return False


def service_login(role, password_file=None, owner=None, vault_ref=None, level="use"):
    """A service's way to the database. Local: {} (the Unix socket, peer authentication, nothing to store).
    On a database server: the role gets a password (kept in a root-only copy, so a re-run does not rotate it)
    and the service's configuration the keys to connect with: the host, the port, TLS, and either
    `pg_password_file` (written here for `owner`: the vault cannot ask itself) or `pg_password_ref` (the vault's
    system compartment, a grant to the service's own principal user:<role>): decision 3. The grant's `level` is
    use for a broker (the gateway), read for any other service: the vault gives mode=use to brokers only."""
    out = service_target()
    if not out:
        return {}
    keep = os.path.join(SECRETS_DIR, f"pg-{role}.password")
    if os.path.exists(keep):
        pw = open(keep).read().strip()
    else:
        pw = secrets.token_urlsafe(32)
        with open(os.open(keep, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(pw + "\n")
    psql(f"ALTER ROLE {qi(db_role(role))} WITH LOGIN PASSWORD {ql(pw)}")
    if password_file:
        with open(os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(pw + "\n")
        if owner:
            u = pwd.getpwnam(owner); os.chown(password_file, u.pw_uid, u.pw_gid)
        out["pg_password_file"] = password_file
    elif vault_ref:
        name = vault_ref.split("/", 1)[-1]
        if not store_system_secret(name, pw, kind="password", provider="postgresql", env_var="PGPASSWORD"):
            raise RuntimeError(f"the vault did not take {vault_ref}: {role} has no way to its database password")
        from maluos_vault_client import Vault
        Vault().grant(f"system/{name}", "principal", f"user:{role}", level=level)
        out["pg_password_ref"] = f"system/{name}"
    out["pg_user"] = db_role(role)
    return out


COMPONENTS_DIR = "/usr/lib/maluos/components"


def run_components(cfg, db, tenant):
    """Run /usr/lib/maluos/components/*.py in name order. Each defines
    provision(ctx) and returns a JSON-able summary or None (not applicable)."""
    import importlib.util, glob
    results = {}
    wanted = cfg.get("components") or {}
    ctx = {"cfg": cfg, "db": db, "tenant": tenant, "log": log, "psql": psql, "exists": exists,
           "qi": qi, "ql": ql, "secrets_dir": SECRETS_DIR, "set_env": set_env, "read_env_file": read_env_file,
           "store_secret": store_system_secret,
           "psql_file": psql_file, "ensure_maludb_database": ensure_maludb_database,
           "database_target": database_target(), "service_login": service_login, "db_role": db_role}
    # an application server runs no kernel and no MaluDB API of its own: it uses the kernel server's through the door
    skip = {"maludb-os-core", "maludb-api"} if is_application_server(cfg) else set()
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(COMPONENTS_DIR, "*.py"))):
        name = os.path.basename(path)[:-3].split("-", 1)[-1]
        if name in skip:
            log(f"component {name}: not on an application server"); continue
        if wanted.get(name, {}).get("enabled", True) is False:
            log(f"component {name}: disabled by configuration"); continue
        spec = importlib.util.spec_from_file_location(f"maluos_component_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            log(f"component {name}: provisioning")
            results[name] = mod.provision(ctx)
        except Exception as e:  # one failing component must not block the others
            log(f"component {name}: FAILED: {e!r}")
            results[name] = {"error": repr(e)}
    return results


def _scrub_enroll_code():
    """The one-time code is used once: blank it in firstboot.yaml, keeping the rest of the file."""
    try:
        lines = open(CONFIG).read().splitlines(True)
    except OSError:
        return
    out, in_enroll = [], False
    for line in lines:
        if re.match(r"^enroll:", line):
            in_enroll = True
        elif re.match(r"^\S", line):
            in_enroll = False
        if in_enroll and re.match(r"^\s+code:", line):
            line = re.sub(r"^(\s+code:).*$", r'\1 ""   # used on the first boot', line.rstrip("\n")) + "\n"
        out.append(line)
    with open(CONFIG, "w") as f:
        f.writelines(out)


def run_enroll(cfg):
    """firstboot.yaml's enroll section (written by the installer from the plan): office -> maluctl office enroll;
    estate -> Phase 13 slice 1, not on this release. Returns the outcome for `maluctl status`, or None."""
    e = cfg.get("enroll") or {}
    kind = (e.get("kind") or "").strip()
    if not kind:
        return None
    url, code, name, owner = e.get("url") or "", e.get("code") or "", e.get("name") or "", e.get("owner") or ""
    if kind == "estate":
        # a server joins the estate as a node (maluos-estate); an application server does not need the overlay to
        # reach the kernel (the owner's decision 2026-11-12: LAN addresses), so it joins without it unless asked
        if not os.path.exists("/usr/lib/maluos/maluctl.d/estate.py"):
            return {"kind": kind, "url": url, "error": "maluos-estate is not installed (no `maluctl estate`)"}
        if os.path.exists("/etc/maluos/estate.yaml"):
            return {"kind": kind, "url": url, "name": name, "ok": True, "output": "already a node of an estate"}
        if not code:
            return {"kind": kind, "url": url, "error": "no code (used already, or none given)"}
        argv = ["maluctl", "estate", "join", url, "--code", code, "--kind", "server"]
        if name:
            argv += ["--name", name]
        if is_database_server(cfg):
            argv += ["--bare"]            # no vault and no gateway here (docs/phase14-watching-agents.md, step 4a)
        elif not e.get("overlay", not is_application_server(cfg)):
            argv += ["--no-overlay"]
        log(f"enroll: estate {url} as {name or 'this host'}")
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
            out, ok = (r.stdout + r.stderr).strip(), r.returncode == 0
        except (OSError, subprocess.SubprocessError) as ex:
            out, ok = repr(ex), False
        _scrub_enroll_code()
        log(f"enroll: {'ok' if ok else 'FAILED'}: {out[-300:]}")
        res = {"kind": kind, "url": url, "name": name, "ok": ok, "output": out[-400:]}
        if not ok:
            res["error"] = out.splitlines()[-1][:200] if out else "the join failed"
        return res
    if kind != "office":
        return {"kind": kind, "url": url, "error": f"unknown enrolment kind {kind!r}"}
    if not os.path.exists("/usr/lib/maluos/maluctl.d/office.py"):
        return {"kind": kind, "url": url, "error": "maluos-desk is not installed (no `maluctl office`)"}
    if not code:
        return {"kind": kind, "url": url, "error": "no code (used already, or none given)"}
    argv = ["maluctl", "office", "enroll", url, "--code", code]
    if name:
        argv += ["--name", name]
    if owner:
        argv += ["--owner", owner]
    log(f"enroll: office {url} as {name or 'this host'}" + (f" for {owner}" if owner else ""))
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        out = (r.stdout + r.stderr).strip()
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError) as ex:
        out, ok = repr(ex), False
    _scrub_enroll_code()
    log(f"enroll: {'ok' if ok else 'FAILED'}: {out[-300:]}")
    res = {"kind": kind, "url": url, "name": name, "owner": owner, "ok": ok, "output": out[-400:]}
    if not ok:
        res["error"] = out.splitlines()[-1][:200] if out else "enrolment failed"
    return res


def run_application_server(cfg, enroll):
    """role: application-server, after the join: the applications of application_server.apps installed here by the
    kernel's installer in its host half (maludb-os-core's maludb_os_apps.install_remote_apps), registered with the
    kernel server through its applications' door. Returns the outcome for the summary and `maluctl status`."""
    blk = cfg.get("application_server") if isinstance(cfg.get("application_server"), dict) else {}
    out = {"kernel": blk.get("kernel"), "apps": list(blk.get("apps") or []), "installed": [], "failed": []}
    if not out["apps"]:
        return out
    if not blk.get("kernel"):
        out["error"] = "application_server.kernel is not set (the kernel server's door, like http://kernel.example.lan:8081)"
    elif not os.path.exists("/etc/maluos/estate.yaml"):
        out["error"] = "this server is not a node of the estate (enroll: kind estate, url, code): " + str((enroll or {}).get("error") or "no enrolment")
    else:
        try:
            sys.path.insert(0, "/usr/lib/maluos")
            import maludb_os_apps as A
            t = database_target()
            out.update(A.install_remote_apps(blk, os.path.join(STATE_DIR, "..", "business-os", "apps"), log=log,
                                             database=({**t, "passfile": DB_PGPASS, "ca": DB_CA if t.get("ca") else None} if t else None)))
        except Exception as e:
            out["error"] = repr(e)
    if out.get("error"):
        log(f"application server: {out['error']}")
    return out


def provision(force=False):
    if os.geteuid() != 0:
        sys.exit("must run as root")
    if os.path.exists(DONE) and not force:
        log("already provisioned (use --force to re-run)"); return 0
    cfg = load_config()
    if is_database_server(cfg):
        return provision_database_server(cfg)
    target = database_target(cfg)
    db, tenant = platform_db(cfg), cfg["tenant"]["name"]
    if target:
        prepare_remote(target)
        log(f"provisioning database={db} tenant={tenant} on the database server {target['host']}:{target['port']} as {target['admin']} ({target['sslmode']})")
    else:
        log(f"provisioning database={db} tenant={tenant}")
    wait_for_postgres()
    version = ensure_database(db)
    ensure_tenant(db, tenant)
    ensure_principal(db, tenant, cfg["admin_principal"])
    if not target:
        ensure_monitor()
    if target:
        # the listener is the engine's own face and stays with the data (decision 6): this host runs none; the
        # tools this host registers are granted to the database server's listener role when it has one
        lu = "maludb-mc2dbd"
        lc = cfg.get("listener") or {}
        url, listener_user = lc.get("url"), (lu if exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(lu)}") else None)
        tok = str(lc.get("token") or "")
        if url and tok.startswith("file:") and os.path.exists(tok[5:]):
            # the database server's listener token (its `maluctl db export`), kept where `maluctl token` and the vault look
            with open(os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(open(tok[5:]).read().strip() + "\n")
        elif not url and os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)       # the token of a listener this host no longer runs
        subprocess.run(["systemctl", "disable", "--now", "--quiet", LISTENER_UNIT], check=False, capture_output=True)
        log(f"listener: on the database server ({url or 'no url in listener.url'})")
    else:
        url, listener_user = ensure_listener(cfg, db)
    ops = operator_users(cfg.get("operators", "auto"))
    ensure_operators(db, tenant, ops)
    components = run_components(cfg, db, tenant)
    enroll = run_enroll(cfg)
    appserver = run_application_server(cfg, enroll) if is_application_server(cfg) else None
    os.makedirs(STATE_DIR, exist_ok=True)
    summary = {"provisioned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "role": "application-server" if appserver is not None else None, "application_server": appserver,
               "platform_suffix": platform_suffix() or None,
               "database": db, "maludb_core": version, "tenant": tenant,
               "admin_principal": cfg["admin_principal"]["ref"], "listener": url,
               "listener_user": listener_user, "token_file": TOKEN_FILE if os.path.exists(TOKEN_FILE) else None,
               "operators": ops, "components": components, "enroll": enroll,
               "database_server": ({k: target[k] for k in ("host", "port", "admin", "sslmode")} if target else None)}
    with open(DONE, "w") as f:
        json.dump(summary, f, indent=2); f.write("\n")
    log("done: " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(provision(force="--force" in sys.argv))
