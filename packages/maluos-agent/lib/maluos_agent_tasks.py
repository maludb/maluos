"""maluos_agent_tasks: the task interface of a MaluOS agent (Phase 12 slice 8; the delegation envelope since
Phase 13 slice 2, docs/phase13-slice2-delegation.md).

One protocol for an agent wherever it runs: JSON-RPC 2.0 over HTTP, shaped
like A2A (tasks/send, tasks/get, tasks/list, tasks/resume, agent/card). A local agent
serves it on a Unix socket in its runtime directory
(MALUOS_AGENT_TASKS_SOCKET, /run/maluos/agents/NAME/tasks.sock) and answers
only its owner, root and itself (SO_PEERCRED, no token); the estate daemon
(user maluos-estate) may bring a task that carries an ENVELOPE, and the
envelope is the authorisation then: its signature is checked against the
directory's keys (/run/maluos/estate/keys.json), its expiry and nonce, and
the agent's own policy (/etc/maluos/agents/NAME.policy.yaml: accept_from,
max_classification, approve). A task the policy wants approved parks as
pending_approval until tasks/resume brings the person's signed decision.

Server, in an agent:

    import maluos_agent_tasks as tasks
    def handle(task):                      # task = {"id", "text", "parts": [...], "ts", "progress", "envelope", "answer"}
        task["progress"]("thinking…")      # partial text, shown while the task works (slice 9)
        return "the answer"                # or {"text": ..., "artifacts": [...]}
    tasks.serve(handle, card={"name": "Research", "description": "...", "capabilities": ["research"]})

    tasks.gateway_headers()                # inside a task: X-MaluOS-Sensitivity and X-MaluOS-Envelope for the gateway
    tasks.record_model_call(resp.headers)  # after a gateway call: the provenance's models list

serve() returns at once (a daemon thread); tasks run one at a time in order.
A task is {"id", "state": submitted|working|pending_approval|completed|failed|refused, "ts", "input": {"text"},
"output": {"text", "artifacts"}, "error", "done_ts", "envelope_id", "provenance", "usage", "ask"}. While it works,
output.text is whatever the handler reported through progress() so far; the final return value replaces it.

Client:

    c = tasks.Client.local("research")     # or tasks.Client(url, token) for an estate agent
    c.card(); c.send("summarise ...", envelope=env); c.get(id); c.list(); c.resume(id, answer)
    c.stream("summarise ...", on_text)     # send without waiting, poll tasks/get, on_text(text) as it grows
"""
import http.client, json, os, pwd, socket, struct, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import UnixStreamServer

VERSION = "0.3"
SOCKET_DIR = os.environ.get("MALUOS_AGENT_SOCKET_DIR", "/run/maluos/agents")
AGENTS_DIR = os.environ.get("MALUOS_AGENTS_DIR", "/etc/maluos/agents")
ESTATE_USER = os.environ.get("MALUOS_ESTATE_USER", "maluos-estate")
_local = threading.local()


def socket_path(name=None):
    if name:
        return f"{SOCKET_DIR}/{name}/tasks.sock"
    return os.environ.get("MALUOS_AGENT_TASKS_SOCKET") or (f"{SOCKET_DIR}/{os.environ['MALUOS_AGENT']}/tasks.sock" if os.environ.get("MALUOS_AGENT") else None)


def _uid_of(login):
    try:
        return pwd.getpwnam(login).pw_uid
    except KeyError:
        return None


def _owner_uid():
    o = os.environ.get("MALUOS_AGENT_OWNER") or ""
    return _uid_of(o[5:]) if o.startswith("user:") else None


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class TaskError(Exception):
    def __init__(self, code, message, reason=None):
        super().__init__(message); self.code, self.message, self.reason = code, message, reason


# -- the task context (what the running handler and the gateway client read)
def current():
    """The task being worked on this thread, or None."""
    return getattr(_local, "task", None)


