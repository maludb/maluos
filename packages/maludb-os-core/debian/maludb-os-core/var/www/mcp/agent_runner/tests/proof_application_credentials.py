"""K24 proof (db/171) — an application's credential at the ledger proxy, end to end, on a SCRATCH database.

Not part of the unit suite: it needs maludb_os_k24_scratch (a schema-only copy), a login role that holds only app_runner's
privileges, and a minted credential. Run (see docs/build-specs/kernel-application-model-credentials.md):

  APPM_KEY=appm_… RUNNER_DB_NAME=maludb_os_k24_scratch RUNNER_DB_USER=k24_runner_scratch RUNNER_DB_PASSWORD=… \
  PROXY_KEY_SECRET=<32+ chars> RUNNER_ENV_FILE=/nonexistent mcp/venv/bin/python mcp/agent_runner/tests/proof_application_credentials.py
"""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import httpx, uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from agent_runner import ledger_proxy, store

KEY = os.environ["APPM_KEY"]
seen = []
async def chat(request):
    b = await request.json(); seen.append(("chat", b.get("model"), request.headers.get("authorization")))
    return JSONResponse({"id": "c1", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
async def emb(request):
    b = await request.json(); seen.append(("emb", b.get("model"), request.headers.get("authorization")))
    return JSONResponse({"data": [{"embedding": [0.1]}], "usage": {"prompt_tokens": 2000, "total_tokens": 2000}})
fake = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"]), Route("/v1/embeddings", emb, methods=["POST"])])
threading.Thread(target=lambda: uvicorn.run(fake, host="127.0.0.1", port=8509, log_level="error"), daemon=True).start()
time.sleep(1.0)

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {detail}"))
    if not ok: fails.append(name)

async def ledger(sql, *a):
    p = await store.pool()
    async with p.acquire() as con: return await con.fetch(sql, *a)

async def main():
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=ledger_proxy.app), base_url="http://proxy")
    h = {"authorization": "Bearer " + KEY}
    body = lambda m: {"model": m, "messages": [{"role": "user", "content": "hi"}]}
    r = await c.post("/openai/v1/chat/completions", json=body("scratch-chat-1")); check("no key is refused", r.status_code == 401, r.text)
    r = await c.post("/openai/v1/chat/completions", json=body("scratch-chat-1"), headers={"authorization": "Bearer appm_" + "0" * 48}); check("an unknown credential is refused", r.status_code == 401, r.text)
    r = await c.get("/openai/v1/models", headers=h); ids = sorted(m["id"] for m in r.json().get("data", []))
    check("the model list is the allowed models", r.status_code == 200 and ids == ["scratch-chat-1", "scratch-embed-1"], f"{r.status_code} {ids}")
    r = await c.post("/openai/v1/embeddings", json={"model": "scratch-embed-1", "input": "x"}, headers=h); check("an embedding is forwarded", r.status_code == 200, r.text)
    r = await c.post("/openai/v1/chat/completions", json=body("scratch-chat-1"), headers=h); check("a chat call by provider id is forwarded", r.status_code == 200, r.text)
    r = await c.post("/openai/v1/chat/completions", json=body("scratch:chat"), headers=h); check("a chat call by registry key is forwarded", r.status_code == 200, r.text)
    check("the upstream saw the provider's model id and not the credential", [s[1] for s in seen] == ["scratch-embed-1", "scratch-chat-1", "scratch-chat-1"] and all(KEY not in (s[2] or "") for s in seen), str(seen))
    r = await c.post("/openai/v1/chat/completions", json=body("scratch-other-1"), headers=h); check("a model outside the allowlist is refused (403)", r.status_code == 403, f"{r.status_code} {r.text}")
    n = len(seen); r = await c.post("/openai/v1/chat/completions", json=body("scratch-chat-1"), headers=h)
    check("the monthly cap stops the next call (402), nothing forwarded", r.status_code == 402 and len(seen) == n, f"{r.status_code} {r.text}")
    rows = await ledger("SELECT * FROM prompt_ledger WHERE application_id IS NOT NULL ORDER BY id")
    kinds = [(x["call_kind"], x["status"]) for x in rows]
    check("four ledger rows: embedding, two chats, one refusal", kinds == [("embedding", "ok"), ("messages", "ok"), ("messages", "ok"), ("messages", "refused")], str(kinds))
    ok = rows[0]
    check("the row is the application's: no agent, no run, harness application, the minter acting",
          ok["agent_member_id"] is None and ok["agent_run_id"] is None and ok["harness"] == "application" and ok["acting_member_id"] == 1, str(dict(ok)))
    check("cost reconciles to the registry prices (embed 2000 x 0.1, chat 1000 x 2 + 500 x 10, per million)",
          [str(x["cost"]) for x in rows[:3]] == ["0.000200", "0.007000", "0.007000"], str([str(x["cost"]) for x in rows]))
    pay = await ledger("SELECT count(*) n FROM prompt_payloads WHERE ledger_id = ANY($1::bigint[])", [x["id"] for x in rows])
    check("every row has its payload", pay[0]["n"] == 4, str(pay[0]["n"]))
    spent = await store.application_month_cost(rows[0]["application_id"]); check("the month's spend by the application is the three paid calls", str(spent) == "0.014200", str(spent))
    print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
asyncio.run(main())
