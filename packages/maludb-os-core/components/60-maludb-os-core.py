"""MaluOS first-boot component: the MaluDB Business OS kernel.

Native port of maludb-os-docker's bos-init (docs/install.md §3-§13) for a
MaluOS host where PostgreSQL, the MaluDB engine and the MaluDB API are
local. Runs after 50-maludb-api. Idempotent; every step checks its state.

Configuration (firstboot.yaml -> components.maludb-os-core):
  domain: maluos.local      names: <domain>, os.<domain>, app.<domain>
  scheme: http              http on a LAN; https when a TLS proxy sits in front
  proxy_address             https only: the proxy's address as this host sees it (192.168.100.1); the office's names
                            go to it in /etc/hosts, never to loopback, where nothing serves https; absent: no line is
                            written and the summary says so (docs/phase13-estate-behind-a-proxy.md, part 2)
  admin_email, admin_name   the first super-admin (default admin@<domain>)
  admin_password            optional; generated and stored otherwise
  model_key, model_name, model_provider_id   the first model registry row
  anthropic_api_key, openrouter_api_key      optional runner keys
  apps.install              the applications installed beside the kernel at first boot, in order (catalog keys;
                            default [hr, projects, helpdesk, spaces]; [] installs none)
  apps.ref                  key -> git tag or branch to clone (default: the repository's default branch)
  apps.propose_agents       keys whose agents are proposed rather than hired
The applications step (9) runs the kernel's own installer, bin/app_install.php apply, for each key
from github.com/maludb/maludb-os-<key> (maluos-apps carries the host tools it needs), with a marker
per application under /var/lib/maluos/business-os/apps so a re-run reconciles rather than repeats;
a failing application is logged and the next continues. `maluctl app names` lists the DNS names.
"""
import glob, json, os, secrets as pysecrets, shutil, socket, subprocess, sys, time, urllib.request

sys.path.insert(0, "/usr/lib/maluos")

WWW = "/var/www"
BOS = "/etc/business-os"
STATE = "/var/lib/maluos/business-os"
DB = "maludb_os"
MEM_DB, MEM_USER = "maludb_os_memory", "maludb_os_mem"
ROLES = {"app_rw": "pw_app_rw", "app_records_ro": "pw_app_records_ro",
         "app_activity_ro": "pw_app_activity_ro", "app_runner": "pw_app_runner"}
UNITS = ["maludb-os-web", "maludb-os-records-mcp", "maludb-os-activity-mcp", "maludb-os-actions-mcp",
         "maludb-os-memory-mcp", "maludb-os-agent-runner", "maludb-os-activity-ingest.timer"]


