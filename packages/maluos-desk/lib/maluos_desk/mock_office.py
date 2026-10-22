"""A mock Business OS office for tests: the desk contract, surface 1 (docs/desk-enrolment.md),
an OpenAI-wire model endpoint beneath /desk-models, records/activity/memory MCP stubs, and
inspection hooks. Stdlib only; deterministic replies.

  python3 -m maluos_desk.mock_office --port 18080 --code CODE [--code CODE2] [--name "Mock Office"]
                                      [--models office-7b,office-embed] [--heartbeat-s 300]

  GET  /api/v1/health                      {"ok": true, "office": NAME}
  POST /api/v1/desks/enroll                the contract
  POST /api/v1/desks/heartbeat, GET /api/v1/desks/me, POST /api/v1/desks/leave   (Bearer desk token)
  GET  /desk-models/                       200 (the gateway's reachability probe)
  GET  /desk-models/v1/models, POST /desk-models/v1/chat/completions (Bearer; stream or not)
  POST /mcp/records | /mcp/activity | /mcp/memory   JSON-RPC: initialize, tools/list, tools/call (Bearer)
  GET  /mock/state                         desks, heartbeats, chats, mcp calls (tokens hashed)
  POST /mock/retire {"desk_id": N}         retire a desk: its token answers 410 from then on
  POST /mock/code {"code": "..."}          add a one-time code
"""
import argparse, hashlib, json, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SURFACE = 1


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Office:
    def __init__(self, name, codes, models, heartbeat_s):
        self.name, self.models, self.heartbeat_s = name, models, heartbeat_s
        self.codes = {c: {"used": False} for c in codes}
        self.desks = {}         # id -> desk
        self.tokens = {}        # token -> desk id
        self.heartbeats, self.chats, self.mcp = [], [], []
        self.next_id = 41
        self.lock = threading.Lock()

    def endpoints(self, base):
        return {"heartbeat": f"{base}/api/v1/desks/heartbeat", "me": f"{base}/api/v1/desks/me", "leave": f"{base}/api/v1/desks/leave",
                "records": f"{base}/mcp/records", "activity": f"{base}/mcp/activity", "memory": f"{base}/mcp/memory", "actions": None,
                "models": {"url": f"{base}/desk-models", "models": list(self.models)}}

    def answer(self, desk, base):
        return {"ok": True, "surface": SURFACE,
                "desk": {k: desk[k] for k in ("id", "name", "status", "presence", "last_seen_at")},
                "office": {"name": self.name, "url": base}, "owner": desk["owner"],
                "endpoints": self.endpoints(base), "heartbeat_s": self.heartbeat_s}

    def public(self):
        return {"office": self.name, "codes": {c: v for c, v in self.codes.items()},
                "desks": [dict(d, token_sha256=hashlib.sha256(d["token"].encode()).hexdigest()[:16], token=None) for d in self.desks.values()],
                "heartbeats": self.heartbeats[-50:], "chats": self.chats[-50:], "mcp": self.mcp[-50:]}


