"""maluctl office: this desk and its office (Phase 12 slice 6, docs/desk-enrolment.md).

A MaluOS desktop joins a Business OS office as a *desk*: a location in the
office's estate that belongs to the person at the keyboard. Enrolment
exchanges a one-time code the office gave the person for a desk token; the
token lives in the person's vault compartment (office-desk-token), never in
a file. The office's model endpoint becomes a rung of this desk's gateway
(--model office) applied with that token on the person's behalf, and the
session heartbeats the office while the person is signed in, so the estate
shows the desk and whether it is online.

  sudo maluctl office enroll URL --code CODE [--name "Ed's desk"] [--owner LOGIN] [--no-gateway] [--force]
  maluctl office status [--json] [--live]          the configuration and the last heartbeat; --live asks the office
  maluctl office heartbeat [--presence online|offline] [--json]       as the desk's owner
  maluctl office apps [--json] [--refresh]         the MaluApps catalogue: the office's (endpoints.apps) over the
                                                   public one (download.maluos.com/apps/catalog.json, signed by the
                                                   MaluOS release key: catalog.json.asc, verified with the archive
                                                   keyring; refused unsigned), cached per user
  maluctl office apps install|remove|open ID       a web app becomes a launcher opening it in Firefox's own window;
                                                   a deb app installs from apt.maluos.com (pkexec apt-get)
  maluctl office agents [--json] [--refresh]       the office's agents this desk may use (endpoints.agents; Phase 12 slice 8)
  maluctl office agent ID card|activity|tasks [--json]       one of them: its card, its recent activity, the tasks sent from here
  maluctl office agent ID send TEXT         Phase 13 slice 2: a task to an estate agent, with this desk's signed envelope
  maluctl office inbox [--json] [--all]     the person's estate inbox (questions, decisions, results, notes)
  maluctl office inbox decide ID approve|deny [--note TEXT] | reply ID TEXT | read ID
  maluctl office estate action NODE restart_agent|start_agent|stop_agent|apply_updates|reboot [AGENT] [--wait S]
  maluctl office agents [--capability X]   the directory (the estate's agents and the office's own)
  sudo maluctl office key                   make and register this desk's signing key (desks enrolled before slice 2)
  maluctl office estate [--json] [--refresh]       the estate as this desk's owner may see it (endpoints.estate, published to
                                                   system managers; Phase 13 slice 1): nodes, their health, the open alerts
  maluctl office agent ID send TEXT [--json]       give it a task and wait for the answer (its task URL, the desk token)
  maluctl office inference [--json] [--refresh] [--all]   Phase 13 slice 3: the backends the estate publishes to this desk (its gateway's
                                                   rungs estate:NAME) and the peers allowed to call it; --refresh re-reads both now;
                                                   --all (an operator) every backend in the estate with its queue and wait
  sudo maluctl office inference --new-key          a new inference key (a desk enrolled before slice 3, or a rotation)
  sudo maluctl office leave [--keep-secret]

Agents: /etc/maluos/office.env names the office's endpoints (MALUOS_OFFICE_*)
for every maluos-agent@ unit. The owner lets an agent use the office's
models with `maluctl secret delegate --to agent:NAME --secret office-desk-token`
and read the token for the office's MCP servers with
`maluctl secret grant office-desk-token --to agent:NAME --level read`.
"""
import json, os, pwd, socket, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate.client import http as _estate_http, flat as _flat     # the shared client (maluos-estate, Phase 13 slice 1)

VERSION = "0.7.0"
SURFACE = 1
CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
ENVF = os.environ.get("MALUOS_OFFICE_ENV", "/etc/maluos/office.env")
SECRET = "office-desk-token"
INFERENCE_SECRET = "estate-inference-key"   # the estate's inference credential (Phase 13 slice 3), in the owner's compartment; the gateway holds a `use` grant
GATEWAY_USER = os.environ.get("MALUOS_GATEWAY_USER", "maluos-gateway")
INFERENCE_CACHE = os.environ.get("MALUOS_OFFICE_INFERENCE", "/run/maluos/office/inference.json")   # the gateway reads these (estate.py)
PEERS_CACHE = os.environ.get("MALUOS_OFFICE_PEERS", "/run/maluos/office/peers.json")
KEY_SECRET = "office-desk-key"              # the desk's ed25519 signing key (Phase 13 slice 2), in the owner's compartment beside the token
PLUGIN_DIR = os.environ.get("MALUCTL_PLUGIN_DIR", "/usr/lib/maluos/maluctl.d")
MALUCTL = os.environ.get("MALUCTL_BIN", "/usr/bin/maluctl")


