#!/usr/bin/python3
"""MaluOS provisioning engine.

Creates the MaluDB database, the tenant, the administrator principal, the
listener and operator PostgreSQL roles, the listener bearer token, and starts
the MC2DB listener. Every step checks the current state first, so the whole
run is idempotent and `maluctl provision` can repeat it at any time.
"""
import json, os, pwd, re, secrets, shutil, subprocess, sys, time, urllib.request

CONFIG = "/etc/maluos/firstboot.yaml"
STATE_DIR = "/var/lib/maluos/firstboot"
DONE = os.path.join(STATE_DIR, "done")
SECRETS_DIR = "/var/lib/maluos/secrets"
TOKEN_FILE = os.path.join(SECRETS_DIR, "mc2dbd.token")
LISTENER_UNIT = "maludb-mc2dbd.service"
LISTENER_CONF = "/etc/maludb/maludb-mc2dbd.conf"

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


def psql(sql, db="postgres", check=True):
    cmd = ["runuser", "-u", "postgres", "--", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}\n  sql: {sql[:200]}")
    return r.stdout.strip()


def exists(sql, db="postgres"):
    return psql(sql, db) == "1"


def cluster_port(version="18", name="main"):
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
    deadline = time.time() + timeout
    while time.time() < deadline:
        if subprocess.run(["runuser", "-u", "postgres", "--", "pg_isready", "-q"]).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready")


# ---------------------------------------------------------------- steps
def ensure_database(db):
    if not exists(f"SELECT 1 FROM pg_database WHERE datname={ql(db)}"):
        psql(f"CREATE DATABASE {qi(db)}")
        log(f"created database {db}")
    for ext in ("vector", "maludb_core"):
        if not exists(f"SELECT 1 FROM pg_extension WHERE extname={ql(ext)}", db):
            psql(f"CREATE EXTENSION {qi(ext)} CASCADE", db)
            log(f"created extension {ext} in {db}")
    psql(f"ALTER DATABASE {qi(db)} SET search_path TO maludb_core, public")
    return psql("SELECT extversion FROM pg_extension WHERE extname='maludb_core'", db)


def ensure_role(name, *attrs):
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(name)}"):
        psql(f"CREATE ROLE {qi(name)} {' '.join(attrs)}")
        log(f"created role {name}")
        return True
    return False


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
    for u in users:
        ensure_role(u, "LOGIN", "SUPERUSER", "CREATEDB")
        psql(f"ALTER ROLE {qi(u)} IN DATABASE {qi(db)} SET search_path TO {qi(tenant)}, maludb_core, public")
    if users:
        log(f"operator roles: {', '.join(users)}")


COMPONENTS_DIR = "/usr/lib/maluos/components"


def run_components(cfg, db, tenant):
    """Run /usr/lib/maluos/components/*.py in name order. Each defines
    provision(ctx) and returns a JSON-able summary or None (not applicable)."""
    import importlib.util, glob
    results = {}
    wanted = cfg.get("components") or {}
    ctx = {"cfg": cfg, "db": db, "tenant": tenant, "log": log, "psql": psql, "exists": exists,
           "qi": qi, "ql": ql, "secrets_dir": SECRETS_DIR, "set_env": set_env, "read_env_file": read_env_file}
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(COMPONENTS_DIR, "*.py"))):
        name = os.path.basename(path)[:-3].split("-", 1)[-1]
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


def provision(force=False):
    if os.geteuid() != 0:
        sys.exit("must run as root")
    if os.path.exists(DONE) and not force:
        log("already provisioned (use --force to re-run)"); return 0
    cfg = load_config()
    db, tenant = cfg["database"], cfg["tenant"]["name"]
    log(f"provisioning database={db} tenant={tenant}")
    wait_for_postgres()
    version = ensure_database(db)
    ensure_tenant(db, tenant)
    ensure_principal(db, tenant, cfg["admin_principal"])
    url, listener_user = ensure_listener(cfg, db)
    ops = operator_users(cfg.get("operators", "auto"))
    ensure_operators(db, tenant, ops)
    components = run_components(cfg, db, tenant)
    os.makedirs(STATE_DIR, exist_ok=True)
    summary = {"provisioned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "database": db, "maludb_core": version, "tenant": tenant,
               "admin_principal": cfg["admin_principal"]["ref"], "listener": url,
               "listener_user": listener_user, "token_file": TOKEN_FILE if os.path.exists(TOKEN_FILE) else None,
               "operators": ops, "components": components}
    with open(DONE, "w") as f:
        json.dump(summary, f, indent=2); f.write("\n")
    log("done: " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(provision(force="--force" in sys.argv))