class Handler(BaseHTTPRequestHandler):
    office: Office = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("mock-office: " + (fmt % args) + "\n")

    # -- plumbing
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"_bad": True}

    def send(self, status, obj, extra=None):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def err(self, status, code, message):
        self.send(status, {"error": code, "message": message})

    def base(self):
        return f"http://{self.headers.get('Host') or 'localhost'}"

    def desk_from_bearer(self):
        """(desk, None) for a live token; (None, (status, code, message)) otherwise."""
        auth = self.headers.get("Authorization") or ""
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        o = self.office
        with o.lock:
            did = o.tokens.get(tok)
            desk = o.desks.get(did) if did else None
        if not desk:
            return None, (401, "unauthorized", "provide a valid desk token as a Bearer token")
        if desk["status"] == "retired":
            return None, (410, "retired", f"desk #{desk['id']} was retired by the office")
        return desk, None

    # -- routes
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        o = self.office
        if p == "/api/v1/health":
            return self.send(200, {"ok": True, "office": o.name, "surface": SURFACE})
        if p == "/api/v1/desks/me":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.send(200, o.answer(desk, self.base()))
        if p in ("/desk-models", "/desk-models/"):
            return self.send(200, {"ok": True, "office": o.name})
        if p == "/desk-models/v1/models":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "office"} for m in o.models]})
        if p == "/mock/state":
            with o.lock:
                return self.send(200, o.public())
        return self.err(404, "not_found", p)

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        o = self.office
        b = self.body()
        if b.get("_bad"):
            return self.err(400, "invalid", "malformed JSON")
        if p == "/api/v1/desks/enroll":
            return self.enroll(b)
        if p == "/api/v1/desks/heartbeat":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            presence = b.get("presence") or "online"
            if presence not in ("online", "offline"):
                return self.err(400, "invalid", "presence must be online or offline")
            with o.lock:
                desk["presence"], desk["last_seen_at"] = presence, now()
                for k in ("app_version", "mcp_surface_version"):
                    if b.get(k):
                        desk[k] = b[k]
                if isinstance(b.get("facts"), dict):
                    desk["facts"].update(b["facts"])
                o.heartbeats.append({"ts": desk["last_seen_at"], "desk_id": desk["id"], "presence": presence})
            return self.send(200, o.answer(desk, self.base()))
        if p == "/api/v1/desks/leave":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            with o.lock:
                desk["status"], desk["retired_at"], desk["presence"] = "retired", now(), "offline"
                o.tokens = {t: d for t, d in o.tokens.items() if d != desk["id"]}
            return self.send(200, {"ok": True, "surface": SURFACE, "desk": {"id": desk["id"], "status": "retired"}})
        if p == "/desk-models/v1/chat/completions":
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.chat(b, desk)
        if p in ("/mcp/records", "/mcp/activity", "/mcp/memory"):
            desk, e = self.desk_from_bearer()
            if e:
                return self.err(*e)
            return self.mcp(p, b, desk)
        if p == "/mock/retire":
            with o.lock:
                targets = [o.desks[b["desk_id"]]] if b.get("desk_id") in o.desks else list(o.desks.values())
                for d in targets:
                    d["status"], d["retired_at"], d["presence"] = "retired", now(), "offline"
            return self.send(200, {"ok": True, "retired": [d["id"] for d in targets]})
        if p == "/mock/code":
            with o.lock:
                o.codes[str(b.get("code") or secrets.token_hex(4))] = {"used": False}
            return self.send(200, {"ok": True, "codes": list(o.codes)})
        return self.err(404, "not_found", p)

    def enroll(self, b):
        o = self.office
        if b.get("surface") not in (None, SURFACE):
            return self.err(400, "invalid", f"surface {b.get('surface')} is not served; this office speaks surface {SURFACE}")
        code = str(b.get("code") or "")
        with o.lock:
            c = o.codes.get(code)
            if not c or c["used"]:
                return self.err(403, "bad_code", "the enrolment code is unknown, expired or already used")
            c["used"] = True
            did = o.next_id; o.next_id += 1
            name = (b.get("name") or "").strip() or f"{b.get('hostname') or 'a'}'s desk"
            if any(d["name"] == name and d["status"] == "active" for d in o.desks.values()):
                return self.err(409, "name_taken", f"a desk named {name!r} already exists")
            tok = "desk_" + secrets.token_hex(24)
            facts = {k: b.get(k) for k in ("hostname", "os_platform", "os_release", "variant", "cpu_cores", "memory_mb", "storage_gb", "machine_id") if b.get(k) is not None}
            desk = {"id": did, "name": name, "status": "active", "presence": "online", "last_seen_at": now(), "enrolled_at": now(),
                    "owner": {"member_id": 1, "email": "person@mock.office", "display_name": "Mock Person"},
                    "principal": b.get("principal"), "app_version": b.get("app_version"), "mcp_surface_version": b.get("mcp_surface_version"),
                    "facts": facts, "token": tok, "code": code}
            o.desks[did] = desk; o.tokens[tok] = did
        ans = o.answer(desk, self.base()); ans["token"] = tok
        return self.send(201, ans)

    def chat(self, b, desk):
        o = self.office
        model = b.get("model") or (o.models[0] if o.models else "office")
        if o.models and model not in o.models:
            return self.err(404, "model_not_found", f"no model {model!r} at this office")
        msgs = b.get("messages") or []
        last = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
        if isinstance(last, list):
            last = " ".join(x.get("text", "") for x in last if isinstance(x, dict))
        text = f"office reply to: {last}"
        n_in = sum(len(str(m.get("content") or "")) // 4 + 1 for m in msgs); n_out = len(text) // 4 + 1
        rid = "chatcmpl-" + secrets.token_hex(6)
        with o.lock:
            o.chats.append({"ts": now(), "desk_id": desk["id"], "model": model, "prompt": str(last)[:120], "stream": bool(b.get("stream"))})
        usage = {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out}
        if not b.get("stream"):
            return self.send(200, {"id": rid, "object": "chat.completion", "created": int(time.time()), "model": model,
                                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}], "usage": usage},
                             {"x-request-id": rid})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.send_header("x-request-id", rid); self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(obj):
            data = ("data: " + json.dumps(obj) + "\n\n").encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        head = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
        for piece in (text[:len(text) // 2], text[len(text) // 2:]):
            chunk(dict(head, choices=[{"index": 0, "delta": {"role": "assistant", "content": piece}, "finish_reason": None}]))
        chunk(dict(head, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]))
        chunk(dict(head, choices=[], usage=usage))
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode() + done + b"\r\n0\r\n\r\n")

    def mcp(self, path, b, desk):
        o = self.office
        server = path.rsplit("/", 1)[1]
        method, mid = b.get("method"), b.get("id")
        with o.lock:
            o.mcp.append({"ts": now(), "desk_id": desk["id"], "server": server, "method": method})
        if method == "initialize":
            res = {"protocolVersion": "2025-06-18", "serverInfo": {"name": f"mock-office-{server}", "version": "0"}, "capabilities": {"tools": {}}}
        elif method == "tools/list":
            res = {"tools": [{"name": "office.ping", "description": "answers pong, as the desk's owner", "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            res = {"content": [{"type": "text", "text": f"pong from {o.name} ({server}) for {desk['owner']['email']} at desk #{desk['id']}"}]}
        elif method == "notifications/initialized":
            self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers(); return
        else:
            return self.send(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})
        return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": res})


def main(argv=None):
    ap = argparse.ArgumentParser(description="mock Business OS office for desk tests")
    ap.add_argument("--port", type=int, default=18080); ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--code", action="append", default=[]); ap.add_argument("--name", default="Mock Office")
    ap.add_argument("--models", default="office-7b,office-embed"); ap.add_argument("--heartbeat-s", type=int, default=300)
    a = ap.parse_args(argv)
    Handler.office = Office(a.name, a.code or ["mock-code"], [m.strip() for m in a.models.split(",") if m.strip()], a.heartbeat_s)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    sys.stderr.write(f"mock-office: {a.name} on http://{a.host}:{a.port} codes={list(Handler.office.codes)} models={Handler.office.models}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