def gateway_headers():
    """Headers a model call made during an estate task carries: the envelope's classification and id (the gateway's
    egress gate holds the originator's ceiling; the ledger row carries the envelope)."""
    t = current()
    env = (t or {}).get("envelope") if t else None
    if not env:
        return {}
    h = {"X-MaluOS-Envelope": env.get("id") or ""}
    cls = (env.get("authority") or {}).get("classification")
    if cls:
        h["X-MaluOS-Sensitivity"] = cls
    return h


def record_model_call(headers=None, model=None, backend=None, usd=None):
    """Remember a model call for the task's provenance: from the gateway's response headers (X-MaluOS-Request,
    X-MaluOS-Route) or given by hand."""
    t = current()
    if t is None:
        return
    h = {k.lower(): v for k, v in dict(headers or {}).items()}
    route = h.get("x-maluos-route") or ""
    bm = route.split(" ")[0] if route else ""
    b, _, m = bm.partition("/")
    t.setdefault("_models", []).append({"request": h.get("x-maluos-request"), "model": model or m or None, "backend": backend or b or None,
                                        "usd": usd if usd is not None else None, "ts": utc()})


# -- the policy (slice 2): read at every envelope-bearing send, so `maluctl agent policy set` applies at once
def read_policy(name=None):
    name = name or os.environ.get("MALUOS_AGENT") or ""
    pol = {"accept_from": None, "max_classification": None, "approve": []}
    for fn, keys in ((f"{AGENTS_DIR}/{name}.manifest.yaml", ("accept_from", "max_classification", "approve")),
                     (f"{AGENTS_DIR}/{name}.policy.yaml", ("accept_from", "max_classification", "approve"))):
        try:
            import yaml
            with open(fn) as fh:
                d = yaml.safe_load(fh) or {}
            for k in keys:
                if k in d and d[k] is not None:
                    pol[k] = d[k]
        except Exception:
            pass
    pol["accept_from"] = [str(x) for x in (pol["accept_from"] or [])]
    pol["approve"] = [str(x) for x in (pol["approve"] or [])]
    return pol


def _envelope_mod():
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_estate.envelope as E
    return E


