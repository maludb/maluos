#!/usr/bin/env python3
"""Proof of the Memory MCP's desk path (db/193, maluos docs/phase13-slice4b-memory.md decision 7): a desk token's recall is
relayed to the office's desks memory query with the same bearer, the tool's scope mapped onto the office's scopes for the
desk, the office's refusal passed on. Runs without Postgres or the MCP venv (asyncpg is stubbed, PHP is a fake office):

    python3 bin/test_memory_mcp_desk.py
"""
import asyncio, json, os, sys, threading, types
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.modules.setdefault("asyncpg", types.SimpleNamespace(Pool=object, Connection=object, create_pool=None))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp"))
try:
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:                          # no MCP library on this host: the smallest stand-in (a tool is its function)
    class ToolError(Exception):
        pass

    class FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self, **kw):
            return lambda fn: fn
    for name in ("mcp", "mcp.server", "mcp.server.fastmcp", "mcp.server.fastmcp.exceptions"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["mcp.server.fastmcp"].FastMCP = FastMCP
    sys.modules["mcp.server.fastmcp.exceptions"].ToolError = ToolError
import db                                   # noqa: E402
import memory_server as ms                  # noqa: E402

SEEN = []


class Office(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        SEEN.append(("GET", self.path, self.headers.get("Authorization"), None))
        if self.path == "/api/v1/desks/memory":
            return self.send(200, {"ok": True, "self": "desk:41", "holders": [], "office": {"query": "x", "scopes": [
                {"scope": "self", "classification_max": "restricted", "label": "you"}, {"scope": "org", "classification_max": "internal", "label": "the organisation"},
                {"scope": "dept:7", "classification_max": "internal", "label": "Warehouse"}]}})
        self.send(404, {"error": {"code": "not_found"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SEEN.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path != "/api/v1/desks/memory/query":
            return self.send(404, {"error": {"code": "not_found"}})
        if "dept:9" in body.get("scopes", []):
            return self.send(403, {"error": {"code": "forbidden", "message": "dept:9 is not a scope of this desk"}})
        claims = [{"text": "Alex completed forklift training", "scope": s, "kind": "note", "sensitivity": "internal", "confidence": 0.9,
                   "observed_at": None, "recorded_at": "2026-11-01T00:00:00Z", "source": {"node": "coordinator"}, "writer": "member:1", "holder": "coordinator", "rank": 1}
                  for s in body["scopes"] if s != "self"]
        self.send(200, {"ok": True, "holder": "coordinator", "claims": claims, "scopes_read": body["scopes"], "count": len(claims)})


ok = fail = 0


def check(name, cond):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("  ok   " if cond else "  FAIL ") + name)


srv = HTTPServer(("127.0.0.1", 0), Office)
threading.Thread(target=srv.serve_forever, daemon=True).start()
db.ENV["APP_URL"] = f"http://127.0.0.1:{srv.server_port}"
db.request_token_scope.set("desk"); db.request_location_id.set(41); db.request_token.set("desk-token-xyz"); db.request_member_id.set(1); db.request_role.set("user")

r = json.loads(asyncio.run(ms.recall(ms.RecallIn(query="forklift training"))))
check("a desk's recall never touches the member path: the office is asked for the desk's scopes, then queried with the same bearer",
      [x[:2] for x in SEEN] == [("GET", "/api/v1/desks/memory"), ("POST", "/api/v1/desks/memory/query")] and all(x[2] == "Bearer desk-token-xyz" for x in SEEN))
check("no scope given: every scope the office publishes to the desk (self, org, dept:7), limit and class internal relayed",
      SEEN[1][3] == {"scopes": ["self", "org", "dept:7"], "query": "forklift training", "classification": "internal", "limit": 8} and r["searched"] == ["self", "org", "dept:7"])
check("the claims come back as results with their scope, kind, sensitivity, confidence and writer; the desk and the holder named",
      len(r["results"]) == 2 and r["results"][0]["from"] == "org" and r["results"][1]["from"] == "dept:7" and r["results"][0]["confidence"] == 0.9 and r["desk"] == 41 and r["holder"] == "coordinator")
SEEN.clear()
r = json.loads(asyncio.run(ms.recall(ms.RecallIn(query="forklift", scope="department", limit=3))))
check("scope department: the dept:N scopes alone, the limit as given", SEEN[1][3]["scopes"] == ["dept:7"] and SEEN[1][3]["limit"] == 3 and r["searched"] == ["dept:7"])
SEEN.clear()
r = json.loads(asyncio.run(ms.recall(ms.RecallIn(query="forklift", scope="self"))))
check("scope self: the owner's own namespace at the office", SEEN[1][3]["scopes"] == ["self"] and r["results"] == [])
check("desk_scopes: org alone; nothing of a kind the office does not publish",
      ms.desk_scopes([{"scope": "org"}], "org") == ["org"] and ms.desk_scopes([{"scope": "org"}], "department") == [] and ms.desk_scopes([{"scope": "org"}, {"x": 1}], None) == ["org"])
try:
    asyncio.run(ms.recall(ms.RecallIn(query="forklift", scope="dept")))
    check("a scope outside self/department/org is refused", False)
except ToolError as e:
    check("a scope outside self/department/org is refused", "scope must be" in str(e))
# the office's refusal is the tool's error, with its code and message
ms.desk_scopes_orig = ms.desk_scopes
ms.desk_scopes = lambda scopes, scope: ["dept:9"]
try:
    asyncio.run(ms.recall(ms.RecallIn(query="forklift")))
    check("the office's 403 forbidden is passed on", False)
except ToolError as e:
    check("the office's 403 forbidden is passed on with its code and message", "forbidden" in str(e) and "dept:9" in str(e))
ms.desk_scopes = ms.desk_scopes_orig
db.request_token_scope.set("mcp")
try:
    asyncio.run(ms.recall(ms.RecallIn(query="forklift")))
    check("a personal token takes the member path (which needs Postgres here)", False)
except Exception as e:
    check("a personal token takes the member path (which needs Postgres here: it fails on the pool, never on the relay)", not isinstance(e, ToolError) or "office" not in str(e))
srv.shutdown()
print(f"\n{ok + fail} checks, {fail} failed")
sys.exit(1 if fail else 0)
