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
    host = next((l.split("=", 1)[1] for l in lines if l.startswith("MALUDB_API_HOST=")), "127.0.0.1")
    port = next((l.split("=", 1)[1] for l in lines if l.startswith("MALUDB_API_PORT=")), "8000")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    # 3. (re)start and wait for /health
    subprocess.run(["systemctl", "enable", "--quiet", "maludb-api.service"], check=False)
    subprocess.run(["systemctl", "restart", "maludb-api.service"], check=False)
    for _ in range(30):
        try:
            with urllib.request.urlopen(url + "/health", timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(2)
    else:
        log(f"warning: maludb-api not healthy at {url}/health")
        return {"url": url, "healthy": False}

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

    # 5. sweeps
    for s in SWEEPS:
        p = f"/etc/maludb/{s}.env"
        el = set_env(set_env(read_env(p), "MALU_API_URL", url), "MALU_TOKEN", token)
        with open(os.open(p, os.O_WRONLY | os.O_TRUNC), "w") as f:
            f.write("\n".join(el) + "\n")
        subprocess.run(["systemctl", "enable", "--now", "--quiet", f"maludb-{s}.timer"], check=False)
    return {"url": url, "healthy": True, "token_file": tok_file, "sweeps": list(SWEEPS)}