def opt(args, name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        v = args[i + 1]; del args[i:i + 2]; return v
    return False if flag else default


def need_root():
    if os.geteuid() != 0:
        sys.exit("maluctl office: run with sudo")


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def http(method, url, body=None, token=None, timeout=20):
    """(status, json) for an office call (the shared client, as maluos-desk); raises when the office is unreachable."""
    return _estate_http(method, url, body, token, timeout, agent=f"maluos-desk/{VERSION}")


def facts():
    f = {"hostname": socket.gethostname(), "os_platform": "linux", "app_version": f"maluos-desk {VERSION}", "mcp_surface_version": str(SURFACE),
         "cpu_cores": os.cpu_count()}
    try:
        for line in open("/etc/os-release"):
            k, _, v = line.rstrip("\n").partition("=")
            if k == "PRETTY_NAME":
                f["os_release"] = v.strip().strip('"')
            elif k == "VARIANT":
                f["variant"] = v.strip().strip('"')
    except OSError:
        pass
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                f["memory_mb"] = int(line.split()[1]) // 1024; break
    except OSError:
        pass
    try:
        import shutil
        f["storage_gb"] = shutil.disk_usage("/").total // 2 ** 30
    except OSError:
        pass
    try:
        import hashlib
        f["machine_id"] = hashlib.sha256(open("/etc/machine-id").read().strip().encode()).hexdigest()[:32]
    except OSError:
        pass
    return f


def read_conf():
    try:
        import yaml
        with open(CONF) as fh:
            return yaml.safe_load(fh) or None
    except OSError:
        return None


def write_conf(conf):
    import yaml
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("# MaluOS desk enrolment (maluctl office). No secret here: the desk token is in the owner's vault compartment.\n")
        yaml.safe_dump(conf, fh, sort_keys=False, default_flow_style=False)
    os.chmod(tmp, 0o644); os.replace(tmp, CONF)


def write_env(conf):
    eps = conf.get("endpoints") or {}
    models = eps.get("models") or {}
    pairs = [("MALUOS_OFFICE_URL", conf.get("url")), ("MALUOS_OFFICE_NAME", (conf.get("office") or {}).get("name")),
             ("MALUOS_OFFICE_DESK_ID", (conf.get("desk") or {}).get("id")), ("MALUOS_OFFICE_DESK_NAME", (conf.get("desk") or {}).get("name")),
             ("MALUOS_OFFICE_OWNER", (conf.get("owner") or {}).get("principal")), ("MALUOS_OFFICE_TOKEN_SECRET", conf.get("secret")),
             ("MALUOS_OFFICE_RECORDS_MCP", eps.get("records")), ("MALUOS_OFFICE_ACTIVITY_MCP", eps.get("activity")),
             ("MALUOS_OFFICE_MEMORY_MCP", eps.get("memory")), ("MALUOS_OFFICE_ACTIONS_MCP", eps.get("actions")),
             ("MALUOS_OFFICE_MODELS_URL", models.get("url") if isinstance(models, dict) else None)]
    tmp = ENVF + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("# The office this desk is enrolled with (maluctl office); loaded by every maluos-agent@ unit.\n")
        for k, v in pairs:
            if v not in (None, ""):
                fh.write(f'{k}="{str(v).replace(chr(34), "")}"\n')
    os.chmod(tmp, 0o644); os.replace(tmp, ENVF)


def plugin(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location("maluctl_plugin_" + name, os.path.join(PLUGIN_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def gateway(args):
    """Run a `maluctl gateway` command in-process (root); its failures become RuntimeError."""
    try:
        rc = plugin("gateway").main(list(args))
    except SystemExit as e:
        rc = e.code
    if rc not in (0, None):
        raise RuntimeError(f"maluctl gateway {' '.join(args[:3])}: exit {rc}")


def run_as(user, args, input=None, check=True):
    """`maluctl ARGS` as another user (the vault identifies callers by uid), with the test overrides carried along."""
    env = [f"{k}={v}" for k, v in os.environ.items() if k.startswith(("MALUOS_", "MALUCTL_", "PYTHONPATH", "PATH"))]
    cmd = ["runuser", "-u", user, "--", "env", *env, sys.executable, MALUCTL, *args]
    r = subprocess.run(cmd, input=input, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"maluctl {' '.join(args[:2])} as {user}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def state_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "maluos", "office.json")


def read_state():
    try:
        return json.load(open(state_path()))
    except (OSError, ValueError):
        return None


def write_state(st):
    try:
        os.makedirs(os.path.dirname(state_path()), exist_ok=True)
        tmp = state_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh)
        os.replace(tmp, state_path())
    except OSError:
        pass


def token_for_me():
    """The desk token from the vault, as the calling user (the owner), or from MALUOS_OFFICE_TOKEN."""
    t = os.environ.get("MALUOS_OFFICE_TOKEN")
    if t:
        return t
    from maluos_vault_client import Vault
    return Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value(SECRET, "read", purpose="office heartbeat")["value"]


# -- MaluApps (Phase 12 slice 7): the catalogue and its installs
PUBLIC_CATALOG = os.environ.get("MALUOS_APPS_PUBLIC_URL", "https://download.maluos.com/apps/catalog.json")
PUBLIC_KEYRING = os.environ.get("MALUOS_APPS_KEYRING", "/usr/share/keyrings/maluos-archive-keyring.gpg")
APP_KINDS = ("web", "deb", "script")


def fetch_public_catalog(timeout=10):
    """The public catalogue, verified (slice 9): catalog.json and its detached signature catalog.json.asc, made by
    the release key, checked with gpgv against the archive keyring maluos-keyring ships. (apps, None) when it
    verifies; (None, reason) otherwise: the public half is refused unsigned, the office's is trusted by the desk token."""
    import tempfile
    def fetch(url):
        req = urllib.request.Request(url); req.add_header("User-Agent", f"maluos-desk/{VERSION}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    try:
        data = fetch(PUBLIC_CATALOG)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    try:
        sig = fetch(PUBLIC_CATALOG + ".asc")
    except urllib.error.HTTPError as e:
        return None, f"unsigned (HTTP {e.code} for catalog.json.asc); refused"
    if not os.path.exists(PUBLIC_KEYRING):
        return None, f"no keyring {PUBLIC_KEYRING}; refused"
    with tempfile.TemporaryDirectory(prefix="maluos-apps-") as d:
        dp, sp = os.path.join(d, "catalog.json"), os.path.join(d, "catalog.json.asc")
        with open(dp, "wb") as fh:
            fh.write(data)
        with open(sp, "wb") as fh:
            fh.write(sig)
        try:
            r = subprocess.run(["gpgv", "--keyring", PUBLIC_KEYRING, sp, dp], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"gpgv: {e.__class__.__name__}; refused"
        if r.returncode != 0:
            why = next((l for l in (r.stderr or "").splitlines() if "BAD" in l or "No public key" in l or "not" in l.lower()), "bad signature")
            return None, f"signature invalid ({why.strip()[:80]}); refused"
    try:
        cat = _flat(json.loads(data))
    except ValueError:
        return None, "not JSON; refused"
    if not isinstance(cat.get("apps"), list):
        return None, "no apps list; refused"
    return cat["apps"], None


def apps_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "maluos-apps", "catalog.json")


def launcher_dir():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"), "applications")


def launcher_path(app_id):
    return os.path.join(launcher_dir(), f"maluapp-{app_id}.desktop")


def _norm_app(a, source, office_url=None):
    a = dict(a); a["source"] = source
    a["kind"] = a.get("kind") if a.get("kind") in APP_KINDS else "web"
    if a["kind"] == "web" and not a.get("url") and a.get("path") and office_url:
        a["url"] = office_url.rstrip("/") + "/" + a["path"].lstrip("/")
    req = a.get("requires") or []
    a["available"] = not (a["kind"] == "web" and not a.get("url")) and not ("office" in req and source == "public" and not office_url)
    a["reason"] = None if a["available"] else ("needs an office: enrol this desk (sudo maluctl office enroll)" if "office" in req else "no URL")
    return a


def fetch_apps(refresh=False):
    """The merged catalogue: the office's apps over the public ones; the cache when neither answers."""
    cache = None
    try:
        cache = json.load(open(apps_cache_path()))
    except (OSError, ValueError):
        pass
    if cache and not refresh and time.time() - (cache.get("fetched_at") or 0) < 900:
        return cache
    conf = read_conf() or {}
    office_url = conf.get("url")
    out, errors = {}, []
    try:
        apps_, why = fetch_public_catalog()
        if apps_ is not None:
            for a in apps_:
                if a.get("id"):
                    out[a["id"]] = _norm_app(a, "public", office_url)
        else:
            errors.append(f"public catalogue: {why}")
    except Exception as e:
        errors.append(f"public catalogue: {e.__class__.__name__}")
    ep = (conf.get("endpoints") or {}).get("apps") if conf else None
    if ep:
        try:
            st, r = http("GET", ep, token=token_for_me(), timeout=15)
            if st == 200 and isinstance(r.get("apps"), list):
                for a in r["apps"]:
                    if a.get("id"):
                        out[a["id"]] = _norm_app(a, "office", office_url)
            else:
                errors.append(f"office catalogue: HTTP {st} {r.get('error') or ''}")
        except Exception as e:
            errors.append(f"office catalogue: {e.__class__.__name__}")
    if not out and cache:
        cache["stale"] = True; cache["errors"] = errors
        return cache
    cat = {"fetched_at": int(time.time()), "office": (conf.get("office") or {}).get("name") if conf else None, "office_url": office_url,
           "apps": sorted(out.values(), key=lambda x: x.get("name") or x["id"]), "errors": errors}
    for a in cat["apps"]:
        a["installed"] = app_installed(a)
    try:
        os.makedirs(os.path.dirname(apps_cache_path()), exist_ok=True)
        tmp = apps_cache_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cat, fh)
        os.replace(tmp, apps_cache_path())
    except OSError:
        pass
    return cat


def refresh_launchers():
    try:
        subprocess.run(["update-desktop-database", launcher_dir()], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def app_installed(a):
    if a["kind"] == "web":
        return os.path.exists(launcher_path(a["id"]))
    if a["kind"] == "deb" and a.get("package"):
        return subprocess.run(["dpkg-query", "-W", "-f=${Status}", a["package"]], capture_output=True, text=True).stdout.startswith("install ok")
    return False


def app_install(a):
    if not a.get("available"):
        raise RuntimeError(a.get("reason") or "not available")
    if a["kind"] == "web":
        os.makedirs(launcher_dir(), exist_ok=True)
        text = ("[Desktop Entry]\nType=Application\n" f"Name={a.get('name') or a['id']}\n" f"Comment={(a.get('description') or '').replace(chr(10), ' ')}\n"
                f"Exec=firefox --new-window {a['url']}\n" f"Icon={a.get('icon') or 'maluos-logo'}\nTerminal=false\nCategories=Office;Network;\n"
                f"X-MaluOS-App={a['id']}\nX-MaluOS-Source={a.get('source')}\nStartupNotify=true\n")
        tmp = launcher_path(a["id"]) + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o755); os.replace(tmp, launcher_path(a["id"]))
        refresh_launchers()
        print(f"installed {a.get('name')}: launcher {launcher_path(a['id'])} opens {a['url']} in its own Firefox window")
        return 0
    if a["kind"] == "deb":
        pkg = a.get("package") or sys.exit("the catalogue entry names no package")
        print(f"installing {pkg} from the MaluOS repository (pkexec apt-get)", flush=True)
        return subprocess.call(["pkexec", "apt-get", "install", "-y", pkg], env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    raise RuntimeError("script apps are not supported yet; the Tools Installer handles install scripts")


def app_remove(a):
    if a["kind"] == "web":
        try:
            os.unlink(launcher_path(a["id"])); print(f"removed the launcher for {a.get('name')}")
        except FileNotFoundError:
            print("not installed")
        refresh_launchers(); return 0
    if a["kind"] == "deb":
        return subprocess.call(["pkexec", "apt-get", "remove", "-y", a.get("package") or ""])
    return 1


def app_open(a):
    if a["kind"] == "web" and a.get("url"):
        subprocess.Popen(["firefox", "--new-window", a["url"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True); return 0
    if a["kind"] == "deb" and a.get("exec"):
        subprocess.Popen(["sh", "-c", a["exec"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True); return 0
    sys.exit(f"{a['id']}: nothing to open")


def apps(a):
    sub = a.pop(0) if a and not a[0].startswith("--") else "list"
    cat = fetch_apps(refresh=opt(a, "--refresh", flag=True) or sub != "list")
    for x in cat.get("apps") or []:
        x["installed"] = app_installed(x)
    if sub == "list":
        if opt(a, "--json", flag=True):
            print(json.dumps(cat, indent=None if opt(a, "--compact", flag=True) else 2)); return 0
        if not cat.get("apps"):
            print("no catalogue: " + "; ".join(cat.get("errors") or ["nothing listed"])); return 1
        print(f"MaluApps{' from ' + cat['office'] if cat.get('office') else ''}" + (" (cached, the sources were unreachable)" if cat.get("stale") else "") + ":")
        for x in cat["apps"]:
            print(f"  {x['id']:<16} {x.get('name') or '':<18} {x['kind']:<6} {x['source']:<7} {'installed' if x.get('installed') else ('available' if x.get('available') else x.get('reason') or '-')}")
        return 0
    if not a:
        sys.exit(f"maluctl office apps {sub} ID")
    app = next((x for x in cat.get("apps") or [] if x["id"] == a[0]), None) or sys.exit(f"no app {a[0]!r} in the catalogue")
    if sub == "install":
        rc = app_install(app)
    elif sub == "remove":
        rc = app_remove(app)
    elif sub == "open":
        rc = app_open(app)
    else:
        sys.exit("maluctl office apps [list|install|remove|open]")
    fetch_apps(refresh=True)
    return rc


# -- the office's agents (Phase 12 slice 8): the directory the Agents app lists beside the local agents
def agents_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "maluos-agents", "office.json")


def _norm_agent(a, office_url, office_name):
    a = dict(a)
    a["id"] = str(a.get("id"))
    a.setdefault("name", a["id"]); a.setdefault("description", ""); a.setdefault("icon", "maluos-logo")
    a.setdefault("capabilities", []); a.setdefault("presence", "unknown"); a.setdefault("state", None)
    for k in ("agent", "node", "node_ref", "node_kind", "accept_from", "max_classification", "owner", "principal", "hired"):
        a.setdefault(k, None)
    a["office"] = office_name; a["office_url"] = office_url
    return a


def fetch_agents(refresh=False):
    """The office's agents (endpoints.agents with the desk token), cached per user for 15 minutes; an empty
    list with `error` when there is no office or it does not answer (the cache, marked stale, when there is one)."""
    cache = None
    try:
        cache = json.load(open(agents_cache_path()))
    except (OSError, ValueError):
        pass
    conf = read_conf()
    if not conf:
        try:
            os.remove(agents_cache_path())
        except OSError:
            pass
        return {"fetched_at": int(time.time()), "office": None, "office_url": None, "agents": [], "error": "not enrolled with an office"}
    if cache and not refresh and cache.get("office_url") == conf.get("url") and time.time() - (cache.get("fetched_at") or 0) < 900:
        return cache
    ep = (conf.get("endpoints") or {}).get("agents")
    office_name = (conf.get("office") or {}).get("name")
    if not ep:
        return {"fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"), "agents": [], "error": "the office publishes no agents to desks (no endpoints.agents)"}
    try:
        st, r = http("GET", ep, token=token_for_me(), timeout=15)
        if st != 200 or not isinstance(r.get("agents"), list):
            raise RuntimeError(f"HTTP {st} {r.get('error') or ''}".strip())
    except Exception as e:
        err = f"office agents: {e.__class__.__name__ if not isinstance(e, RuntimeError) else ''} {str(e)[:120]}".strip()
        if cache and cache.get("office_url") == conf.get("url"):
            cache["stale"] = True; cache["error"] = err
            return cache
        return {"fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"), "agents": [], "error": err}
    cat = {"fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"),
           "agents": sorted((_norm_agent(a, conf.get("url"), office_name) for a in r["agents"] if a.get("id") is not None), key=lambda x: x["name"]), "error": None}
    try:
        os.makedirs(os.path.dirname(agents_cache_path()), exist_ok=True)
        tmp = agents_cache_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cat, fh)
        os.replace(tmp, agents_cache_path())
    except OSError:
        pass
    return cat


def agents(a):
    cap = opt(a, "--capability")
    cat = fetch_agents(refresh=opt(a, "--refresh", flag=True) or bool(cap))
    if cap:
        cat = dict(cat, agents=[x for x in cat.get("agents") or [] if cap.lower() in [c.lower() for c in x.get("capabilities") or []]])
    if opt(a, "--json", flag=True):
        print(json.dumps(cat, indent=None if opt(a, "--compact", flag=True) else 2)); return 0
    if cat.get("error") and not cat.get("agents"):
        print(cat["error"]); return 1
    print(f"agents at {cat.get('office') or cat.get('office_url')}" + (" (cached, the office was unreachable)" if cat.get("stale") else "") + ":")
    for x in cat["agents"]:
        print(f"  {x['id']:<16} {x['name']:<22} {(x.get('node') or 'office'):<16} {x.get('presence') or '':<8} {', '.join(x.get('capabilities') or []):<24}"
              + (f" accepts {', '.join(x['accept_from']) if x['accept_from'] else 'its owner only'}" if x.get("node_ref") else ""))
    return 0


def agent(a):
    """maluctl office agent ID card|activity|tasks|send ..."""
    as_json = opt(a, "--json", flag=True)
    if len(a) < 2:
        sys.exit("maluctl office agent ID card|activity|tasks|send TEXT")
    aid, sub = a.pop(0), a.pop(0)
    cat = fetch_agents()
    ag = next((x for x in cat.get("agents") or [] if x["id"] == aid), None)
    if not ag:
        raise RuntimeError(cat.get("error") or f"no agent {aid!r} at the office (maluctl office agents)")
    if sub == "activity":
        if not ag.get("activity"):
            raise RuntimeError("the office publishes no activity for this agent")
        st, r = http("GET", ag["activity"], token=token_for_me(), timeout=15)
        if st != 200:
            raise RuntimeError(f"HTTP {st} {r.get('error') or ''}")
        rows = r.get("activity") or []
        if as_json:
            print(json.dumps(rows, indent=1)); return 0
        for x in rows:
            print(f"{(x.get('ts') or '')[:19]}  {x.get('kind') or '':<10} {x.get('actor') or '':<14} {x.get('summary') or ''}")
        return 0
    if not ag.get("tasks"):
        raise RuntimeError("the office publishes no task interface for this agent")
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_agent_tasks as T
    c = T.Client(ag["tasks"], token=token_for_me())
    try:
        if sub == "card":
            d = c.card()
            if as_json:
                print(json.dumps(d, indent=1)); return 0
            print(f"{d.get('name')}: {d.get('description') or ''}\ncapabilities: {', '.join(d.get('capabilities') or []) or '-'}\nprotocol:     {d.get('protocol')}"); return 0
        if sub == "send":
            cls = opt(a, "--classification", "internal")
            text = " ".join(a).strip() or sys.exit("send TEXT")
            # Phase 13 slice 2: an estate agent (a directory row with a node) needs this desk's envelope; the office's own agents take none
            env = None
            if ag.get("node_ref") or (ag.get("agent") and ag.get("node")):
                conf = read_conf()
                env = my_envelope(conf, {"agent": ag.get("agent") or ag["id"], "node": ag.get("node_ref")}, text[:200], classification=cls)
            if as_json:
                t = c.send(text, envelope=env)
                print(json.dumps(t, indent=1)); return 0 if t.get("state") == "completed" else 1
            shown = [""]
            def on_text(txt):          # the answer as it grows (slice 9); an office that answers at once prints once
                sys.stdout.write(txt[len(shown[0]):] if txt.startswith(shown[0]) else "\n" + txt); sys.stdout.flush(); shown[0] = txt
            t = c.stream(text, on_text=on_text, envelope=env)
            if t.get("state") == "completed":
                if t["output"]["text"] != shown[0]:
                    on_text(t["output"]["text"])
                if not shown[0].endswith("\n"):
                    print()
                p = t.get("provenance") or {}
                if p:
                    print(f"— from {ag.get('agent') or ag['name']} on {p.get('node') or ag.get('node')} · {len(p.get('models') or [])} model call(s) · envelope {p.get('envelope')} · task {t.get('id')}", file=sys.stderr)
                return 0
            print(f"task {t['id']} {t['state']}: {t.get('error') or t.get('reason') or ''}", file=sys.stderr); return 1
        if sub == "tasks":
            rows = c.list()
            if as_json:
                print(json.dumps(rows, indent=1)); return 0
            for t in rows:
                print(f"{t['ts'][:19]}  {t['id']}  {t['state']:9} {t['input']['text'][:50]!r:54} -> {(t.get('output') or {}).get('text', t.get('error') or '')[:60]!r}")
            return 0
    except T.TaskError as e:
        raise RuntimeError(f"agent {aid}: {e.message}")
    sys.exit("maluctl office agent ID card|activity|tasks|send TEXT")


# -- the estate (Phase 13 slice 1): the nodes of the office's estate, when the office publishes them to this desk's owner
def estate_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "maluos-estate", "office.json")


def fetch_estate(refresh=False):
    """GET endpoints.estate with the desk token, cached per user for 60 s: {available, fetched_at, office, office_url,
    nodes, alerts, counts, error}; available is False with the reason when there is no office, no endpoint
    (the owner is not a system manager) or no answer (the cache, marked stale, when there is one)."""
    cache = None
    try:
        cache = json.load(open(estate_cache_path()))
    except (OSError, ValueError):
        pass
    conf = read_conf()
    if not conf:
        try:
            os.remove(estate_cache_path())
        except OSError:
            pass
        return {"available": False, "fetched_at": int(time.time()), "office": None, "office_url": None, "nodes": [], "alerts": [], "counts": {}, "error": "not enrolled with an office"}
    office_name = (conf.get("office") or {}).get("name")
    ep = (conf.get("endpoints") or {}).get("estate")
    if not ep:
        return {"available": False, "fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"), "nodes": [], "alerts": [], "counts": {},
                "error": "the office does not publish the estate to this desk (endpoints.estate: its owner is not a system manager)"}
    if cache and not refresh and cache.get("office_url") == conf.get("url") and cache.get("available") and time.time() - (cache.get("fetched_at") or 0) < 60:
        return cache
    try:
        st, r = http("GET", ep, token=token_for_me(), timeout=15)
        if st != 200 or not isinstance(r.get("nodes"), list):
            raise RuntimeError(f"HTTP {st} {r.get('error') or ''}".strip())
    except Exception as e:
        err = f"office estate: {e.__class__.__name__ if not isinstance(e, RuntimeError) else ''} {str(e)[:120]}".strip()
        if cache and cache.get("office_url") == conf.get("url") and cache.get("available"):
            cache["stale"] = True; cache["error"] = err
            return cache
        return {"available": False, "fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"), "nodes": [], "alerts": [], "counts": {}, "error": err}
    nodes = [n for n in r["nodes"] if isinstance(n, dict)]
    alerts = [a for a in r.get("alerts") or [] if isinstance(a, dict)]
    cat = {"available": True, "fetched_at": int(time.time()), "office": office_name, "office_url": conf.get("url"), "error": None,
           "nodes": sorted(nodes, key=lambda n: (n.get("kind") == "desk", str(n.get("name") or ""))), "alerts": alerts,
           "counts": {"nodes": len(nodes), "online": sum(1 for n in nodes if n.get("presence") == "online"), "offline": sum(1 for n in nodes if n.get("presence") != "online"),
                      "alerts": sum(1 for a in alerts if not a.get("cleared_at"))}}
    try:
        os.makedirs(os.path.dirname(estate_cache_path()), exist_ok=True)
        tmp = estate_cache_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cat, fh)
        os.replace(tmp, estate_cache_path())
    except OSError:
        pass
    return cat


