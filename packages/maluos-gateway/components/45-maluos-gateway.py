"""MaluOS first-boot component: the inference gateway (maluos-gateway).

Creates the gateway's PostgreSQL role and tenant-schema tables, seeds the
catalogue (classes, tiers, the local Ollama backend and its aliases) when it
is empty, registers the MCP tool maluos.model_status on the listener, makes
the gateway a vault broker, starts the socket, and optionally installs Ollama
and pulls models (ollama.install / ollama.pull in /etc/maluos/gateway.yaml).
"""
import json, os, pwd, subprocess, sys, time

ROLE = "maluos-gateway"
SCHEMA = "/usr/share/maluos-gateway/schema.sql"
CONF = "/etc/maluos/gateway.yaml"
VAULT_CONF = "/etc/maluos/vault.yaml"
DAEMON = "/usr/lib/maluos/maluos_gateway/server.py"
TABLES = ("maluos_backend", "maluos_tier", "maluos_alias", "maluos_class", "maluos_policy", "maluos_token", "maluos_gateway_status")
SEQUENCES = ("maluos_backend_backend_id_seq", "maluos_policy_policy_id_seq", "maluos_token_token_id_seq", "maluos_ledger_ledger_id_seq")


def provision(ctx):
    log, psql, exists, qi, ql = ctx["log"], ctx["psql"], ctx["exists"], ctx["qi"], ctx["ql"]
    db, tenant = ctx["db"], ctx["tenant"]
    if not os.path.exists(DAEMON):
        return None
    try:
        pwd.getpwnam(ROLE)
    except KeyError:
        raise RuntimeError(f"system user {ROLE} missing (package postinst did not run?)")
    sys.path.insert(0, "/usr/lib/maluos")
    from maluos_gateway.config import Config
    cfg = Config(CONF)
    ccfg = (ctx["cfg"].get("components") or {}).get("maluos-gateway") or {}

    # 1. role, schema, grants
    ensure_schema(psql, exists, qi, ql, db, tenant)
    log(f"gateway: schema in {tenant}, grants to {ROLE}")

    # 2. catalogue seed (only when empty)
    seeded = seed_catalog(psql, qi, ql, db, tenant, cfg)
    if seeded:
        log(f"gateway: seeded catalogue ({seeded})")

    # 3. MCP tool on the listener
    listener_user = unit_user("maludb-mc2dbd.service") or "maludb-mc2dbd"
    register_tool(psql, exists, qi, ql, db, tenant, listener_user)

    # 4. configuration: database/tenant; the gateway is a vault broker
    import yaml
    conf = {}
    if os.path.exists(CONF):
        with open(CONF) as f:
            conf = yaml.safe_load(f) or {}
    want = dict(conf); want.update({"database": db, "tenant": tenant})
    for k in ("ollama", "tcp"):
        if isinstance(ccfg.get(k), dict):
            want[k] = {**(want.get(k) or {}), **ccfg[k]}
    if want != conf:
        with open(CONF, "w") as f:
            f.write("# MaluOS inference gateway (maluos-gateway). database/tenant are set by first boot.\n"
                    "# See docs/phase6-slice2-gateway.md; the catalogue (tiers, aliases, classes, policies)\n"
                    "# lives in the database: maluctl gateway catalog.\n")
            yaml.safe_dump(want, f, sort_keys=True)
        os.chmod(CONF, 0o644)
    vconf = {}
    if os.path.exists(VAULT_CONF):
        with open(VAULT_CONF) as f:
            vconf = yaml.safe_load(f) or {}
    brokers = list(vconf.get("brokers") or [])
    if ROLE not in brokers:
        vconf["brokers"] = brokers + [ROLE]
        with open(VAULT_CONF, "w") as f:
            yaml.safe_dump(vconf, f, sort_keys=True)
        log("gateway: registered as a vault broker")

    # 5. Ollama (optional)
    cfg = Config(CONF)
    oll = cfg["ollama"]
    installed = os.path.exists("/usr/local/bin/ollama")
    if oll.get("install") and not installed:
        log("gateway: installing Ollama (ollama.install: true)")
        r = subprocess.run(["/usr/lib/maluos/maluos-ollama-install", "--version", str(oll.get("version") or "")], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"warning: Ollama install failed: {r.stderr.strip()[-300:]}")
        else:
            installed = True

    # 6. start the gateway
    subprocess.run(["systemctl", "enable", "--quiet", "maluos-gateway.socket"], check=False)
    subprocess.run(["systemctl", "start", "maluos-gateway.socket"], check=False)
    subprocess.run(["systemctl", "restart", "maluos-gateway.service"], check=False)
    import maluos_vault_client  # noqa: F401  (same socket client style)
    healthy, status = False, None
    for _ in range(30):
        try:
            status = gw_get("/v1/maluos/health")
            if status.get("ok"):
                healthy = True; break
        except Exception:
            pass
        time.sleep(1)
    if not healthy:
        log("warning: gateway not healthy (journalctl -u maluos-gateway)")
        return {"healthy": False, "socket": cfg["socket"]}

    # 7. pulls (long; only when the local backend is up)
    pulled = []
    if installed and oll.get("pull"):
        for model in oll["pull"]:
            try:
                for _ in gw_stream("/api/pull", {"model": model}):
                    pass
                pulled.append(model); log(f"gateway: pulled {model}")
            except Exception as e:
                log(f"warning: pull {model}: {str(e)[:160]}")
    log(f"gateway healthy at {cfg['socket']}; tcp {'on' if cfg['tcp'].get('enabled') else 'off'}; ollama {'installed' if installed else 'not installed (maluctl gateway ollama install)'}")
    return {"healthy": True, "socket": cfg["socket"], "role": ROLE, "tcp": cfg["tcp"] if cfg["tcp"].get("enabled") else None,
            "ollama_installed": installed, "pulled": pulled, "mcp_tool": "maluos.model_status"}