# -- server
class _Server(UnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    agent = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/card"):
            return self._send(200, self.agent.card)
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        creds = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        rid = req.get("id"); method = req.get("method"); params = req.get("params") or {}
        if uid not in self.agent.allow:
            # the estate daemon brings tasks from the office: the envelope is the authorisation, not the caller
            carried = uid == self.agent.estate_uid and (
                (method in ("tasks/send", "tasks/resume") and isinstance(params.get("envelope") or (params.get("answer") or {}).get("envelope"), dict))
                or method in ("tasks/get", "agent/card"))
            if not carried:
                return self._send(403, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": f"uid {uid} may not talk to this agent (its owner, root and itself may; the estate daemon with an envelope)"}})
        try:
            res = self.agent.dispatch(method, params, uid)
            self._send(200, {"jsonrpc": "2.0", "id": rid, "result": res})
        except TaskError as e:
            err = {"code": e.code, "message": e.message}
            if e.reason:
                err["data"] = {"reason": e.reason}
            self._send(200, {"jsonrpc": "2.0", "id": rid, "error": err})


class Agent:
    """The task state of one agent: a queue worked in order by one thread."""

    def __init__(self, handle, card=None, allow_uids=None):
        name = os.environ.get("MALUOS_AGENT", "agent")
        self.name = name
        self.card = {"name": name, "description": "", "capabilities": [], "version": VERSION, "principal": os.environ.get("MALUOS_PRINCIPAL"),
                     "owner": os.environ.get("MALUOS_AGENT_OWNER"), "protocol": "maluos-tasks/" + VERSION, **(card or {})}
        self.handle = handle
        self.allow = set(allow_uids or ()) | {0, os.getuid()}
        ou = _owner_uid()
        if ou is not None:
            self.allow.add(ou)
        self.estate_uid = _uid_of(ESTATE_USER)
        self.tasks, self.order, self.lock, self.wake = {}, [], threading.Lock(), threading.Event()
        self.nonces = None
        self.keys = None

    # -- the envelope on an incoming task (slice 2)
    def verify_envelope(self, env, purpose="task"):
        """The signature, times and nonce against the directory's keys, then this agent's policy. Raises TaskError."""
        try:
            E = _envelope_mod()
        except Exception as e:
            raise TaskError(-32001, f"envelopes cannot be verified here (maluos-estate missing: {e.__class__.__name__})", "bad_envelope")
        if self.nonces is None:
            self.nonces = E.Nonces()
        if self.keys is None:
            self.keys = E.Keys()
        self.keys.load()
        ok, reason, msg = E.verify(env, self.keys.table(), None, self.nonces)
        if not ok:
            self.log(f"{purpose} refused ({reason}): {msg}; envelope {env.get('id') if isinstance(env, dict) else '?'}")
            raise TaskError(-32001, msg, reason)
        return E

    def apply_policy(self, env, E):
        pol = read_policy(self.name)
        owner = os.environ.get("MALUOS_AGENT_OWNER") or ""
        o = env.get("originator") or {}
        if not E.accepts(pol["accept_from"], owner, o):
            self.log(f"task refused (not_accepted): originator {o.get('principal')} is not in accept_from {pol['accept_from'] or ['(the owner only)']}; envelope {env['id']}")
            raise TaskError(-32001, f"this agent does not accept tasks from {o.get('principal')}", "not_accepted")
        cls = (env.get("authority") or {}).get("classification", "internal")
        approval = E.needs_approval(pol["approve"], env)          # the owner's approval admits what the ceiling alone would refuse
        if not approval and not E.classification_within(cls, pol["max_classification"]):
            self.log(f"task refused (classification): {cls} is above {pol['max_classification']}; envelope {env['id']}")
            raise TaskError(-32001, f"classification {cls} is above this agent's ceiling ({pol['max_classification']})", "classification")
        return approval

    def log(self, msg):
        sys.stderr.write(f"maluos_agent_tasks[{self.name}]: {msg}\n"); sys.stderr.flush()

    def dispatch(self, method, params, uid):
        if method == "agent/card":
            return dict(self.card, policy=read_policy(self.name))
        if method == "tasks/send":
            msg = params.get("message") or {}
            parts = msg.get("parts") or ([{"type": "text", "text": params["text"]}] if params.get("text") else [])
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type", "text") == "text").strip()
            if not text:
                raise TaskError(-32602, "tasks/send needs message.parts with text")
            env = params.get("envelope")
            approval = False
            if isinstance(env, dict):
                E = self.verify_envelope(env)
                approval = self.apply_policy(env, E)
            elif env is not None:
                raise TaskError(-32602, "envelope is an object", "bad_envelope")
            tid = params.get("id") or uuid.uuid4().hex[:12]
            with self.lock:
                if tid in self.tasks:
                    return dict(self.tasks[tid])
            t = {"id": tid, "state": "pending_approval" if approval else "submitted", "ts": utc(),
                 "from_uid": uid, "input": {"text": text, "parts": parts}, "output": None, "error": None, "done_ts": None,
                 "envelope_id": env.get("id") if isinstance(env, dict) else None, "_envelope": env if isinstance(env, dict) else None,
                 "provenance": None, "usage": None, "ask": None, "answer": None}
            if approval:
                cls = (env.get("authority") or {}).get("classification", "internal")
                t["ask"] = {"kind": "decision_needed", "subject": f"{self.name} asks to run a {cls} task", "body": text[:2000], "options": ["approve", "deny"]}
                self.log(f"task {tid} parked pending_approval ({cls} from {(env.get('originator') or {}).get('principal')}); envelope {env['id']}")
            with self.lock:
                self.tasks[t["id"]] = t; self.order.append(t["id"])
                if len(self.order) > 200:
                    self.tasks.pop(self.order.pop(0), None)
            if not approval:
                self.wake.set()
                if params.get("wait", True):
                    deadline = time.time() + float(params.get("timeout") or 180)
                    while t["state"] in ("submitted", "working") and time.time() < deadline:
                        time.sleep(0.2)
            return self.present(t)
        if method == "tasks/resume":
            t = self.tasks.get(params.get("id") or "")
            if not t:
                raise TaskError(-32004, "no such task")
            if t["state"] != "pending_approval":
                raise TaskError(-32002, f"task {t['id']} is {t['state']}, not waiting", "not_waiting")
            ans = params.get("answer") or {}
            env = ans.get("envelope")
            if t.get("_envelope") is not None:
                if not isinstance(env, dict):
                    raise TaskError(-32602, "the answer carries the decider's envelope", "bad_envelope")
                self.verify_envelope(env, "decision")
                # the decider is the originator (or their desk), else refused
                o = (t["_envelope"].get("originator") or {})
                if (env.get("sender") or {}).get("node") != o.get("node") and (env.get("originator") or {}).get("principal") != o.get("principal"):
                    raise TaskError(-32001, "the decision must come from the task's originator", "not_accepted")
            t["answer"] = {k: ans.get(k) for k in ("kind", "decision", "note", "text", "by", "ts")}
            if ans.get("decision") == "deny":
                t["state"], t["error"], t["done_ts"] = "refused", "denied: " + (ans.get("note") or "the owner denied it"), utc()
                self.log(f"task {t['id']} denied by {ans.get('by')}")
                return self.present(t)
            t["state"], t["ask"] = "submitted", None
            self.wake.set()
            if params.get("wait", False):
                deadline = time.time() + float(params.get("timeout") or 180)
                while t["state"] in ("submitted", "working") and time.time() < deadline:
                    time.sleep(0.2)
            return self.present(t)
        if method == "tasks/get":
            t = self.tasks.get(params.get("id") or "")
            if not t:
                raise TaskError(-32004, "no such task")
            return self.present(t)
        if method == "tasks/list":
            with self.lock:
                return {"tasks": [self.present(self.tasks[i]) for i in reversed(self.order[-int(params.get("limit") or 50):])]}
        raise TaskError(-32601, f"unknown method {method}")

    @staticmethod
    def present(t):
        return {k: v for k, v in t.items() if not k.startswith("_")}

    def work(self):
        while True:
            self.wake.wait(); self.wake.clear()
            while True:
                with self.lock:
                    nxt = next((self.tasks[i] for i in self.order if self.tasks[i]["state"] == "submitted"), None)
                if not nxt:
                    break
                nxt["state"] = "working"; nxt["_started"] = utc()

                def progress(text, t=nxt):
                    """Partial output while the task works; replaced by the handler's return value."""
                    t["output"] = {"text": "" if text is None else str(text), "artifacts": [], "partial": True}
                _local.task = nxt
                try:
                    out = self.handle(dict(nxt["input"], id=nxt["id"], ts=nxt["ts"], progress=progress, envelope=nxt.get("_envelope"), answer=nxt.get("answer")))
                    if isinstance(out, dict):
                        nxt["output"] = {"text": out.get("text", ""), "artifacts": out.get("artifacts") or []}
                    else:
                        nxt["output"] = {"text": "" if out is None else str(out), "artifacts": []}
                    nxt["state"] = "completed"
                except Exception as e:
                    nxt["error"] = f"{e.__class__.__name__}: {str(e)[:400]}"; nxt["state"] = "failed"
                finally:
                    _local.task = None
                nxt["done_ts"] = utc()
                self.provenance(nxt)

    def provenance(self, t):
        """The task's provenance and usage (slice 2): the envelope's chain plus this hop, the model calls made, the budget."""
        env = t.get("_envelope")
        models = t.pop("_models", []) or []
        usd = sum(float(m.get("usd") or 0) for m in models)
        me = {"principal": self.card.get("principal") or f"agent:{self.name}", "node": (env or {}).get("target", {}).get("node") if env else None}
        chain = list((env or {}).get("chain") or []) + [dict(me, ts=t["done_ts"], task_id=t["id"])]
        t["provenance"] = {"envelope": t.get("envelope_id"), "node": me["node"], "agent": me["principal"], "chain": chain, "models": models,
                           "scopes_read": [], "started_at": t.get("_started"), "done_ts": t["done_ts"]}
        t["usage"] = {"usd": round(usd, 6), "calls": len(models), "budget": ((env or {}).get("authority") or {}).get("budget")}


def serve(handle, card=None, path=None, allow_uids=None):
    """Start serving tasks on the agent's socket in a daemon thread; returns the Agent (None when no socket path applies)."""
    path = path or socket_path()
    if not path:
        return None
    agent = Agent(handle, card, allow_uids)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    handler = type("Handler", (_Handler,), {"agent": agent})
    srv = _Server(path, handler)
    os.chmod(path, 0o666)                     # SO_PEERCRED does the authorisation
    threading.Thread(target=agent.work, daemon=True).start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return agent


# -- client
class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=200):
        super().__init__("agent", timeout=timeout); self.path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(self.timeout); s.connect(self.path); self.sock = s


class Client:
    """tasks/* against a local agent's socket or an estate agent's task URL (Bearer token)."""

    def __init__(self, url, token=None, timeout=200):
        self.url, self.token, self.timeout = url, token, timeout

    @classmethod
    def local(cls, name, timeout=200):
        return cls(socket_path(name), timeout=timeout)

    @property
    def available(self):
        return not self.url.startswith("http") and os.path.exists(self.url)

    def call(self, method, params=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
        headers = {"Content-Type": "application/json"}
        if self.url.startswith("http"):
            u = urllib.parse.urlsplit(self.url)
            conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=self.timeout)
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
        else:
            if not os.path.exists(self.url):
                raise TaskError(-32000, "this agent does not accept tasks (no task socket; it is not running or does not serve maluos_agent_tasks)")
            conn, path = _UnixConn(self.url, self.timeout), "/rpc"
        try:
            conn.request("POST", path, body=body, headers=headers)
            r = conn.getresponse(); data = r.read()
        except (OSError, http.client.HTTPException) as e:
            raise TaskError(-32000, f"{e.__class__.__name__}: {str(e)[:200]}")
        finally:
            conn.close()
        try:
            d = json.loads(data)
        except ValueError:
            raise TaskError(-32000, f"HTTP {r.status}: not JSON")
        err = d.get("error") if isinstance(d, dict) else None
        if isinstance(err, dict):
            raise TaskError(err.get("code", -32000), err.get("message") or f"HTTP {r.status}", (err.get("data") or {}).get("reason"))
        if err or r.status != 200:                       # the office's own error shape: {"error": code, "message": text}
            raise TaskError(-32000, f"HTTP {r.status}: {d.get('message') or err or ''}".strip(), err if isinstance(err, str) else None)
        return d.get("result")

    def card(self):          return self.call("agent/card")

    def send(self, text, wait=True, timeout=180, envelope=None, task_id=None):
        p = {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}, "wait": wait, "timeout": timeout}
        if envelope is not None:
            p["envelope"] = envelope
        if task_id:
            p["id"] = task_id
        return self.call("tasks/send", p)

    def get(self, tid):      return self.call("tasks/get", {"id": tid})
    def resume(self, tid, answer, wait=False, timeout=180): return self.call("tasks/resume", {"id": tid, "answer": answer, "wait": wait, "timeout": timeout})

    def stream(self, text, on_text=None, timeout=180, every=0.5, envelope=None):
        """Send without waiting, then poll tasks/get until the task is done, calling on_text(text) whenever
        the (partial) answer grows; returns the final task. An office that answers at once needs no polling."""
        t = self.send(text, wait=False, timeout=timeout, envelope=envelope)
        shown = ""
        deadline = time.time() + float(timeout)
        while True:
            txt = (t.get("output") or {}).get("text") or ""
            if txt != shown and on_text:
                on_text(txt); shown = txt
            if t.get("state") not in ("submitted", "working", "queued", "leased", "running"):
                return t
            if time.time() > deadline:
                t = dict(t, state="failed", error=f"no answer within {timeout:.0f} s (task {t.get('id')} still {t.get('state')})"); return t
            time.sleep(every)
            t = self.get(t["id"])
    def list(self, limit=50): return self.call("tasks/list", {"limit": limit})["tasks"]
