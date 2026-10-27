"""The estate client: the HTTP shape every MaluOS node and desk speaks to its office (surface 1), the files of
this node's enrolment, and the estate endpoints (docs/phase13-slice1-nodes.md, "The contract").

Files (no secret in any of them):
  /etc/maluos/estate.yaml           the enrolment: url, office, node, endpoints, heartbeat_s, report_s, principal, joined_at
  /var/lib/maluos/estate/state.json the last heartbeat's outcome, written by the daemon (maluctl estate status reads it)
The node token (estate-node-token) and the node key (estate-node-key) are in the vault, in the host principal's
compartment (host:<hostname>), stored as the system user maluos-estate at `join`.

Test overrides: MALUOS_ESTATE_CONF, MALUOS_ESTATE_STATE_DIR, MALUOS_ESTATE_USER, MALUOS_ESTATE_TOKEN,
MALUOS_OFFICE_CONF, MALUOS_PROVISIONED, MALUOS_VAULT_SOCKET.
"""
import hashlib, json, os, shutil, socket, time, urllib.error, urllib.request

from . import VERSION

SURFACE = 1
CONF = os.environ.get("MALUOS_ESTATE_CONF", "/etc/maluos/estate.yaml")
STATE_DIR = os.environ.get("MALUOS_ESTATE_STATE_DIR", "/var/lib/maluos/estate")
STATE = os.path.join(STATE_DIR, "state.json")
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
PROVISIONED = os.environ.get("MALUOS_PROVISIONED", "/var/lib/maluos/firstboot/done")
USER = os.environ.get("MALUOS_ESTATE_USER", "maluos-estate")
SECRET_TOKEN, SECRET_KEY = "estate-node-token", "estate-node-key"
KINDS = ("server", "inference")


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def http(method, url, body=None, token=None, timeout=20, agent=None):
    """(status, json) for an office call; raises OSError/URLError when the office is unreachable."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json"); req.add_header("User-Agent", agent or f"maluos-estate/{VERSION}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, flat(json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, flat(json.loads(raw))
        except Exception:
            return e.code, {"error": "http_error", "message": raw.decode(errors="replace")[:200]}


def flat(obj):
    """The kernel answers errors as {"error": {"code", "message"}}; the mock and this code use the flat form."""
    if isinstance(obj, dict) and isinstance(obj.get("error"), dict):
        e = obj["error"]
        obj = {**obj, "error": e.get("code") or "error", "message": e.get("message") or ""}
    return obj if isinstance(obj, dict) else {}


def os_release():
    d = {}
    try:
        for line in open("/etc/os-release"):
            k, _, v = line.rstrip("\n").partition("=")
            if k:
                d[k] = v.strip().strip('"')
    except OSError:
        pass
    return d


def facts(app=None):
    """The machine facts every enrolment and heartbeat carries (desks and nodes alike)."""
    osr = os_release()
    f = {"hostname": socket.gethostname(), "os_platform": "linux", "app_version": app or f"maluos-estate {VERSION}",
         "mcp_surface_version": str(SURFACE), "cpu_cores": os.cpu_count()}
    if osr.get("PRETTY_NAME"):
        f["os_release"] = osr["PRETTY_NAME"]
    if osr.get("VARIANT"):
        f["variant"] = osr["VARIANT"]
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                f["memory_mb"] = int(line.split()[1]) // 1024; break
    except OSError:
        pass
    try:
        f["storage_gb"] = shutil.disk_usage("/").total // 2 ** 30
    except OSError:
        pass
    try:
        f["machine_id"] = hashlib.sha256(open("/etc/machine-id").read().strip().encode()).hexdigest()[:32]
    except OSError:
        pass
    return f


def components():
    """What the host's provisioning record says it runs (the component names of /var/lib/maluos/firstboot/done)."""
    try:
        with open(PROVISIONED) as fh:
            p = json.load(fh)
        c = p.get("components") or {}
        return sorted(c) if isinstance(c, dict) else list(c)
    except (OSError, ValueError):
        return []


# -- files
def read_conf(path=None):
    try:
        import yaml
        with open(path or CONF) as fh:
            return yaml.safe_load(fh) or None
    except (OSError, ImportError, ValueError):
        return None


def write_conf(conf):
    import yaml
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("# MaluOS estate membership (maluctl estate). No secret here: the node token and key are in the vault,\n"
                 "# in the host principal's compartment, stored as the system user maluos-estate.\n")
        yaml.safe_dump(conf, fh, sort_keys=False, default_flow_style=False)
    os.chmod(tmp, 0o644); os.replace(tmp, CONF)


def desk_conf():
    """/etc/maluos/office.yaml when this host is an enrolled desk (its node record is its desk row), else None."""
    return read_conf(OFFICE_CONF)


def read_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_state(st):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh, default=str)
        os.chmod(tmp, 0o644); os.replace(tmp, STATE)
    except OSError:
        pass


# -- the token
def token(conf):
    """The node token: MALUOS_ESTATE_TOKEN, or the vault entry in the host principal's compartment (readable by that
    principal, by root and by the estate's operators)."""
    t = os.environ.get("MALUOS_ESTATE_TOKEN")
    if t:
        return t
    import sys
    sys.path.insert(0, "/usr/lib/maluos")
    from maluos_vault_client import Vault
    ref = f"{conf.get('principal')}/{SECRET_TOKEN}" if conf.get("principal") else SECRET_TOKEN
    return Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value(ref, "read", purpose="estate heartbeat")["value"]


# -- the endpoints
def endpoint(conf, name):
    return (conf.get("endpoints") or {}).get(name) or conf["url"].rstrip("/") + f"/api/v1/estate/{name}"


def heartbeat(conf, tok, presence="online", report=None, timeout=20):
    """One heartbeat: presence, facts and (when given) the report. The outcome in the shape state.json keeps."""
    res = {"ts": utc(), "ok": False, "presence": presence, "revoked": False, "error": None, "node": None, "report_sent": report is not None}
    try:
        f = facts()
        body = {"surface": SURFACE, "presence": presence, "app_version": f["app_version"],
                "facts": {k: f[k] for k in ("hostname", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb") if k in f}}
        if report is not None:
            body["report"] = report
        st, r = http("POST", endpoint(conf, "heartbeat"), body, token=tok, timeout=timeout)
        if st == 200:
            res.update(ok=True, node=r.get("node"), office=r.get("office"), heartbeat_s=r.get("heartbeat_s"), report_s=r.get("report_s"))
        elif st in (401, 410):
            res.update(revoked=True, error=f"{st} {r.get('error') or ''}: {r.get('message') or 'the office no longer knows this node'}")
        else:
            res["error"] = f"{st} {r.get('error') or ''}: {r.get('message') or r}"
    except Exception as e:
        res["error"] = f"{e.__class__.__name__}: {str(e)[:160]}"
    return res


def me(conf, tok, timeout=15):
    return http("GET", endpoint(conf, "me"), token=tok, timeout=timeout)


def leave(conf, tok, timeout=15):
    return http("POST", endpoint(conf, "leave"), {"surface": SURFACE}, token=tok, timeout=timeout)


def nodes(url, tok, node_id=None, timeout=15):
    """GET …/nodes (or …/nodes/ID): the estate as the token's holder may see it; url is the full endpoint."""
    return http("GET", url.rstrip("/") + (f"/{node_id}" if node_id else ""), token=tok, timeout=timeout)