def ensure_schema(psql, exists, qi, ql, db, tenant, role=ROLE, schema=SCHEMA):
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(role)}"):
        psql(f"CREATE ROLE {qi(role)} LOGIN")
    r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db,
                        "-c", f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public;", "-f", schema],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gateway schema failed: {r.stderr.strip()[-400:]}")
    t, rl = qi(tenant), qi(role)
    psql(f"""GRANT CONNECT ON DATABASE {qi(db)} TO {rl};
             GRANT USAGE ON SCHEMA maludb_core TO {rl};
             GRANT USAGE ON SCHEMA {t} TO {rl};
             GRANT SELECT ON maludb_core."malu$principal", maludb_core."malu$principal_scope" TO {rl};
             GRANT SELECT ON {t}.maludb_principal, {t}.maludb_principal_scope TO {rl};
             GRANT SELECT ON maludb_core."malu$model_alias", maludb_core."malu$account" TO {rl};
             ALTER ROLE {rl} BYPASSRLS;  -- the engine queue holds every account's requests (model_request_tenant policy)
             GRANT SELECT, UPDATE ON maludb_core."malu$model_request" TO {rl};
             GRANT SELECT, INSERT ON maludb_core."malu$model_response" TO {rl};
             GRANT USAGE, SELECT ON maludb_core."malu$model_response_response_id_seq" TO {rl};""", db)
    psql(f"""SET ROLE {t};
             GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(f'{t}.{x}' for x in TABLES)} TO {rl};
             GRANT SELECT, INSERT ON {t}.maluos_ledger TO {rl};
             GRANT USAGE, SELECT ON {', '.join(f'{t}.{s}' for s in SEQUENCES)} TO {rl};""", db)