def estate(a):
    if a and a[0] == "action":
        a.pop(0)
        return estate_action(a, read_conf() or sys.exit(f"not enrolled (no {CONF})"))
    cat = fetch_estate(refresh=opt(a, "--refresh", flag=True))
    if opt(a, "--json", flag=True):
        print(json.dumps(cat, indent=None if opt(a, "--compact", flag=True) else 2)); return 0
    if not cat.get("available"):
        print(cat.get("error") or "no estate"); return 1
    c = cat["counts"]
    print(f"estate of {cat.get('office') or cat.get('office_url')}" + (" (cached, the office was unreachable)" if cat.get("stale") else "")
          + f": {c['nodes']} nodes, {c['online']} online, {c['alerts']} open alerts")
    for n in cat["nodes"]:
        print(f"  #{n.get('id'):<4} {n.get('kind') or '':<9} {n.get('name') or '':<20} {n.get('presence') or '':<8} {n.get('health') or '':<8} {n.get('summary') or ''}")
    for x in cat["alerts"]:
        print(f"  alert #{x.get('id')} {x.get('node') or '?'}: {x.get('severity')} {x.get('kind')}: {x.get('title')}" + (f"  (cleared {x['cleared_at']})" if x.get("cleared_at") else ""))
    return 0


# -- Phase 13 slice 2: the desk's envelope, the directory, the inbox, an operator's actions
def key_for_me():
    """The desk's private signing key from the vault, as the owner (or MALUOS_OFFICE_KEY for tests)."""
    k = os.environ.get("MALUOS_OFFICE_KEY")
    if k:
        return k
    from maluos_vault_client import Vault
    return Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value(KEY_SECRET, "read", purpose="office envelope")["value"]


