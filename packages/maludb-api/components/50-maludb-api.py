"""MaluOS first-boot component: the MaluDB API server.

Runs after the core provisioning (database, tenant, principal). Gives the
tenant role a password (the API connects over TCP with scram), seals the
auth store, restarts the service, mints the tenant's API token, and enables
the embedding and reindex sweeps with that token.
"""
import json, os, secrets, subprocess, time, urllib.request

ENV = "/etc/maludb/maludb-api.env"
SWEEPS = ("embedding-worker", "skill-reindex", "memory-reindex")


def provision(ctx):
    log, psql, qi, ql = ctx["log"], ctx["psql"], ctx["qi"], ctx["ql"]
    db, tenant, secrets_dir = ctx["db"], ctx["tenant"], ctx["secrets_dir"]
    set_env, read_env = ctx["set_env"], ctx["read_env_file"]
    if not os.path.exists("/usr/lib/maludb-api/app/main.py"):
        return None

    # 1. tenant database password (peer auth does not reach a TCP client)
    pw_file = os.path.join(secrets_dir, f"pg-{tenant}.password")
    if os.path.exists(pw_file):
        password = open(pw_file).read().strip()
    else:
        password = secrets.token_urlsafe(24)
        with open(os.open(pw_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(password + "\n")
    psql(f"ALTER ROLE {qi(tenant)} WITH LOGIN PASSWORD {ql(password)}")

    # 2. seal the auth store (the key is a Fernet key, as `python3 -m app.seal_store --new-key` makes)
    from cryptography.fernet import Fernet
    lines = read_env(ENV)
    current = next((l.split("=", 1)[1] for l in lines if l.startswith("MALUDB_STORE_KEY=")), "")
    try:
        Fernet(current.encode()) if current else None
        valid = bool(current)
    except Exception:
        valid = False
    if not valid:
        # Only safe while the auth store holds nothing sealed, i.e. at provisioning time.
        lines = set_env(lines, "MALUDB_STORE_KEY", Fernet.generate_key().decode())
        with open(os.open(ENV, os.O_WRONLY | os.O_TRUNC), "w") as f:
            f.write("\n".join(lines) + "\n")
        log("maludb-api: generated MALUDB_STORE_KEY")
    # Phase 14: the API stays on this host; its PostgreSQL is the database server's when there is one. The API
    # is a libpq client, so PGSSLMODE/PGSSLROOTCERT in its environment verify the server's certificate.
    dbt = ctx.get("database_target") or {}
    want = {"MALUDB_PG_HOST": dbt["host"] if dbt else "localhost", "MALUDB_PG_PORT": str(dbt["port"]) if dbt else "5432"}
    if dbt:
        want["PGSSLMODE"] = dbt["sslmode"]
        if dbt.get("ca"):
            want["PGSSLROOTCERT"] = dbt["ca"]
    new_lines = [l for l in lines if dbt or not l.startswith(("PGSSLMODE=", "PGSSLROOTCERT="))]
    for k, v in want.items():
        new_lines = set_env(new_lines, k, v)
    if new_lines != lines:
        lines = new_lines
        with open(os.open(ENV, os.O_WRONLY | os.O_TRUNC), "w") as f:
            f.write("\n".join(lines) + "\n")
        log(f"maludb-api: PostgreSQL at {want['MALUDB_PG_HOST']}:{want['MALUDB_PG_PORT']}")
    host = next((l.split("=", 1)[1] for l in lines if l.startswith("MALUDB_API_HOST=")), "127.0.0.1")
    port = next((l.split("=", 1)[1] for l in lines if l.startswith("MALUDB_API_PORT=")), "8000")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    # 3. (re)start and wait for /health
    subprocess.run(["systemctl", "enable", "--quiet", "maludb-api.service"], check=False)
    subprocess.run(["systemctl", "restart", "maludb-api.service"], check=False)
    # by the clock, not by a count of tries: a refused connection returns at once, and a loaded host starts the
    # workers slowly (a re-provisioning restarts every service before this one)
    deadline = time.monotonic() + 240
    while True:
        try:
            with urllib.request.urlopen(url + "/health", timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            pass
        if time.monotonic() > deadline:
            state = subprocess.run(["systemctl", "is-active", "maludb-api.service"], capture_output=True, text=True).stdout.strip()
            log(f"warning: maludb-api not healthy at {url}/health within 240s (unit {state}; see: journalctl -u maludb-api)")
            return {"url": url, "healthy": False}
        time.sleep(2)

    # 4. tenant API token
    tok_file = os.path.join(secrets_dir, "api.token")
    if os.path.exists(tok_file):
        token = open(tok_file).read().strip()
    else:
        body = json.dumps({"pg_dbname": db, "pg_user": tenant, "pg_password": password,
                           "role": "executor", "device_name": "maluos-firstboot"}).encode()
        req = urllib.request.Request(url + "/v1/tokens", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            token = json.load(r)["token"]
        with open(os.open(tok_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(token + "\n")
    log(f"maludb-api healthy at {url}; tenant token in {tok_file}")
    if ctx.get("store_secret"):
        ctx["store_secret"](f"pg-{tenant}-password", password, kind="password", provider="postgresql", env_var="PGPASSWORD")
        ctx["store_secret"]("maludb-api-token", token, kind="token", provider="maludb-api", env_var="MALU_TOKEN")

    # 5. sweeps
    for s in SWEEPS:
        p = f"/etc/maludb/{s}.env"
        el = set_env(set_env(read_env(p), "MALU_API_URL", url), "MALU_TOKEN", token)
        with open(os.open(p, os.O_WRONLY | os.O_TRUNC), "w") as f:
            f.write("\n".join(el) + "\n")
        subprocess.run(["systemctl", "enable", "--now", "--quiet", f"maludb-{s}.timer"], check=False)
    return {"url": url, "healthy": True, "token_file": tok_file, "sweeps": list(SWEEPS)}