def seed_catalog(psql, qi, ql, db, tenant, cfg):
    pre = f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public; "
    done = []
    seed, oll = cfg["seed"], cfg["ollama"]
    if psql(pre + "SELECT count(*) FROM maluos_class", db) == "0":
        for c in seed["classes"]:
            psql(pre + f"INSERT INTO maluos_class (name, priority, weight, max_queue, fallback_wait_s, description) VALUES "
                       f"({ql(c['name'])}, {int(c['priority'])}, {int(c.get('weight', 1))}, {int(c.get('max_queue', 100))}, "
                       f"{'NULL' if c.get('fallback_wait_s') is None else int(c['fallback_wait_s'])}, {ql(c.get('description'))})", db)
        done.append("classes")
    if psql(pre + "SELECT count(*) FROM maluos_policy WHERE subject_kind='default'", db) == "0":
        psql(pre + "INSERT INTO maluos_policy (subject_kind, subject_ref, default_class, cloud_allowed) VALUES ('default', '', NULL, true)", db)
        done.append("default policy")
    if psql(pre + "SELECT count(*) FROM maluos_backend", db) == "0":
        cap = json.dumps({"max_concurrent": int(oll.get("max_concurrent") or 1)})
        opts = json.dumps({"keep_alive": oll.get("keep_alive") or "30m", "keep_warm": list(oll.get("keep_warm") or [])})
        psql(pre + f"INSERT INTO maluos_backend (name, kind, endpoint, capacity, options) VALUES ('ollama-local', 'ollama_local', {ql(oll.get('url'))}, {ql(cap)}::jsonb, {ql(opts)}::jsonb)", db)
        done.append("backend ollama-local")
    if psql(pre + "SELECT count(*) FROM maluos_tier", db) == "0":
        for name, t in (seed.get("tiers") or {}).items():
            psql(pre + f"INSERT INTO maluos_tier (name, description) VALUES ({ql(name)}, {ql(t.get('description'))})", db)
            for i, model in enumerate(t.get("local") or []):
                psql(pre + f"INSERT INTO maluos_alias (name, tier, backend, model, position) VALUES ({ql(name)}, {ql(name)}, 'ollama-local', {ql(model)}, {i}) ON CONFLICT DO NOTHING", db)
        done.append("tiers")
    return ", ".join(done)


def register_tool(psql, exists, qi, ql, db, tenant, listener_user):
    t = qi(tenant)
    if not exists("""SELECT 1 FROM maludb_core."malu$mc2db_server" WHERE server_name='maluos'""", db):
        psql("SELECT mc2db.create_server('maluos', 'MaluOS', 'MaluOS host services: the inference gateway and the vault')", db)
    if not exists("""SELECT 1 FROM maludb_core."malu$mc2db_tool" WHERE tool_name='maluos.model_status'""", db):
        psql(f"""SELECT mc2db.register_tool(
                   server_name => 'maluos', tool_name => 'maluos.model_status',
                   description => 'Inference gateway state: queue depth, expected wait per class, backends and their loaded models, tiers.',
                   implementation_type => 'sql_function',
                   input_schema => '{{"type":"object","properties":{{}},"additionalProperties":false}}'::jsonb,
                   output_schema => '{{"type":"object"}}'::jsonb,
                   impl_metadata => jsonb_build_object('function_signature', {ql(f'{tenant}.maluos_model_status(jsonb, jsonb)')}))""", db)
    lr = qi(listener_user)
    if exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(listener_user)}"):
        psql(f"""GRANT USAGE ON SCHEMA {t} TO {lr};
                 GRANT SELECT ON {t}.maluos_gateway_status TO {lr};
                 GRANT EXECUTE ON FUNCTION {t}.maluos_model_status(jsonb, jsonb) TO {lr};""", db)


def unit_user(unit):
    r = subprocess.run(["systemctl", "show", "-p", "User", "--value", unit], capture_output=True, text=True)
    return r.stdout.strip()


def gw_get(path):
    import http.client, socket as so
    from maluos_gateway.config import Config
    sock = Config(CONF)["socket"]

    class U(http.client.HTTPConnection):
        def connect(self):
            s = so.socket(so.AF_UNIX, so.SOCK_STREAM); s.settimeout(10); s.connect(sock); self.sock = s
    c = U("maluos-gateway"); c.request("GET", path); r = c.getresponse(); data = json.loads(r.read() or b"{}"); c.close()
    return data


def gw_stream(path, body):
    import http.client, socket as so
    from maluos_gateway.config import Config
    sock = Config(CONF)["socket"]

    class U(http.client.HTTPConnection):
        def connect(self):
            s = so.socket(so.AF_UNIX, so.SOCK_STREAM); s.settimeout(3600); s.connect(sock); self.sock = s
    c = U("maluos-gateway"); c.request("POST", path, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = c.getresponse()
    if r.status >= 400:
        raise RuntimeError(r.read().decode()[:200])
    for line in r:
        obj = json.loads(line)
        if "error" in obj:
            raise RuntimeError(obj["error"])
        yield obj
    c.close()