def my_envelope(conf, target, purpose, classification="internal", budget=None, life_s=600):
    """An envelope this desk's owner originates and signs: originator and sender the person, the chain one hop."""
    from maluos_estate import envelope as E
    w = conf.get("owner") or {}
    node = f"desk:{(conf.get('desk') or {}).get('id')}"
    me = {"principal": w.get("principal") or f"user:{w.get('login') or os.environ.get('USER')}", "node": node}
    env = E.make(dict(me, kind="human", member_id=w.get("member_id")), me, target, purpose,
                 {"scopes": [], "classification": classification, "budget": budget or {"usd": 0.5, "calls": 20}}, life_s=life_s)
    return E.sign(env, node, key_for_me())


def key(a):
    """sudo maluctl office key: make this desk's signing key and register it (a desk enrolled before slice 2)."""
    need_root()
    conf = read_conf() or sys.exit(f"not enrolled (no {CONF})")
    owner = (conf.get("owner") or {}).get("login") or sys.exit("the enrolment names no owner login")
    from maluos_estate import envelope as E
    priv, pub = E.genkey(f"desk of user:{owner}")
    ep = (conf.get("endpoints") or {}).get("key") or conf["url"].rstrip("/") + "/api/v1/desks/key"
    env = dict(os.environ); env.pop("MALUOS_OFFICE_TOKEN", None)
    tok = run_as(owner, ["secret", "show", SECRET, "--value"], check=False).strip() if not os.environ.get("MALUOS_OFFICE_TOKEN") else os.environ["MALUOS_OFFICE_TOKEN"]
    st, r = http("POST", ep, {"surface": SURFACE, "public_key": pub}, token=tok)
    if st != 200:
        sys.exit(f"the office refused the key ({st} {r.get('error') or ''}): {r.get('message') or r}")
    run_as(owner, ["secret", "delete", KEY_SECRET], check=False)
    run_as(owner, ["secret", "add", KEY_SECRET, "--kind", "generic", "--provider", "office", "--stdin"], input=priv)
    conf["key"] = {"secret": KEY_SECRET, "public_key": pub, "registered": True}
    write_conf(conf)
    print(f"desk key registered as {r.get('node')}: vault user:{owner}/{KEY_SECRET}"); return 0


