#!/usr/bin/python3
"""Unit test of the agent task runner's memory half (Phase 13 slice 4): `maluctl agent create --scope` parsing,
record_memory() into the task's provenance, memory_recall() against a fake memory face on a Unix socket.
Runs without a kernel, a vault or the face:  python3 tests/agent-tasks-test.py"""
import importlib.util, json, os, socket, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "packages", "maluos-agent", "lib")
W = tempfile.mkdtemp(prefix="agent-tasks-test.")
FACE = os.path.join(W, "memory.sock")
os.environ["MALUOS_MEMORY_SOCKET"] = FACE
os.environ["MALUOS_AGENT"] = "demo"
os.environ["MALUOS_PRINCIPAL"] = "agent:demo"
os.environ["MALUOS_AGENT_SOCKET_DIR"] = W
os.environ["MALUOS_AGENTS_DIR"] = W
sys.path.insert(0, LIB)
import maluos_agent_tasks as T

fails = 0
def ok(c, label):
    global fails
    fails += 0 if c else 1
    print(("  ok   " if c else "  FAIL ") + label)

# -- 1. the scope parsing, imported from the maluctl plugin itself
spec = importlib.util.spec_from_file_location("maluctl_agent", os.path.join(LIB, "maluctl.d", "agent.py"))
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
ok(A.parse_scope("dept:3:read") == ("dept:3", "read"), "parse_scope: dept:3:read is scope dept:3, level read (the found bug)")
ok(A.parse_scope("dept:3:write") == ("dept:3", "write"), "parse_scope: dept:3:write")
ok(A.parse_scope("org:write") == ("org", "write"), "parse_scope: org:write")
ok(A.parse_scope("org") == ("org", "read"), "parse_scope: a bare scope reads")
ok(A.parse_scope("dept:3") == ("dept:3", "read"), "parse_scope: dept:3 is the whole scope, level read")
ok(A.parse_scope("user:ed:read") == ("user:ed", "read") and A.parse_scope("agent:hr:write") == ("agent:hr", "write"), "parse_scope: home scopes with a level")
ok(A.parse_scope("dept:3:other") == ("dept:3:other", "read"), "parse_scope: an unknown last part is not a level")

# -- 2. a fake memory face: /v1/recall answers canned claims and keeps every body it was given
SEEN = []
CLAIMS = [{"id": 1, "text": "Alex completed safety training in March", "scope": "dept:3", "kind": "note", "sensitivity": "internal", "holder": "server:57", "rank": 1, "writer": "agent:hr"},
          {"id": 2, "text": "Alex is on the forklift rota", "scope": "org", "kind": "summary", "sensitivity": "internal", "holder": "desk:41", "rank": 2, "writer": "user:ed"}]
class S(HTTPServer):
    address_family = socket.AF_UNIX
    def server_bind(self):
        try: os.remove(self.server_address)
        except OSError: pass
        self.socket.bind(self.server_address); os.chmod(self.server_address, 0o666)
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, status, obj):
        d = json.dumps(obj).encode(); self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SEEN.append((self.path, body))
        if self.path != "/v1/recall":
            return self._send(404, {"error": {"code": "not_found", "message": self.path}})
        q = body.get("query") or ""
        if q == "forbidden":
            return self._send(403, {"error": {"code": "forbidden", "message": "agent:demo may not read dept:9"}})
        if q == "nothing":
            return self._send(200, {"ok": True, "principal": "agent:demo", "scopes": ["agent:demo"], "claims": [], "holders": [], "holders_failed": [], "count": 0})
        out = {"ok": True, "principal": "agent:demo", "scopes": ["agent:demo", "dept:3", "org"], "claims": CLAIMS, "holders": ["server:57", "desk:41"] if body.get("estate") else [],
               "holders_failed": [{"holder": "server:58", "error": "timeout"}] if body.get("estate") else [], "count": len(CLAIMS)}
        if q == "with scopes_read":
            out["scopes_read"] = ["dept:3", "org", "agent:demo"]
        self._send(200, out)
srv = S(FACE, H); threading.Thread(target=srv.serve_forever, daemon=True).start()
for _ in range(40):
    if os.path.exists(FACE): break
    time.sleep(0.05)

# -- 3. memory_recall outside a task: the answer, the body it sent, nothing recorded
r = T.memory_recall("alex")
ok(r.get("ok") is True and len(r["claims"]) == 2 and r["holders"] == ["server:57", "desk:41"], "memory_recall: the face's answer as it gave it (claims, holders)")
path, body = SEEN[-1]
ok(path == "/v1/recall" and body["query"] == "alex" and body["estate"] is True and body["limit"] == 12 and body["classification"] == "internal" and body["envelope"] is None and body["scopes"] is None,
   "memory_recall: POST /v1/recall {query, scopes, classification, limit, estate, envelope}; the defaults without a task")
