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
import hashlib, json, os, shutil, socket, time, urllib.error, urllib.parse, urllib.request

from . import VERSION

SURFACE = 1
CONF = os.environ.get("MALUOS_ESTATE_CONF", "/etc/maluos/estate.yaml")
STATE_DIR = os.environ.get("MALUOS_ESTATE_STATE_DIR", "/var/lib/maluos/estate")
STATE = os.path.join(STATE_DIR, "state.json")
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
PROVISIONED = os.environ.get("MALUOS_PROVISIONED", "/var/lib/maluos/firstboot/done")
USER = os.environ.get("MALUOS_ESTATE_USER", "maluos-estate")
SECRET_TOKEN, SECRET_KEY = "estate-node-token", "estate-node-key"
SECRET_OVERLAY = "estate-overlay-key"      # the WireGuard private key (slice 1b), beside the token
SECRET_INFERENCE = "estate-inference-key"  # the estate's inference credential (slice 3), beside the token; the gateway holds a `use` grant
OFFICE_SECRET = "office-desk-token"        # the desk's token (maluos-desk), in the owner's compartment
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


def heartbeat(conf, tok, presence="online", report=None, timeout=20, agents=None, inference=None):
    """One heartbeat: presence, facts, (when given) the report, (slice 2) the agents this node registers and (slice 3) the
    gateway's inference facts. The outcome in the shape state.json keeps."""
    res = {"ts": utc(), "ok": False, "presence": presence, "revoked": False, "error": None, "node": None, "report_sent": report is not None}
    try:
        f = facts()
        body = {"surface": SURFACE, "presence": presence, "app_version": f["app_version"],
                "facts": {k: f[k] for k in ("hostname", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb") if k in f}}
        if report is not None:
            body["report"] = report
        if agents is not None:
            body["agents"] = agents
        if inference is not None:
            body["inference"] = inference
        st, r = http("POST", endpoint(conf, "heartbeat"), body, token=tok, timeout=timeout)
        if st == 200:
            res.update(ok=True, node=r.get("node"), office=r.get("office"), heartbeat_s=r.get("heartbeat_s"), report_s=r.get("report_s"),
                       overlay_changed=bool(r.get("overlay_changed")), agents_registered=r.get("agents_registered"),
                       inference_changed=bool(r.get("inference_changed")), peers_changed=bool(r.get("peers_changed")), editions=r.get("editions"))
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


def overlay(url, tok, timeout=15):
    """GET endpoints.overlay: self, the hub, the peers, the names (slice 1b)."""
    return http("GET", url, token=tok, timeout=timeout)


def overlay_key(conf, tok, public_key, timeout=15):
    """POST .../estate/overlay/key: this host's new WireGuard public key (rotation)."""
    return http("POST", conf["url"].rstrip("/") + "/api/v1/estate/overlay/key", {"surface": SURFACE, "overlay_public_key": public_key}, token=tok, timeout=timeout)


def overlay_hint():
    """A heartbeat answer said overlay_changed: ask maluos-overlay to refresh now."""
    from maluos_estate import overlay as OV
    OV.hint()


# -- Phase 13 slice 2: the directory, the keys, this node's inbox, tasks and actions (docs/phase13-slice2-delegation.md)
AGENTS_DIR = os.environ.get("MALUOS_AGENTS_DIR", "/etc/maluos/agents")
AGENTS_HINT = os.environ.get("MALUOS_AGENTS_HINT", "/run/maluos/estate/agents-changed")
KEYS_CACHE = os.environ.get("MALUOS_ESTATE_KEYS", "/run/maluos/estate/keys.json")
DEFAULT_ACTIONS = ["restart_agent", "start_agent", "stop_agent", "apply_updates"]      # reboot is off unless the node's owner allows it


def manifests():
    """The agents this node registers: /etc/maluos/agents/*.manifest.yaml (written by maluctl agent create)."""
    out = []
    try:
        names = sorted(f[:-14] for f in os.listdir(AGENTS_DIR) if f.endswith(".manifest.yaml"))
    except OSError:
        return out
    for n in names:
        try:
            import yaml
            with open(f"{AGENTS_DIR}/{n}.manifest.yaml") as fh:
                m = yaml.safe_load(fh) or {}
        except Exception:
            continue
        if not isinstance(m, dict) or not m.get("name"):
            continue
        out.append({k: m.get(k) for k in ("name", "display", "description", "capabilities", "owner", "accept_from", "max_classification", "approve", "tasks", "personal") if m.get(k) is not None})
    return out


def agents_hint_take():
    """True once when `maluctl agent create|remove|policy` touched the hint since the last take."""
    try:
        os.remove(AGENTS_HINT)
        return True
    except OSError:
        return False


def register_agents(conf, tok, agents, timeout=15):
    return http("POST", endpoint(conf, "agents"), {"surface": SURFACE, "agents": agents}, token=tok, timeout=timeout)


def keys(conf_or_url, tok, timeout=15):
    """GET endpoints.keys: every member's public key and the coordinator's."""
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "keys")
    return http("GET", url, token=tok, timeout=timeout)


def agents(conf_or_url, tok, capability=None, node=None, timeout=15):
    """GET endpoints.agents: the directory (a node or a desk token)."""
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "agents")
    q = {}
    if capability:
        q["capability"] = capability
    if node:
        q["node"] = node
    return http("GET", url + ("?" + urllib.parse.urlencode(q) if q else ""), token=tok, timeout=timeout)


def inbox(conf, tok, wait=25, timeout=None):
    """GET endpoints.inbox?wait=N: the tasks and actions queued for this node, leased."""
    return http("GET", endpoint(conf, "inbox") + f"?wait={int(wait)}", token=tok, timeout=timeout or (int(wait) + 15))


def inbox_result(conf, tok, item_id, body, timeout=15):
    """POST endpoints.inbox/ID/result: a task record or an action's outcome, or {"refused": reason}."""
    return http("POST", endpoint(conf, "inbox").rstrip("/") + f"/{item_id}/result", body, token=tok, timeout=timeout)


def task(conf_or_url, tok, task_id, wait=None, timeout=15):
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "tasks")
    return http("GET", url.rstrip("/") + f"/{task_id}" + (f"?wait={int(wait)}" if wait else ""), token=tok, timeout=(timeout + int(wait)) if wait else timeout)


