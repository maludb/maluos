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
                                                   public one (download.maluos.com/apps/catalog.json), cached per user
  maluctl office apps install|remove|open ID       a web app becomes a launcher opening it in Firefox's own window;
                                                   a deb app installs from apt.maluos.com (pkexec apt-get)
  maluctl office agents [--json] [--refresh]       the office's agents this desk may use (endpoints.agents; Phase 12 slice 8)
  maluctl office agent ID card|activity|tasks [--json]       one of them: its card, its recent activity, the tasks sent from here
  maluctl office agent ID send TEXT [--json]       give it a task and wait for the answer (its task URL, the desk token)
  sudo maluctl office leave [--keep-secret]

Agents: /etc/maluos/office.env names the office's endpoints (MALUOS_OFFICE_*)
for every maluos-agent@ unit. The owner lets an agent use the office's
models with `maluctl secret delegate --to agent:NAME --secret office-desk-token`
and read the token for the office's MCP servers with
`maluctl secret grant office-desk-token --to agent:NAME --level read`.
"""
import json, os, pwd, socket, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, "/usr/lib/maluos")

VERSION = "0.3.0"
SURFACE = 1
CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
ENVF = os.environ.get("MALUOS_OFFICE_ENV", "/etc/maluos/office.env")
SECRET = "office-desk-token"
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
    """(status, json) for an office call; raises OSError/URLError when the office is unreachable."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json"); req.add_header("User-Agent", f"maluos-desk/{VERSION}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, _flat(json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, _flat(json.loads(raw))
        except Exception:
            return e.code, {"error": "http_error", "message": raw.decode(errors="replace")[:200]}


def _flat(obj):
    """The kernel answers errors as {"error": {"code", "message"}}; the mock and this code use the flat form."""
    if isinstance(obj, dict) and isinstance(obj.get("error"), dict):
        e = obj["error"]
        obj = {**obj, "error": e.get("code") or "error", "message": e.get("message") or ""}
    return obj if isinstance(obj, dict) else {}


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
APP_KINDS = ("web", "deb", "script")


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
        st, r = http("GET", PUBLIC_CATALOG, timeout=10)
        if st == 200 and isinstance(r.get("apps"), list):
            for a in r["apps"]:
                if a.get("id"):
                    out[a["id"]] = _norm_app(a, "public", office_url)
        else:
            errors.append(f"public catalogue: HTTP {st}")
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
    cat = fetch_agents(refresh=opt(a, "--refresh", flag=True))
    if opt(a, "--json", flag=True):
        print(json.dumps(cat, indent=None if opt(a, "--compact", flag=True) else 2)); return 0
    if cat.get("error") and not cat.get("agents"):
        print(cat["error"]); return 1
    print(f"agents at {cat.get('office') or cat.get('office_url')}" + (" (cached, the office was unreachable)" if cat.get("stale") else "") + ":")
    for x in cat["agents"]:
        print(f"  {x['id']:<16} {x['name']:<22} {x.get('presence') or '':<8} {x.get('state') or '':<8} {', '.join(x.get('capabilities') or [])}")
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
            text = " ".join(a).strip() or sys.exit("send TEXT")
            t = c.send(text)
            if as_json:
                print(json.dumps(t, indent=1)); return 0 if t.get("state") == "completed" else 1
            if t.get("state") == "completed":
                print(t["output"]["text"]); return 0
            print(f"task {t['id']} {t['state']}: {t.get('error') or ''}", file=sys.stderr); return 1
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


# -- commands
def enroll(a):
    need_root()
    if not a or a[0].startswith("-"):
        sys.exit("usage: maluctl office enroll URL --code CODE [--name N] [--owner LOGIN] [--no-gateway]")
    url = a.pop(0).rstrip("/")
    if not url.startswith(("http://", "https://")):
        sys.exit(f"the office URL must start with http:// or https:// ({url})")
    code = opt(a, "--code") or sys.exit("--code CODE: the one-time enrolment code the office shows the person")
    name = opt(a, "--name"); owner = opt(a, "--owner") or os.environ.get("SUDO_USER")
    no_gw = opt(a, "--no-gateway", flag=True); force = opt(a, "--force", flag=True)
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
    conf = {"surface": r.get("surface", SURFACE), "url": url, "office": r.get("office") or {"name": None, "url": url}, "desk": desk,
            "owner": {**(r.get("owner") or {}), "login": owner, "principal": principal}, "endpoints": eps,
            "heartbeat_s": int(r.get("heartbeat_s") or 300), "secret": SECRET, "gateway": None, "enrolled_at": utc(), "maluos_desk": VERSION}
    # 2. the office's models as a rung of this desk's gateway, keyed by the token the gateway applies for the caller
    models = eps.get("models") if isinstance(eps.get("models"), dict) else None
    gw_note = "the office publishes no model endpoint to desks"
    if models and models.get("url") and not no_gw:
        mlist = [m for m in (models.get("models") or []) if m]
        try:
            gateway(["backend", "add", "office", "--kind", "openai_compat", "--endpoint", models["url"].rstrip("/"), "--secret", SECRET]
                    + (["--models", ",".join(mlist)] if mlist else []))
            gateway(["tier", "add", "office", "--description", "the office's models, through the desk token"])
            if mlist:
                gateway(["alias", "set", "office", "--tier", "office", "--backend", "office", "--model", mlist[0]])
            conf["gateway"] = {"backend": "office", "tier": "office", "alias": "office" if mlist else None, "models": mlist}
            gw_note = f"maluctl gateway chat ... --model office  ({', '.join(mlist) or 'models as the office lists them'})"
        except Exception as e:
            gw_note = f"gateway rung not made: {str(e)[:160]} (maluctl gateway backend add office --kind openai_compat --endpoint {models['url']} --secret {SECRET})"
    elif no_gw:
        gw_note = "no gateway rung (--no-gateway)"
    write_conf(conf); write_env(conf)
    print(f"enrolled: desk '{desk.get('name')}' (#{desk.get('id')}) at {conf['office'].get('name') or url} for {principal}")
    print(f"  token:    vault {principal}/{SECRET} (the session heartbeats with it; maluctl office status)")
    print(f"  models:   {gw_note}")
    print(f"  agents:   {ENVF} names the office's endpoints; maluctl secret delegate --to agent:NAME --secret {SECRET}")
    return 0


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
    print(f"token:      vault {w.get('principal')}/{conf.get('secret')}")
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
            st, r = http("POST", url, {"surface": SURFACE, "presence": presence, "app_version": f["app_version"], "mcp_surface_version": f["mcp_surface_version"],
                                       "facts": {k: f[k] for k in ("hostname", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb") if k in f}}, token=tok)
            if st == 200:
                res.update(ok=True, desk=r.get("desk"), heartbeat_s=r.get("heartbeat_s"), office=r.get("office"))
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
        except Exception as e:
            print(f"  warn: {e}", file=sys.stderr)
    for p in (CONF, ENVF):
        try:
            os.remove(p)
        except OSError:
            pass
    print(f"left {(conf.get('office') or {}).get('name') or conf.get('url')}: the office was {told}; " + ("the gateway rung and " if g else "") + ("the token " if not keep else "") + "removed")
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
    except RuntimeError as e:
        sys.exit(f"maluctl office {cmd}: {e}")
    print(__doc__); return 2