r = T.memory_recall("alex", scopes=["dept:3"], classification="restricted", limit=3, estate=False)
ok(SEEN[-1][1] == {"query": "alex", "scopes": ["dept:3"], "classification": "restricted", "limit": 3, "estate": False, "envelope": None}, "memory_recall: the arguments reach the face")
r = T.memory_recall("forbidden")
ok(r == {"ok": False, "error": {"code": "forbidden", "message": "agent:demo may not read dept:9"}}, "memory_recall: the face's refusal comes back as ok False with its code and message")
saved = T.MEMORY_SOCKET; T.MEMORY_SOCKET = os.path.join(W, "absent.sock")
r = T.memory_recall("alex")
T.MEMORY_SOCKET = saved
ok(r.get("ok") is False and r["error"]["code"] == "unavailable" and "not reachable" in r["error"]["message"], "memory_recall: no face: ok False, nothing raised")

# -- 4. inside a task: the envelope and its classification travel; the scopes read and holders land in the provenance
ENV = {"id": "env_test1", "v": 1, "originator": {"principal": "user:ed", "kind": "human", "node": "desk:41"}, "authority": {"classification": "restricted", "scopes": []}, "sig": {"alg": "ed25519", "value": "x"}}
T._local.task = {"id": "t0", "_envelope": ENV}
r = T.memory_recall("alex")
ok(SEEN[-1][1]["envelope"] == ENV and SEEN[-1][1]["classification"] == "restricted", "memory_recall in a task: the task's envelope and its classification are sent")
ok(T._local.task["_memory"][0]["scopes_read"] == ["dept:3", "org"] and T._local.task["_memory"][0]["holders"] == ["desk:41", "server:57"], "memory_recall in a task: scopes_read from the claims' scopes, holders sorted")
r = T.memory_recall("with scopes_read", classification="public")
ok(SEEN[-1][1]["classification"] == "public" and T._local.task["_memory"][1]["scopes_read"] == ["agent:demo", "dept:3", "org"], "a given classification wins; the face's scopes_read is preferred over the claims' scopes")
T._local.task = None
T.record_memory(["x"], ["y"])
ok(True, "record_memory outside a task is a no-op")

def handle(t):
    if t["text"] == "by hand":
        T.record_memory(["dept:3", "org"], ["server:57"]); T.record_memory(["dept:3"], None); T.record_memory(["agent:demo"], ["desk:41"])
        return "recorded"
    if t["text"] == "nothing":
        r = T.memory_recall("nothing"); return "none" if r.get("ok") and not r["claims"] else "?"
    if t["text"] == "no face":
        T.MEMORY_SOCKET = os.path.join(W, "absent.sock")
        try:
            r = T.memory_recall("alex")
        finally:
            T.MEMORY_SOCKET = saved
        return "unavailable" if r.get("ok") is False else "?"
    r = T.memory_recall(t["text"])
    return "\n".join(f"- {c['text']} ({c['scope']}, {c['sensitivity']}, from {c['holder']})" for c in r["claims"])
agent = T.serve(handle, card={"description": "test"}, path=os.path.join(W, "demo", "tasks.sock"))
c = T.Client.local("demo")
t = c.send("by hand")
ok(t["state"] == "completed" and t["provenance"]["scopes_read"] == ["agent:demo", "dept:3", "org"] and t["provenance"]["holders"] == ["desk:41", "server:57"],
   "record_memory -> provenance.scopes_read and holders are the sorted unions over the task")
t = c.send("alex")
ok(t["state"] == "completed" and t["output"]["text"].startswith("- Alex completed safety training in March (dept:3, internal, from server:57)\n- Alex is on the forklift rota (org, internal, from desk:41)"),
   "memory_recall in a served task: the claims answer the task")
ok(t["provenance"]["scopes_read"] == ["dept:3", "org"] and t["provenance"]["holders"] == ["desk:41", "server:57"] and "_memory" not in t, "its provenance names the scopes read and the holders; the record is consumed")
t = c.send("nothing")
ok(t["state"] == "completed" and t["output"]["text"] == "none" and t["provenance"]["scopes_read"] == [] and t["provenance"]["holders"] == [], "an empty answer: empty unions")
t = c.send("no face")
ok(t["state"] == "completed" and t["output"]["text"] == "unavailable" and t["provenance"]["scopes_read"] == [], "a task survives an absent face: nothing recorded, nothing raised")
ok(agent.card["version"] == "0.4" and t["provenance"].get("models") == [], "the protocol version is 0.4; models stay their own list")

srv.shutdown()
print(("agent-tasks-test: %d FAIL" % fails) if fails else "agent-tasks-test: all ok")
sys.exit(1 if fails else 0)