def inbox(a):
    """maluctl office inbox [--json] [--all] [--wait S] | decide ID approve|deny [--note T] | reply ID TEXT | read ID"""
    conf = read_conf() or sys.exit(f"not enrolled (no {CONF})")
    ep = (conf.get("endpoints") or {}).get("inbox") or conf["url"].rstrip("/") + "/api/v1/desks/inbox"
    sub = a.pop(0) if a and not a[0].startswith("--") else "list"
    tok = token_for_me()
    if sub in ("decide", "reply", "read"):
        iid = a.pop(0) if a and a[0].isdigit() else sys.exit(f"inbox {sub} ID …")
        if sub == "read":
            st, r = http("POST", ep.rstrip("/") + f"/{iid}/read", {}, token=tok)
        else:
            st0, item = http("GET", ep + "?all=1", token=tok)
            row = next((i for i in (item.get("items") or []) if str(i.get("id")) == iid), None) if st0 == 200 else None
            target = {"agent": (row.get("from") or {}).get("principal", "").partition(":")[2] or None, "node": (row.get("from") or {}).get("node")} if row else {"node": "coordinator"}
            env = my_envelope(conf, {k: v for k, v in target.items() if v}, f"{sub} on inbox item {iid}")
            if sub == "decide":
                decision = a.pop(0) if a and not a[0].startswith("--") else sys.exit("decide ID approve|deny")
                body = {"decision": decision, "note": opt(a, "--note"), "envelope": env}
            else:
                body = {"text": " ".join(a).strip() or sys.exit("reply ID TEXT"), "envelope": env}
            st, r = http("POST", ep.rstrip("/") + f"/{iid}/{sub}", body, token=tok)
        if st != 200:
            raise RuntimeError(f"HTTP {st} {r.get('error') or ''}: {r.get('message') or ''}")
        if opt(a, "--json", flag=True):
            print(json.dumps(r, indent=1)); return 0
        it = r.get("item") or {}
        print(f"inbox #{iid}: {sub} {'' if sub == 'read' else (it.get('decision') or '') if sub == 'decide' else 'sent'}".rstrip() + (f"; task {r['task']['id']} {r['task']['state']}" if r.get("task") else "")); return 0
    q = {"wait": opt(a, "--wait", "0")}
    if opt(a, "--all", flag=True):
        q["all"] = "1"
    if opt(a, "--since"):
        q["since"] = opt(a, "--since")
    import urllib.parse
    st, r = http("GET", ep + "?" + urllib.parse.urlencode(q), token=tok, timeout=int(q["wait"] or 0) + 15)
    if st != 200:
        raise RuntimeError(f"HTTP {st} {r.get('error') or ''}: {r.get('message') or ''}")
    if opt(a, "--json", flag=True):
        print(json.dumps(r, indent=None if opt(a, "--compact", flag=True) else 1)); return 0
    items = r.get("items") or []
    print(f"inbox: {r.get('unread', 0)} unread" + ("" if items else " (nothing to show)"))
    for i in items:
        f = i.get("from") or {}
        print(f"  #{i['id']:<5} {i.get('kind'):<16} {f.get('principal') or ''} on {f.get('node') or ''}: {i.get('subject')}" + (f"  [{', '.join(i['options'])}]" if i.get("options") and i.get("status") != "done" else "")
              + (f"  -> {i.get('decision') or i.get('reply') or ''}" if i.get("status") == "done" else "") + (f"  (task {i['task_id']})" if i.get("task_id") else ""))
    return 0


def estate_action(a, conf):
    """maluctl office estate action NODE ACTION [AGENT] [--wait S]: an operator's action on a node, with this desk's envelope."""
    node = a.pop(0) if a else sys.exit("estate action NODE ACTION [AGENT]")
    action = a.pop(0) if a else sys.exit("estate action NODE ACTION [AGENT]")
    agent = a.pop(0) if a and not a[0].startswith("--") else None
    wait = float(opt(a, "--wait", "30") or 0)
    cat = fetch_estate(refresh=True)
    rows = [n for n in cat.get("nodes") or [] if n.get("kind") != "desk" and (str(n.get("id")) == node or n.get("name") == node)]
    if not rows:
        raise RuntimeError(f"no node {node!r} in the estate ({', '.join(str(n.get('name')) for n in cat.get('nodes') or [] if n.get('kind') != 'desk') or 'none'})")
    n = rows[0]
    ep = (conf.get("endpoints") or {}).get("actions") or sys.exit("the office publishes no actions endpoint to this desk (not an operator)")
    env = my_envelope(conf, {"node": f"{n['kind']}:{n['id']}", "action": action}, f"{action} on {n['name']}")
    st, r = http("POST", conf["url"].rstrip("/") + f"/api/v1/estate/nodes/{n['id']}/actions", {"action": action, "agent": agent, "envelope": env, "wait": wait}, token=token_for_me(), timeout=int(wait) + 20)
    if st not in (200, 201):
        raise RuntimeError(f"HTTP {st} {r.get('error') or ''}: {r.get('message') or ''}")
    x = r.get("action") or {}
    if opt(a, "--json", flag=True):
        print(json.dumps(x, indent=1)); return 0
    res = x.get("result") or {}
    print(f"action {x.get('id')} {action}{' ' + agent if agent else ''} on {n['name']}: {x.get('state')}" + (f" ({x.get('reason')})" if x.get("reason") else "") + (f": {res.get('output')}" if res.get("output") else ""))
    return 0 if x.get("state") == "completed" else 1