def provision(ctx):
    log, psql, exists, qi, ql = ctx["log"], ctx["psql"], ctx["exists"], ctx["qi"], ctx["ql"]
    set_env, read_env = ctx["set_env"], ctx["read_env_file"]
    if not os.path.exists(f"{WWW}/bin/bootstrap_organizer.php"):
        return None
    cfg = (ctx["cfg"].get("components") or {}).get("maludb-os-core") or {}
    domain = cfg.get("domain") or "maluos.local"
    scheme = cfg.get("scheme") or "http"
    admin_email = cfg.get("admin_email") or f"admin@{domain}"
    admin_name = cfg.get("admin_name") or "Administrator"
    model_key = cfg.get("model_key") or "claude-fable-5-1"
    model_name = cfg.get("model_name") or "Claude Fable 5.1"
    model_provider_id = cfg.get("model_provider_id") or model_key
    sdir = os.path.join(ctx["secrets_dir"], "business-os")
    os.makedirs(sdir, mode=0o700, exist_ok=True); os.chmod(sdir, 0o700)
    os.makedirs(STATE, exist_ok=True); os.makedirs(BOS, exist_ok=True)

    def secret(name, nbytes=32, gen=None):
        f = os.path.join(sdir, name)
        if not os.path.exists(f) or os.path.getsize(f) == 0:
            val = gen() if gen else pysecrets.token_hex(nbytes)
            with open(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
                fh.write(val + "\n")
        return open(f).read().strip()

    def write_env(path, pairs, owner, mode):
        lines = read_env(path) if os.path.exists(path) else []
        for k, v in pairs.items():
            lines = set_env(lines, k, str(v))
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        shutil.chown(path, *owner)

    def www(*cmd, check=True):
        r = subprocess.run(["runuser", "-u", "www-data", "--", *cmd], cwd=WWW, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd[:3])} failed: {(r.stderr or r.stdout)[-400:]}")
        return r.stdout

    # ---- 1. the kernel's own names, so its URLs resolve on this host: under http on loopback (Apache answers there);
    # under https at the proxy's address (components.maludb-os-core.proxy_address), never on loopback, where nothing
    # serves https, or nowhere when no address is given (docs/phase13-estate-behind-a-proxy.md, part 2)
    import maludb_os_apps as A
    names = [domain, f"www.{domain}", f"os.{domain}", f"app.{domain}"]
    proxy_address, proxy_why = (A.resolve_address(cfg.get("proxy_address")) if scheme == "https" else (None, "http"))
    if scheme == "https" and cfg.get("proxy_address") and proxy_address is None:
        log(f"warning: proxy_address: {proxy_why}; the office's names are left to DNS")
    elif scheme == "https" and proxy_address and str(cfg.get("proxy_address")).strip() != proxy_address:
        log(f"proxy_address {cfg.get('proxy_address')} resolves to {proxy_address}")

    def point_names(all_names):
        """/etc/hosts for the office's names (the four, then the applications' once installed)."""
        text = open("/etc/hosts").read()
        if scheme == "https":
            new, changed = A.office_hosts(text, all_names, proxy_address)
            how = f"proxy {proxy_address}" if proxy_address else "none"
        else:
            new, changed = A.office_hosts(text, [], None)                  # a stale block from an https run goes
            missing = [n for n in all_names if f" {n}" not in new and f"\t{n}" not in new]
            if missing:
                new = new + "127.0.0.1 " + " ".join(missing) + "\n"; changed = True
            how = "loopback"
        if changed:
            with open("/etc/hosts", "w") as fh:
                fh.write(new)
        return how
    hosts_mode = point_names(names)
    hosts_note = {"loopback": "the kernel's names on loopback (http)",
                  "none": "https without proxy_address: no /etc/hosts line for the office's names; set components.maludb-os-core.proxy_address "
                          "(the proxy's address as this host sees it) or give the names to this host's DNS, else the office cannot reach its own URLs"}.get(
                      hosts_mode, f"the kernel's names at the proxy's address {proxy_address} (https)")
    log("hosts: " + hosts_note)

    # ---- 2. the kernel's activity memory: its own MaluDB database, role and schema
    mem_pw = secret("mem_password", 24)
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(MEM_USER)}"):
        psql(f"CREATE ROLE {qi(MEM_USER)} LOGIN PASSWORD {ql(mem_pw)}")
    else:
        psql(f"ALTER ROLE {qi(MEM_USER)} WITH LOGIN PASSWORD {ql(mem_pw)}")
    if not exists(f"SELECT 1 FROM pg_database WHERE datname={ql(MEM_DB)}"):
        psql(f"CREATE DATABASE {qi(MEM_DB)}")
        log(f"created memory database {MEM_DB}")
    for ext in ("vector", "maludb_core"):
        if not exists(f"SELECT 1 FROM pg_extension WHERE extname={ql(ext)}", MEM_DB):
            psql(f"CREATE EXTENSION {qi(ext)} CASCADE", MEM_DB)
    psql(f"ALTER DATABASE {qi(MEM_DB)} SET search_path TO maludb_core, public")
    psql(f"GRANT maludb_user TO {qi(MEM_USER)}", MEM_DB)
    if not exists(f"SELECT 1 FROM pg_namespace WHERE nspname={ql(MEM_USER)}", MEM_DB):
        psql(f"CREATE SCHEMA {qi(MEM_USER)} AUTHORIZATION {qi(MEM_USER)}", MEM_DB)
    psql(f"ALTER ROLE {qi(MEM_USER)} IN DATABASE {qi(MEM_DB)} SET search_path TO {qi(MEM_USER)}, maludb_core, public")
    psql(f"SET ROLE {qi(MEM_USER)}; SET search_path TO {qi(MEM_USER)}, maludb_core, public; "
         f"SELECT count(*) FROM maludb_core.enable_memory_schema();", MEM_DB)
    if exists("SELECT 1 FROM pg_proc WHERE proname='grant_memory_access' AND pronamespace='maludb_core'::regnamespace", MEM_DB):
        psql(f"SELECT maludb_core.grant_memory_access({ql(MEM_USER)})", MEM_DB, check=False)
    log(f"memory database {MEM_DB} / {MEM_USER} ready")

    # ---- 3. a MaluDB API token for the kernel's memory
    api_env = read_env("/etc/maludb/maludb-api.env")
    api_port = next((l.split("=", 1)[1] for l in api_env if l.startswith("MALUDB_API_PORT=")), "8000")
    api_url = f"http://127.0.0.1:{api_port}"
    tok_file = os.path.join(sdir, "maludb.token")
    token = open(tok_file).read().strip() if os.path.exists(tok_file) else ""
    if token:
        try:
            urllib.request.urlopen(urllib.request.Request(api_url + "/v1/whoami", headers={"Authorization": f"Bearer {token}"}), timeout=5)
        except Exception:
            token = ""
    if not token:
        body = json.dumps({"pg_dbname": MEM_DB, "pg_user": MEM_USER, "pg_password": mem_pw, "role": "executor", "device_name": "business-os kernel"}).encode()
        for attempt in range(10):
            try:
                with urllib.request.urlopen(urllib.request.Request(api_url + "/v1/tokens", data=body, headers={"Content-Type": "application/json"}), timeout=20) as r:
                    token = json.load(r)["token"]; break
            except Exception as e:
                if attempt == 9: raise
                time.sleep(3)
        with open(os.open(tok_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
            fh.write(token + "\n")

    # ---- 4. the kernel database and its migrations (resumable ledger)
    if not exists(f"SELECT 1 FROM pg_database WHERE datname={ql(DB)}"):
        psql(f"CREATE DATABASE {qi(DB)}")
        log(f"created kernel database {DB}")
    ledger = os.path.join(STATE, "migrations-applied")
    done = set(open(ledger).read().split()) if os.path.exists(ledger) else set()
    applied = 0
    for f in sorted(glob.glob(f"{WWW}/db/*.sql")):
        base = os.path.basename(f)
        if base in done: continue
        r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", DB, "-f", f],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"migration {base} failed: {r.stderr[-600:]}")
        with open(ledger, "a") as fh: fh.write(base + "\n")
        applied += 1
    log(f"migrations: {applied} applied, {len(done)} already in the ledger")

    # ---- 5. role passwords
    pws = {role: secret(name, 24) for role, name in ROLES.items()}
    for role, pw in pws.items():
        if exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(role)}"):
            psql(f"ALTER ROLE {qi(role)} WITH LOGIN PASSWORD {ql(pw)}")

    # ---- 6. configuration files
    keys = {n: secret(n) for n in ("app_totp_key", "action_token_key", "secrets_key", "web_internal_key",
                                   "runner_key", "actions_relay_key", "proxy_key_secret")}
    envf = f"{WWW}/config/.env"
    if not os.path.exists(envf):
        shutil.copy(f"{WWW}/config/.env.example", envf)
    pairs = {"APP_ENV": "prod", "APP_URL": f"{scheme}://app.{domain}", "OS_HOST": f"os.{domain}", "APP_HOST": f"app.{domain}",
             "SESSION_COOKIE_DOMAIN": f".{domain}", "DB_HOST": "127.0.0.1", "DB_PORT": "5432", "DB_NAME": DB,
             "DB_USER": "app_rw", "DB_PASSWORD": pws["app_rw"],
             "MCP_RECORDS_DB_USER": "app_records_ro", "MCP_RECORDS_DB_PASSWORD": pws["app_records_ro"],
             "MCP_ACTIVITY_DB_USER": "app_activity_ro", "MCP_ACTIVITY_DB_PASSWORD": pws["app_activity_ro"],
             "APP_TOTP_KEY": keys["app_totp_key"], "ACTION_TOKEN_KEY": keys["action_token_key"], "SECRETS_KEY": keys["secrets_key"],
             "WEB_INTERNAL_KEY": keys["web_internal_key"], "RUNNER_KEY": keys["runner_key"], "ACTIONS_RELAY_KEY": keys["actions_relay_key"],
             "MALUDB_API_URL": api_url, "MALUDB_API_TOKEN": token, "MALUDB_MEMORY_DB": MEM_DB, "MALUDB_MEMORY_USER": MEM_USER,
             "MALUDB_MEMORY_PASSWORD": mem_pw, "MAIL_FROM": f"no-reply@{domain}"}
    if cfg.get("malumail_api_key"): pairs["MALUMAIL_API_KEY"] = cfg["malumail_api_key"]
    write_env(envf, pairs, ("root", "www-data"), 0o640)
    webenv = f"{WWW}/web/.env.local"
    write_env(webenv, {"API_BASE_URL": "http://127.0.0.1:8080", "LOGIN_URL": f"{scheme}://app.{domain}/login",
                       "WEB_INTERNAL_KEY": keys["web_internal_key"]}, ("www-data", "www-data"), 0o640)
    renv = f"{BOS}/runner.env"
    if not os.path.exists(renv):
        shutil.copy(f"{WWW}/docs/deploy/runner.env.example", renv)
    rpairs = {"RUNNER_DB_USER": "app_runner", "RUNNER_DB_PASSWORD": pws["app_runner"], "RUNNER_DB_NAME": DB, "RUNNER_DB_HOST": "127.0.0.1",
              "ACTION_TOKEN_KEY": keys["action_token_key"], "RUNNER_KEY": keys["runner_key"], "PROXY_KEY_SECRET": keys["proxy_key_secret"],
              "MALUDB_API_URL": api_url, "MALUDB_API_TOKEN": token, "RUNNER_SCHEDULER": "on"}
    for k in ("anthropic_api_key", "openrouter_api_key"):
        if cfg.get(k): rpairs[k.upper()] = cfg[k]
    write_env(renv, rpairs, ("root", "bos-runner"), 0o640)

    # ---- 7. Apache: the kernel's vhosts rendered for the domain; the web drop-in
    vhost = open(f"{WWW}/docs/deploy/apache-react-cutover.conf").read().replace("subello.com", domain)
    open("/etc/apache2/sites-available/maludb-os.conf", "w").write(vhost)
    landing = f"{WWW}/landing/index.html"
    if os.path.exists(landing):
        s = open(landing).read()
        if "subello.com" in s: open(landing, "w").write(s.replace("subello.com", domain))
    subprocess.run(["a2dissite", "-q", "000-default"], check=False, capture_output=True)
    subprocess.run(["a2ensite", "-q", "maludb-os"], check=False, capture_output=True)
    os.makedirs("/etc/systemd/system/maludb-os-web.service.d", exist_ok=True)
    dropin = open(f"{WWW}/docs/deploy/maludb-os-web.service.d-cutover.conf").read().replace("subello.com", domain)
    open("/etc/systemd/system/maludb-os-web.service.d/cutover.conf", "w").write(dropin)
    r = subprocess.run(["apache2ctl", "configtest"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("apache configtest failed: " + r.stderr[-300:])
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "--now", "--quiet", "apache2", "cron"], check=False)
    subprocess.run(["systemctl", "restart", "apache2"], check=False)
    subprocess.run(["systemctl", "enable", "--now", "--quiet", *UNITS], check=False)
    subprocess.run(["systemctl", "restart", *UNITS], check=False)
    for _ in range(45):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/v1/health", timeout=3) as r:
                if r.status == 200: break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("the kernel's PHP API on 127.0.0.1:8080 did not become healthy")

    # ---- 8. the first super-admin, the first model, cron, the kernel's agents
    count = psql(f"SELECT count(*) FROM members WHERE lower(email)=lower({ql(admin_email)})", DB)
    pw_file = os.path.join(sdir, "admin-password")
    if count == "0":
        pw = cfg.get("admin_password") or secret("admin-password", gen=lambda: pysecrets.token_urlsafe(12))
        www("php", "bin/bootstrap_organizer.php", "--email", admin_email, "--name", admin_name, "--password", pw)
        log(f"super-admin {admin_email} created")
    if ctx.get("store_secret") and os.path.exists(pw_file):
        ctx["store_secret"]("business-os-admin-password", open(pw_file).read().strip(), kind="password", provider="business-os")
    if psql(f"SELECT count(*) FROM model_registry WHERE model_key={ql(model_key)}", DB) == "0":
        psql("INSERT INTO model_registry (model_key, display_name, provider, provider_model_id, harness, price_input_per_mtok, "
             "price_output_per_mtok, price_cache_read_per_mtok, price_cache_write_per_mtok, currency, status, auth_mode) VALUES "
             f"({ql(model_key)}, {ql(model_name)}, 'anthropic', {ql(model_provider_id)}, 'claude_agent_sdk', 10, 50, 0.25, 12.5, 'USD', 'active', 'api_key')", DB)
    logf = "/var/log/maludb-os-cron.log"
    if not os.path.exists(logf):
        open(logf, "a").close(); shutil.chown(logf, "www-data", "www-data")
    subprocess.run(["crontab", "-u", "www-data", f"{WWW}/docs/deploy/crontab.example"], check=False, capture_output=True)
    for marker, cmd in (("hire-installer", ["php", "bin/hire_installation_agent.php", "--by", admin_email]),
                        ("hire-jev", ["php", "bin/hire_jev_prompt_writer.php", "--by", admin_email])):
        m = os.path.join(STATE, marker)
        if not os.path.exists(m):
            try:
                www(*cmd); open(m, "w").close()
            except Exception as e:
                log(f"warning: {marker}: {str(e)[:200]}")

    # ---- 9. the applications (the maluos-apps proposal, phase 1): the kernel's installer for each key, in order,
    # HR first by default (the one application that writes the directory). Markers under STATE/apps; the installer's
    # output beside them as <key>.log. The step waits for DNS and HTTPS to github.com first: a clone needs both.
    try:
        apps_cfg = A.apps_config(cfg.get("apps"))
    except ValueError as e:
        log(f"warning: {e}; no application installed"); apps_cfg = {"install": [], "ref": {}, "propose_agents": []}
    apps = A.install_apps(apps_cfg, admin_email, domain, scheme, os.path.join(STATE, "apps"), www=WWW, log=log, proxy_address=proxy_address)
    if apps_cfg["install"]:
        log(f"applications: {len(apps['installed'])} installed ({', '.join(apps['installed']) or '-'}), "
            f"{len(apps['failed'])} failed ({', '.join(apps['failed']) or '-'})")
    names = A.office_names(domain)
    log("names the office needs: " + " ".join(names))
    if scheme == "https" and names != [domain, f"www.{domain}", f"app.{domain}", f"os.{domain}"]:
        point_names(names)                     # the applications' names join the block (and leave any loopback line the installer wrote)

    return {"domain": domain, "scheme": scheme, "urls": {"os": f"{scheme}://os.{domain}", "app": f"{scheme}://app.{domain}"},
            "database": DB, "memory_database": MEM_DB, "admin_email": admin_email,
            "admin_password_file": pw_file if os.path.exists(pw_file) else None,
            "apps": apps, "names": names, "healthy": True,
            "proxy_address": proxy_address, "hosts": {"mode": hosts_mode, "address": proxy_address if hosts_mode.startswith("proxy") else ("127.0.0.1" if hosts_mode == "loopback" else None), "note": hosts_note}}
