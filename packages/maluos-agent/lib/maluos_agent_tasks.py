"""maluos_agent_tasks: the task interface of a MaluOS agent (Phase 12 slice 8).

One protocol for an agent wherever it runs: JSON-RPC 2.0 over HTTP, shaped
like A2A (tasks/send, tasks/get, tasks/list, agent/card). A local agent
serves it on a Unix socket in its runtime directory
(MALUOS_AGENT_TASKS_SOCKET, /run/maluos/agents/NAME/tasks.sock) and answers
only its owner, root and itself (SO_PEERCRED, no token); an office serves
the same methods for its agents over HTTPS with the desk token. The Agents
app and `maluctl agent send` are the clients; Phase 13 slice 2 puts the
delegation envelope on it.

Server, in an agent:

    import maluos_agent_tasks as tasks
    def handle(task):                      # task = {"id", "text", "parts": [...], "ts"}
        return "the answer"                # or {"text": ..., "artifacts": [...]}
    tasks.serve(handle, card={"name": "Research", "description": "...", "capabilities": ["research"]})

serve() returns at once (a daemon thread); tasks run one at a time in order.
A task is {"id", "state": submitted|working|completed|failed, "ts", "input": {"text"},
"output": {"text", "artifacts"}, "error", "done_ts"}.

Client:

    c = tasks.Client.local("research")     # or tasks.Client(url, token) for an office agent
    c.card(); c.send("summarise ..."); c.get(id); c.list()
"""
import http.client, json, os, pwd, socket, struct, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import UnixStreamServer

VERSION = "0.1"
SOCKET_DIR = "/run/maluos/agents"


def socket_path(name=None):
    if name:
        return f"{SOCKET_DIR}/{name}/tasks.sock"
    return os.environ.get("MALUOS_AGENT_TASKS_SOCKET") or (f"{SOCKET_DIR}/{os.environ['MALUOS_AGENT']}/tasks.sock" if os.environ.get("MALUOS_AGENT") else None)


def _owner_uid():
    o = os.environ.get("MALUOS_AGENT_OWNER") or ""
    if o.startswith("user:"):
        try:
            return pwd.getpwnam(o[5:]).pw_uid
        except KeyError:
            pass
    return None


class TaskError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code, self.message = code, message


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
        if uid not in self.agent.allow:
            return self._send(403, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": f"uid {uid} may not talk to this agent (its owner, root and itself may)"}})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        rid = req.get("id")
        try:
            res = self.agent.dispatch(req.get("method"), req.get("params") or {}, uid)
            self._send(200, {"jsonrpc": "2.0", "id": rid, "result": res})
        except TaskError as e:
            self._send(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}})


class Agent:
    """The task state of one agent: a queue worked in order by one thread."""

    def __init__(self, handle, card=None, allow_uids=None):
        name = os.environ.get("MALUOS_AGENT", "agent")
        self.card = {"name": name, "description": "", "capabilities": [], "version": VERSION, "principal": os.environ.get("MALUOS_PRINCIPAL"),
                     "owner": os.environ.get("MALUOS_AGENT_OWNER"), "protocol": "maluos-tasks/" + VERSION, **(card or {})}
        self.handle = handle
        self.allow = set(allow_uids or ()) | {0, os.getuid()}
        ou = _owner_uid()
        if ou is not None:
            self.allow.add(ou)
        self.tasks, self.order, self.lock, self.wake = {}, [], threading.Lock(), threading.Event()

    def dispatch(self, method, params, uid):
        if method == "agent/card":
            return self.card
        if method == "tasks/send":
            msg = params.get("message") or {}
            parts = msg.get("parts") or ([{"type": "text", "text": params["text"]}] if params.get("text") else [])
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type", "text") == "text").strip()
            if not text:
                raise TaskError(-32602, "tasks/send needs message.parts with text")
            t = {"id": params.get("id") or uuid.uuid4().hex[:12], "state": "submitted", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "from_uid": uid, "input": {"text": text, "parts": parts}, "output": None, "error": None, "done_ts": None}
            with self.lock:
                self.tasks[t["id"]] = t; self.order.append(t["id"])
                if len(self.order) > 200:
                    self.tasks.pop(self.order.pop(0), None)
            self.wake.set()
            if params.get("wait", True):
                deadline = time.time() + float(params.get("timeout") or 180)
                while t["state"] in ("submitted", "working") and time.time() < deadline:
                    time.sleep(0.2)
            return dict(t)
        if method == "tasks/get":
            t = self.tasks.get(params.get("id") or "")
            if not t:
                raise TaskError(-32004, "no such task")
            return dict(t)
        if method == "tasks/list":
            with self.lock:
                return {"tasks": [dict(self.tasks[i]) for i in reversed(self.order[-int(params.get("limit") or 50):])]}
        raise TaskError(-32601, f"unknown method {method}")

    def work(self):
        while True:
            self.wake.wait(); self.wake.clear()
            while True:
                with self.lock:
                    nxt = next((self.tasks[i] for i in self.order if self.tasks[i]["state"] == "submitted"), None)
                if not nxt:
                    break
                nxt["state"] = "working"
                try:
                    out = self.handle(dict(nxt["input"], id=nxt["id"], ts=nxt["ts"]))
                    if isinstance(out, dict):
                        nxt["output"] = {"text": out.get("text", ""), "artifacts": out.get("artifacts") or []}
                    else:
                        nxt["output"] = {"text": "" if out is None else str(out), "artifacts": []}
                    nxt["state"] = "completed"
                except Exception as e:
                    nxt["error"] = f"{e.__class__.__name__}: {str(e)[:400]}"; nxt["state"] = "failed"
                nxt["done_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    """tasks/* against a local agent's socket or an office's agent task URL (Bearer token)."""

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
            path = u.path or "/"
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
            raise TaskError(err.get("code", -32000), err.get("message") or f"HTTP {r.status}")
        if err or r.status != 200:                       # the office's own error shape: {"error": code, "message": text}
            raise TaskError(-32000, f"HTTP {r.status}: {d.get('message') or err or ''}".strip())
        return d.get("result")

    def card(self):          return self.call("agent/card")
    def send(self, text, wait=True, timeout=180):
        return self.call("tasks/send", {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}, "wait": wait, "timeout": timeout})
    def get(self, tid):      return self.call("tasks/get", {"id": tid})
    def list(self, limit=50): return self.call("tasks/list", {"limit": limit})["tasks"]