def actions(conf_or_url, tok, action_id=None, timeout=15):
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "actions")
    return http("GET", url.rstrip("/") + (f"/{action_id}" if action_id else ""), token=tok, timeout=timeout)


def allowed_actions(conf):
    a = (conf.get("actions") or {}).get("allow")
    return list(a) if isinstance(a, list) else list(DEFAULT_ACTIONS)


# -- Phase 13 slice 3: shared inference (docs/phase13-slice3-inference.md): the backends this member may use, the peers
# allowed to call it, its own facts, the caches the gateway reads
INFERENCE_CACHE = os.environ.get("MALUOS_ESTATE_INFERENCE", "/run/maluos/estate/inference.json")
PEERS_CACHE = os.environ.get("MALUOS_ESTATE_PEERS", "/run/maluos/estate/peers.json")
GATEWAY_SOCKET = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")
INFERENCE_REFRESH_S = 3600
PEERS_REFRESH_S = 300


def inference(conf_or_url, tok, timeout=15):
    """GET endpoints.inference: the backends the caller may use (a node or a desk token)."""
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "inference")
    return http("GET", url, token=tok, timeout=timeout)


def inference_peers(conf_or_url, tok, timeout=15):
    """GET endpoints.inference_peers: the members allowed to call this host, with their keys' hashes."""
    url = conf_or_url if isinstance(conf_or_url, str) else ((conf_or_url.get("endpoints") or {}).get("inference_peers") or conf_or_url["url"].rstrip("/") + "/api/v1/estate/inference/peers")
    return http("GET", url, token=tok, timeout=timeout)


def inference_key_new(conf_or_url, tok, timeout=15):
    """POST endpoints.inference/key: a new inference key for the caller, shown once (a member enrolled before slice 3, or a rotation)."""
    url = conf_or_url if isinstance(conf_or_url, str) else endpoint(conf_or_url, "inference")
    return http("POST", url.rstrip("/") + "/key", {"surface": SURFACE}, token=tok, timeout=timeout)


def gateway_inference(timeout=5):
    """This host's inference facts from its gateway (GET /v1/maluos/inference over the socket), or None without a gateway."""
    if not os.path.exists(GATEWAY_SOCKET):
        return None
    import http.client, socket as _socket

    class _Conn(http.client.HTTPConnection):
        def __init__(self, path):
            super().__init__("maluos-gateway", timeout=timeout); self._path = path

        def connect(self):
            s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM); s.settimeout(timeout); s.connect(self._path); self.sock = s
    try:
        c = _Conn(GATEWAY_SOCKET); c.request("GET", "/v1/maluos/inference"); r = c.getresponse(); raw = r.read(); c.close()
        if r.status != 200:
            return None
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def write_cache(path, answer, secret_ref, principal, source):
    """The gateway reads these: the directory's answer plus the vault ref of this host's inference key. Atomic, world-readable."""
    d = {k: answer.get(k) for k in ("ok", "fetched_at", "self", "backends", "peers", "editions", "place", "lease_s", "refresh_s", "version") if k in answer}
    d.update({"secret": secret_ref, "principal": principal, "source": source, "written_at": utc()})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(d, fh)
    os.chmod(tmp, 0o644); os.replace(tmp, path)
    return d


def read_cache(path):
    try:
        with open(path) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def drop_caches(*paths):
    for p in paths or (INFERENCE_CACHE, PEERS_CACHE):
        try:
            os.remove(p)
        except OSError:
            pass


def refresh_inference(conf, tok, which=("backends", "peers"), timeout=15):
    """Re-read the directory's backends and/or the peers for a node and write the caches. Returns {name: (status, answer)}."""
    out = {}
    secret_ref = f"{conf.get('principal')}/{SECRET_INFERENCE}" if conf.get("principal") else SECRET_INFERENCE
    if "backends" in which:
        st, r = inference(conf, tok, timeout=timeout)
        if st == 200:
            write_cache(INFERENCE_CACHE, r, secret_ref, conf.get("principal"), "node")
        out["backends"] = (st, r)
    if "peers" in which:
        st, r = inference_peers(conf, tok, timeout=timeout)
        if st == 200:
            write_cache(PEERS_CACHE, r, secret_ref, conf.get("principal"), "node")
        out["peers"] = (st, r)
    return out