# -- commands
def enroll(a):
    need_root()
    if not a or a[0].startswith("-"):
        sys.exit("usage: maluctl office enroll URL --code CODE [--name N] [--owner LOGIN] [--no-gateway] [--no-overlay]")
    url = a.pop(0).rstrip("/")
    if not url.startswith(("http://", "https://")):
        sys.exit(f"the office URL must start with http:// or https:// ({url})")
    code = opt(a, "--code") or sys.exit("--code CODE: the one-time enrolment code the office shows the person")
    name = opt(a, "--name"); owner = opt(a, "--owner") or os.environ.get("SUDO_USER")
    no_gw = opt(a, "--no-gateway", flag=True); force = opt(a, "--force", flag=True); no_overlay = opt(a, "--no-overlay", flag=True)
    if not owner or owner == "root":
        sys.exit("--owner LOGIN: whose desk this is (or run sudo from that account)")
    try:
        pwd.getpwnam(owner)
    except KeyError:
        sys.exit(f"no such user {owner}")
    old = read_conf()
    if old and not force:
        sys.exit(f"this desk is already enrolled with {old.get('url')} as desk #{(old.get('desk') or {}).get('id')}; `sudo maluctl office leave` first, or --force")
    principal = f"user:{owner}"
    who = run_as(owner, ["secret", "whoami"], check=False)
    if f"principal:  {principal}" not in who:
        sys.exit(f"{owner} is not an enrolled principal on this host (sudo maluctl principal add {principal} --kind human)")
    body = {"surface": SURFACE, "code": code, "name": name, "principal": principal, **facts()}
    # Phase 13 slice 2: the desk's signing key (ed25519), made here; the private half goes into the owner's compartment after the enrolment succeeds
    from maluos_estate import envelope as _E
    key_priv, key_pub = _E.genkey(f"desk of {principal}")
    body["public_key"] = key_pub
    # Phase 13 slice 1b: the desk's WireGuard key, made here; the private half goes into the owner's compartment after the enrolment succeeds
    ov_priv = ov_pub = None
    if not no_overlay:
        from maluos_estate import overlay as _OV
        ov_priv, ov_pub = _OV.genkey()
        body["overlay_public_key"] = ov_pub
    try:
        st, r = http("POST", url + "/api/v1/desks/enroll", body)
    except Exception as e:
        sys.exit(f"cannot reach the office at {url}: {str(e)[:160]}")
    if st not in (200, 201):
        sys.exit(f"the office refused enrolment ({st} {r.get('error') or ''}): {r.get('message') or r}")
    token, desk, eps = r.get("token"), r.get("desk") or {}, r.get("endpoints") or {}
    if not token or not desk.get("id"):
        sys.exit("the office answered without a desk token or a desk id")
    # 1. the token, into the owner's own compartment (as them: peer identity, their ledger rows)
    run_as(owner, ["secret", "delete", SECRET], check=False)
    run_as(owner, ["secret", "add", SECRET, "--kind", "token", "--provider", "office", "--env", "MALUOS_OFFICE_TOKEN", "--stdin"], input=token + "\n")
    if ov_priv:
        run_as(owner, ["secret", "delete", OVERLAY_SECRET], check=False)
        run_as(owner, ["secret", "add", OVERLAY_SECRET, "--kind", "generic", "--provider", "estate", "--stdin"], input=ov_priv + "\n")
    run_as(owner, ["secret", "delete", KEY_SECRET], check=False)
    run_as(owner, ["secret", "add", KEY_SECRET, "--kind", "generic", "--provider", "office", "--stdin"], input=key_priv)
    # Phase 13 slice 3: the inference key, in the owner's compartment too; the gateway may use it (its estate rungs, the kernel's placement)
    inf = None
    if r.get("inference_key"):
        store_inference_key(owner, r["inference_key"])
        inf = {"secret": INFERENCE_SECRET}
    conf = {"surface": r.get("surface", SURFACE), "url": url, "office": r.get("office") or {"name": None, "url": url}, "desk": desk,
            "owner": {**(r.get("owner") or {}), "login": owner, "principal": principal}, "endpoints": eps,
            "heartbeat_s": int(r.get("heartbeat_s") or 300), "secret": SECRET, "key": {"secret": KEY_SECRET, "public_key": key_pub, "registered": True}, "gateway": None, "enrolled_at": utc(), "maluos_desk": VERSION,
            "overlay": (r.get("overlay") or {"role": "spoke", "address": None, "hub": None}) if ov_priv else None, "overlay_secret": OVERLAY_SECRET if ov_priv else None,
            "inference": inf, "editions": list(r.get("editions") or [])}
    # 2. the office's models as a rung of this desk's gateway, keyed by the token the gateway applies for the caller
    models = eps.get("models") if isinstance(eps.get("models"), dict) else None
    gw_note = "the office publishes no model endpoint to desks"
    if models and models.get("url") and not no_gw:
        mlist = [m for m in (models.get("models") or []) if m]
        try:
            # The rung names the owner's token explicitly (slice 9): a principal without a grant is refused by the
            # vault and asks the owner (a grant request with the call as its cause), instead of "no such secret".
            gateway(["backend", "add", "office", "--kind", "openai_compat", "--endpoint", models["url"].rstrip("/"), "--secret", f"{principal}/{SECRET}"]
                    + (["--models", ",".join(mlist)] if mlist else []))
            gateway(["tier", "add", "office", "--description", "the office's models, through the desk token"])
            if mlist:
                gateway(["alias", "set", "office", "--tier", "office", "--backend", "office", "--model", mlist[0]])
            conf["gateway"] = {"backend": "office", "tier": "office", "alias": "office" if mlist else None, "models": mlist}
            gw_note = f"maluctl gateway chat ... --model office  ({', '.join(mlist) or 'models as the office lists them'})"
        except Exception as e:
            gw_note = f"gateway rung not made: {str(e)[:160]} (maluctl gateway backend add office --kind openai_compat --endpoint {models['url']} --secret {principal}/{SECRET})"
    elif no_gw:
        gw_note = "no gateway rung (--no-gateway)"
    write_conf(conf); write_env(conf)
    if ov_priv:
        overlay_unit("enable"); overlay_unit("restart")
    print(f"enrolled: desk '{desk.get('name')}' (#{desk.get('id')}) at {conf['office'].get('name') or url} for {principal}")
    print(f"  token:    vault {principal}/{SECRET} (the session heartbeats with it; maluctl office status); key {principal}/{KEY_SECRET} signs this desk's envelopes")
    print(f"  models:   {gw_note}")
    print(f"  agents:   {ENVF} names the office's endpoints; maluctl secret delegate --to agent:NAME --secret {SECRET}")
    o = conf.get("overlay")
    print("  overlay:  " + ("off (--no-overlay)" if o is None else (f"{o['address']} as {o.get('name')} via the hub at {(o.get('hub') or {}).get('endpoint')} (maluos-overlay.service; maluctl estate overlay status)" if o.get("address") else "a key was sent; no hub has joined the estate yet")))
    print("  inference: " + (f"key {principal}/{INFERENCE_SECRET} (the gateway may use it); the estate's shared GPUs become rungs of this gateway (maluctl gateway estate)"
                             + (f"; editions {', '.join(conf['editions'])}" if conf.get("editions") else "") if inf else "the office issued no inference key (an office before slice 3)"))
    return 0


def store_inference_key(owner, key):
    """The inference key into the owner's compartment (as them), with a `use` grant to the gateway's own user."""
    run_as(owner, ["secret", "delete", INFERENCE_SECRET], check=False)
    run_as(owner, ["secret", "add", INFERENCE_SECRET, "--kind", "token", "--provider", "estate", "--stdin"], input=key + "\n")
    try:
        run_as(owner, ["secret", "grant", INFERENCE_SECRET, "--to", f"user:{GATEWAY_USER}", "--level", "use"])
    except RuntimeError as e:
        print(f"  warn: the gateway's grant on {INFERENCE_SECRET}: {e}", file=sys.stderr)


def inference_refresh(conf, tok, which=("backends", "peers")):
    """Re-read the directory's backends and/or the peers with the desk token and write the gateway's caches (as the owner)."""
    from maluos_estate import client as _C
    out = {}
    principal = (conf.get("owner") or {}).get("principal")
    secret_ref = f"{principal}/{INFERENCE_SECRET}" if principal else INFERENCE_SECRET
    eps = conf.get("endpoints") or {}
    if "backends" in which:
        st, r = _C.inference(eps.get("inference") or conf["url"].rstrip("/") + "/api/v1/desks/inference", tok)
        if st == 200:
            _C.write_cache(INFERENCE_CACHE, r, secret_ref, principal, "desk")
        out["backends"] = (st, r)
    if "peers" in which:
        st, r = _C.inference_peers(eps.get("inference_peers") or conf["url"].rstrip("/") + "/api/v1/estate/inference/peers", tok)
        if st == 200:
            _C.write_cache(PEERS_CACHE, r, secret_ref, principal, "desk")
        out["peers"] = (st, r)
    return out


def inference(a):
    """maluctl office inference: the backends published to this desk, the peers, this desk's own facts; --refresh, --all, --new-key."""
    from maluos_estate import client as _C
    as_json = opt(a, "--json", flag=True); refresh = opt(a, "--refresh", flag=True); everything = opt(a, "--all", flag=True); new_key = opt(a, "--new-key", flag=True)
    conf = read_conf() or sys.exit(f"not enrolled (no {CONF})")
    eps = conf.get("endpoints") or {}
    if new_key:
        need_root()
        owner = (conf.get("owner") or {}).get("login") or sys.exit("the enrolment names no owner login")
        tok = run_as(owner, ["secret", "show", SECRET, "--value"], check=False).strip() if not os.environ.get("MALUOS_OFFICE_TOKEN") else os.environ["MALUOS_OFFICE_TOKEN"]
        st, r = _C.inference_key_new(eps.get("inference") or conf["url"].rstrip("/") + "/api/v1/desks/inference", tok)
        if st != 200 or not r.get("inference_key"):
            sys.exit(f"the office answered {st} {r.get('error') or ''}: {r.get('message') or ''}")
        store_inference_key(owner, r["inference_key"])
        conf["inference"] = {"secret": INFERENCE_SECRET}; write_conf(conf)
        print(f"a new inference key is in the vault as {(conf.get('owner') or {}).get('principal')}/{INFERENCE_SECRET}; the old one stops working at once")
        out = run_as(owner, ["office", "inference", "--refresh"], check=False)
        print(out.rstrip())
        return 0
    if everything:
        st, r = _C.inference((eps.get("inference") or conf["url"].rstrip("/") + "/api/v1/desks/inference") + "?all=1", token_for_me())
        if st != 200:
            sys.exit(f"the office answered {st} {r.get('error') or ''}: {r.get('message') or ''}")
        if as_json:
            print(json.dumps(r, indent=1)); return 0
        print(f"every backend of the estate ({len(r.get('backends') or [])}; version {r.get('version')})" + (f"; editions {', '.join(r['editions'])}" if r.get("editions") else ""))
        for b in r.get("backends") or []:
            w = b.get("expected_wait_s") or {}; q = b.get("queue") or {}
            print(f"  {b.get('name'):<20} {b.get('node'):<14} {b.get('address')}:{b.get('port')}  queue {q.get('queued', 0)}/{q.get('running', 0)}  "
                  + " ".join(f"{c} {v}s" for c, v in w.items()) + f"  {', '.join(m.get('name') for m in b.get('models') or []) or '-'}" + ("" if b.get("allowed", True) else "  (not for this desk)"))
        return 0
    if refresh:
        out = inference_refresh(conf, token_for_me())
        for name, (st, r) in out.items():
            if st != 200:
                sys.exit(f"{name}: the office answered {st} {r.get('error') or ''}: {r.get('message') or ''}")
        try:
            gateway(["reload"])
        except Exception:
            pass                # not an operator of the gateway: it re-reads the cache within its reload interval
    facts = _C.gateway_inference()
    backends = _C.read_cache(INFERENCE_CACHE) or {}
    peers = _C.read_cache(PEERS_CACHE) or {}
    if as_json:
        print(json.dumps({"facts": facts, "backends": backends, "peers": peers}, indent=1, default=str)); return 0
    if facts is None:
        print("facts:     no gateway on this desk (nothing to share)")
    else:
        print(f"facts:     share {'on' if facts.get('share') else 'off'} ({facts.get('contribution')}" + (f", idle since {facts['idle'].get('since')}" if (facts.get('idle') or {}).get('idle') else "") + f"), port {facts.get('port')}, "
              + f"{len(facts.get('models') or [])} model(s); queue {facts.get('queue')}")
    if not backends:
        print(f"backends:  no cache yet ({INFERENCE_CACHE}): the session writes it after a heartbeat; --refresh does it now")
    else:
        bs = backends.get("backends") or []
        print(f"backends:  {len(bs)} published to this desk (version {backends.get('version')}, fetched {backends.get('fetched_at')})"
              + (f"; editions {', '.join(backends['editions'])}" if backends.get("editions") else "") + ("; placement by the kernel" if backends.get("place") else ""))
        for b in bs:
            w = b.get("expected_wait_s") or {}
            print(f"  {b.get('name'):<20} {b.get('node'):<14} {b.get('address')}:{b.get('port')}  {', '.join(m.get('name') for m in b.get('models') or []) or '-'}"
                  + (f"  wait " + " ".join(f"{c} {v}s" for c, v in w.items()) if w else "") + f"  ceiling {b.get('classification_max')}"
                  + (f" class<={b['class_max']}" if b.get("class_max") else "") + (f" priority {b['priority']}" if b.get("priority") else ""))
    if peers:
        print(f"peers:     {len(peers.get('peers') or [])} member(s) may call this desk's gateway (version {peers.get('version')})")
    return 0


OVERLAY_SECRET = "estate-overlay-key"       # the desk's WireGuard private key, in the owner's compartment (Phase 13 slice 1b)
OVERLAY_UNIT = "maluos-overlay.service"


def overlay_unit(action):
    if os.environ.get("MALUOS_ESTATE_NO_UNIT") == "1" or not os.path.exists("/run/systemd/system"):
        return
    r = subprocess.run(["systemctl", action, "--quiet", OVERLAY_UNIT], capture_output=True, text=True)
    if r.returncode != 0 and action not in ("stop", "disable"):
        print(f"  warn: systemctl {action} {OVERLAY_UNIT}: {(r.stderr or r.stdout).strip()[-160:]}", file=sys.stderr)


def status(a):
    as_json = opt(a, "--json", flag=True); live = opt(a, "--live", flag=True)
    conf = read_conf()
    out = {"enrolled": bool(conf), "conf": CONF}
    if conf:
        out.update({k: conf.get(k) for k in ("surface", "url", "office", "desk", "owner", "endpoints", "heartbeat_s", "secret", "gateway", "enrolled_at")})
        out["last_heartbeat"] = read_state()
        if live:
            try:
                st, r = http("GET", (conf.get("endpoints") or {}).get("me") or conf["url"] + "/api/v1/desks/me", token=token_for_me())
                out["live"] = {"status": st, **({k: r.get(k) for k in ("desk", "office", "owner")} if st == 200 else {"error": r.get("error"), "message": r.get("message")})}
            except Exception as e:
                out["live"] = {"status": 0, "error": e.__class__.__name__, "message": str(e)[:160]}
    if as_json:
        print(json.dumps(out, indent=2, default=str)); return 0
    if not conf:
        print(f"not enrolled: sudo maluctl office enroll URL --code CODE  (no {CONF})"); return 1
    d, o, w = conf.get("desk") or {}, conf.get("office") or {}, conf.get("owner") or {}
    print(f"office:     {o.get('name') or '?'}  {conf.get('url')}  (surface {conf.get('surface')})")
    print(f"desk:       {d.get('name')}  (#{d.get('id')})  enrolled {conf.get('enrolled_at')}")
    print(f"owner:      {w.get('principal')}  {w.get('display_name') or ''} <{w.get('email') or '?'}>  member #{w.get('member_id')}")
    print(f"token:      vault {w.get('principal')}/{conf.get('secret')}" + (f"; key {KEY_SECRET} ({(conf.get('key') or {}).get('public_key', '')[:30]}…)" if conf.get("key") else "; no desk key yet (sudo maluctl office key)"))
    eps = conf.get("endpoints") or {}
    pub = [k for k in ("records", "activity", "memory", "actions") if eps.get(k)]
    models = eps.get("models") if isinstance(eps.get("models"), dict) else None
    print(f"endpoints:  {', '.join(pub) or 'none'}" + (f"; models at {models['url']} ({', '.join(models.get('models') or []) or 'unlisted'})" if models else "; no models for desks"))
    g = conf.get("gateway")
    print(f"gateway:    backend {g['backend']}, tier {g['tier']}" + (f", --model {g['alias']}" if g.get("alias") else "") if g else "gateway:    no rung")
    hb = out.get("last_heartbeat")
    if hb:
        print(f"heartbeat:  {hb.get('ts')}  {'ok' if hb.get('ok') else 'FAILED'}  presence {hb.get('presence')}" + (f"  ({hb.get('error')})" if hb.get("error") else "") + ("  RETIRED by the office" if hb.get("revoked") else ""))
    else:
        print(f"heartbeat:  none yet from this account (the session sends them every {conf.get('heartbeat_s')} s)")
    if "live" in out:
        lv = out["live"]
        print(f"office says: {lv['status']}  " + (f"desk {lv['desk'].get('name')} {lv['desk'].get('status')} presence {lv['desk'].get('presence')} seen {lv['desk'].get('last_seen_at')}" if lv.get("desk") else f"{lv.get('error')}: {lv.get('message')}"))
    return 0


def heartbeat(a):
    as_json = opt(a, "--json", flag=True); presence = opt(a, "--presence", "online")
    conf = read_conf()
    res = {"ts": utc(), "ok": False, "presence": presence, "revoked": False, "error": None, "desk": None}
    if not conf:
        res["error"] = "not enrolled"
    else:
        try:
            tok = token_for_me()
            url = (conf.get("endpoints") or {}).get("heartbeat") or conf["url"] + "/api/v1/desks/heartbeat"
            f = facts()
            from maluos_estate import client as _C
            body = {"surface": SURFACE, "presence": presence, "app_version": f["app_version"], "mcp_surface_version": f["mcp_surface_version"],
                    "facts": {k: f[k] for k in ("hostname", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb") if k in f}}
            inf = _C.gateway_inference() if presence == "online" else None      # Phase 13 slice 3: this desk's gateway facts (a laptop that shares while idle)
            if inf is not None:
                body["inference"] = inf
            st, r = http("POST", url, body, token=tok)
            if st == 200:
                res.update(ok=True, desk=r.get("desk"), heartbeat_s=r.get("heartbeat_s"), office=r.get("office"), overlay_changed=bool(r.get("overlay_changed")),
                           inference_changed=bool(r.get("inference_changed")), peers_changed=bool(r.get("peers_changed")), editions=r.get("editions"))
                if r.get("overlay_changed"):
                    from maluos_estate import overlay as _OV
                    _OV.hint()                   # slice 1b: the overlay service refreshes now
                # slice 3: the gateway's caches: the backends hourly or on inference_changed, the peers every 5 min or on peers_changed
                if (conf.get("endpoints") or {}).get("inference") and presence == "online":
                    which = []
                    bc = _C.read_cache(INFERENCE_CACHE); pc = _C.read_cache(PEERS_CACHE)
                    if r.get("inference_changed") or not bc or bc.get("principal") != (conf.get("owner") or {}).get("principal") or time.time() - _cache_age(INFERENCE_CACHE) > _C.INFERENCE_REFRESH_S:
                        which.append("backends")
                    if r.get("peers_changed") or not pc or time.time() - _cache_age(PEERS_CACHE) > _C.PEERS_REFRESH_S:
                        which.append("peers")
                    if which:
                        try:
                            out = inference_refresh(conf, tok, which)
                            res["inference"] = {k: v[0] for k, v in out.items()}
                        except Exception as e:
                            res["inference"] = {"error": f"{e.__class__.__name__}: {str(e)[:120]}"}
            elif st in (401, 410):
                res.update(revoked=True, error=f"{st} {r.get('error') or ''}: {r.get('message') or 'the office no longer knows this desk'}")
            else:
                res["error"] = f"{st} {r.get('error') or ''}: {r.get('message') or r}"
        except Exception as e:
            res["error"] = f"{e.__class__.__name__}: {str(e)[:160]}"
    write_state(res)
    if as_json:
        print(json.dumps(res, default=str))
    elif res["ok"]:
        d = res["desk"] or {}
        print(f"ok: desk {d.get('name')} (#{d.get('id')}) {res['presence']} at {res['ts']}")
    else:
        print(f"heartbeat failed: {res['error']}" + ("  (retired: sudo maluctl office leave)" if res["revoked"] else ""), file=sys.stderr)
    return 0 if res["ok"] else 1


def _cache_age(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def leave(a):
    need_root()
    keep = opt(a, "--keep-secret", flag=True)
    conf = read_conf()
    if not conf:
        sys.exit(f"not enrolled (no {CONF})")
    owner = (conf.get("owner") or {}).get("login")
    told = "not told (no token)"
    tok = None
    if owner:
        try:
            tok = run_as(owner, ["secret", "show", SECRET]).strip() or None
        except Exception:
            tok = None
    if tok:
        try:
            st, r = http("POST", (conf.get("endpoints") or {}).get("leave") or conf["url"] + "/api/v1/desks/leave", {"surface": SURFACE}, token=tok)
            told = "told; desk retired" if st == 200 else f"answered {st} {r.get('error') or ''}: {r.get('message') or ''}".strip()
        except Exception as e:
            told = f"unreachable ({str(e)[:100]}); retire the desk from the office's Work Locations"
    if conf.get("overlay_secret"):
        from maluos_estate import overlay as _OV
        overlay_unit("disable"); overlay_unit("stop")
        try:
            _OV.down()
        except Exception as e:
            print(f"  warn: overlay down: {e}", file=sys.stderr)
        if owner and not keep:
            try:
                run_as(owner, ["secret", "delete", conf["overlay_secret"]])
            except Exception as e:
                print(f"  warn: {e}", file=sys.stderr)
    g = conf.get("gateway") or {}
    if g.get("backend"):
        for args in (["alias", "rm", g.get("alias") or "office"], ["tier", "rm", g.get("tier") or "office"], ["backend", "rm", g["backend"]]):
            try:
                gateway(args)
            except Exception as e:
                print(f"  warn: {e}", file=sys.stderr)
    if owner and not keep:
        try:
            run_as(owner, ["secret", "delete", SECRET])
            run_as(owner, ["secret", "delete", KEY_SECRET], check=False)       # slice 2: the desk key goes with the token
            run_as(owner, ["secret", "delete", INFERENCE_SECRET], check=False)   # slice 3: and the inference key
        except Exception as e:
            print(f"  warn: {e}", file=sys.stderr)
    for p in (INFERENCE_CACHE, PEERS_CACHE):      # slice 3: the gateway's estate rungs and peers go with the enrolment
        try:
            os.remove(p)
        except OSError:
            pass
    for p in (CONF, ENVF):
        try:
            os.remove(p)
        except OSError:
            pass
    print(f"left {(conf.get('office') or {}).get('name') or conf.get('url')}: the office was {told}; " + ("the gateway rung and " if g else "") + ("the token " if not keep else "") + "removed"
          + ("; the overlay tunnel down" if conf.get("overlay_secret") else ""))
    return 0


def main(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    try:
        if cmd == "enroll":
            return enroll(a)
        if cmd == "status":
            return status(a)
        if cmd == "heartbeat":
            return heartbeat(a)
        if cmd == "leave":
            return leave(a)
        if cmd == "apps":
            return apps(a)
        if cmd == "agents":
            return agents(a)
        if cmd == "agent":
            return agent(a)
        if cmd == "estate":
            return estate(a)
        if cmd == "inbox":
            return inbox(a)
        if cmd == "inference":
            return inference(a)
        if cmd == "key":
            return key(a)
    except RuntimeError as e:
        sys.exit(f"maluctl office {cmd}: {e}")
    print(__doc__); return 2
