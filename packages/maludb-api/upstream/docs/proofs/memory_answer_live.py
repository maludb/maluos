import base64, hashlib, json, os, re, secrets, sys, threading, time
"""Live proof of POST /v1/memory/answer (M1) on a SCRATCH tenant, with a fake OpenAI-compatible model on :8510.
Needs MA_SCRATCH_CREDS (a file of MA_DB / MA_USER / MA_PASSWORD lines for a scratch tenant) and writes a private auth store
beside itself (a new token each run). Nothing here touches a live service or store; it deletes what it made.
  MA_SCRATCH_CREDS=/path/creds.env python docs/proofs/memory_answer_live.py"""
HERE = os.path.dirname(os.path.abspath(__file__))
creds = dict(l.strip().split("=", 1) for l in open(os.environ["MA_SCRATCH_CREDS"]))
os.environ["MALUDB_AUTH_STORE"] = os.path.join(HERE, "auth.db"); os.environ.setdefault("MALUDB_PG_HOST", "127.0.0.1")
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from app.auth_store import AuthStore

calls = []
async def chat(request):
    b = await request.json(); user = b["messages"][-1]["content"]; calls.append(user)
    ev = re.search(r"\[1\][^\n]*\n(.+?)(\n\n|$)", user, re.S)
    text = ev.group(1).strip() if ev else ""
    quote = text[:60]
    if "FABRICATE" in user: quote = "the battery is covered for ten whole years"
    out = {"sufficient": "NOEVIDENCE" not in user, "answer_md": f"Per the terms [1]: {quote[:40]}...", "citations": [{"n": 1, "quote": quote}]}
    return JSONResponse({"id": "x", "choices": [{"message": {"content": json.dumps(out)}}], "usage": {"prompt_tokens": 321, "completion_tokens": 45}})
fake = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"])])
threading.Thread(target=lambda: uvicorn.run(fake, host="127.0.0.1", port=8510, log_level="error"), daemon=True).start(); time.sleep(1)

store = AuthStore(os.environ["MALUDB_AUTH_STORE"]); store.init_db()
raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
store.connection.execute("INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password) VALUES (?,?,?,?,?,?,?)",
    (hashlib.sha256(raw.encode()).hexdigest(), raw[:8], 1, "user", creds["MA_DB"], creds["MA_USER"], creds["MA_PASSWORD"])); store.connection.commit()
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, raise_server_exceptions=False); H = {"Authorization": "Bearer malu_" + raw}
fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -- " + str(detail)[:300])); (fails.append(name) if not ok else None)
def post(path, body, method="POST"): return c.request(method, path, json=body, headers=H)

NS = "kb:answer-proof"
r = post("/v1/memory/remember", {"namespace": NS, "subject": "Warranty", "verb": "covers", "text": "The battery is covered for 24 months from the date of purchase. Water damage is not covered by the warranty."})
check("remember a source under a subject", r.status_code in (200, 201), r.text); doc_ids = [r.json().get("document_id")] if r.status_code < 300 else []
r = post("/v1/memory/remember", {"namespace": NS, "subject": "Returns", "verb": "allows", "text": "Unopened items may be returned within 30 days for a full refund."})
doc_ids.append(r.json().get("document_id"))
r = post("/v1/llm/providers/openai", {"api_key": "scratch-key", "base_url": "http://127.0.0.1:8510/v1"}, "PUT"); check("a provider key pointing at the fake model", r.status_code == 200, r.text)
name = "gpt-4o"
r = post("/v1/llm/models/answer", {"model_name": name}, "PUT"); check("an 'answer' task model chosen", r.status_code == 200, f"{name} {r.status_code} {r.text}")

Q = {"namespace": NS, "min_similarity": -1.0}   # the dev embedder is hash-based: its cosines are noise, so the floor is opened
r = post("/v1/memory/answer", {**Q, "question": "How long is the Warranty on the battery?"}); j = r.json()
check("an answer is composed and verified", r.status_code == 200 and j.get("status") == "answered", f"{r.status_code} {r.text}")
check("evidence carries the document's title and chunk", j.get("evidence") and j["evidence"][0].get("chunk_id") and "document" in j["evidence"][0], j)
check("the citation is verified against its evidence", j.get("citations") and j["citations"][0]["verified"] is True, j.get("citations"))
check("the subject was found from the question", "Warranty" in j.get("subjects_tried", []), j.get("subjects_tried"))
check("usage is reported", j.get("usage") == {"input_tokens": 321, "output_tokens": 45, "calls": 1}, j.get("usage"))
check("the model saw numbered evidence and the rules", "[1]" in calls[-1] and "EVIDENCE" in calls[-1])
n = len(calls); r = post("/v1/memory/answer", {**Q, "question": "How long is the Warranty on the battery? FABRICATE"}); j = r.json()
check("a fabricated quote is withheld (unverified, 2 calls)", j.get("status") == "unverified" and j["answer_md"] is None and j["usage"]["calls"] == 2 and len(calls) == n + 2, j)
n = len(calls); r = post("/v1/memory/answer", {**Q, "question": "What is the plumbing of Xylophone zebras?"}); j = r.json()
check("no subject known: no_evidence and no model call", j.get("status") == "no_evidence" and len(calls) == n and j["usage"]["calls"] == 0, j)
r = post("/v1/memory/answer", {**Q, "question": "How long is the Warranty? NOEVIDENCE"}); check("a model that says insufficient: no_evidence", r.json().get("status") == "no_evidence", r.text)
r = post("/v1/memory/answer", {**Q, "question": "Warranty?", "project": "no-such-project"}); check("an unknown project is a 404", r.status_code == 404, f"{r.status_code} {r.text}")
r = post("/v1/memory/answer", {"namespace": NS, "question": "How long is the Warranty on the battery?", "min_similarity": 1.0}); check("a similarity floor above every hit: no_evidence", r.json().get("status") == "no_evidence", r.text)
subj = {x["label"]: x["id"] for x in c.get("/v1/subjects?limit=200", headers=H).json().get("subjects", []) if x["label"] in ("Warranty", "Returns")}
check("both subjects exist", set(subj) == {"Warranty", "Returns"}, subj)
projects = {}
for nm, sub in (("proof-warranty-area", "Warranty"), ("proof-returns-area", "Returns")):
    pid = post("/v1/projects", {"name": nm}).json()["project"]["id"]; projects[nm] = pid
    # Known defect (reported with M1): DELETE /v1/projects/{id} leaves the project's subject links behind, and a new project
    # can reuse the id and inherit them. Clear any such stale link so the proof starts clean and can be re-run.
    for stale in c.get(f"/v1/projects/{pid}", headers=H).json()["project"]["subjects"]:
        c.delete(f"/v1/projects/{pid}/subjects/{stale['id']}", headers=H)
    lr = post(f"/v1/projects/{pid}/subjects", {"subject_id": subj[sub]})
    check(f"project {nm} links {sub}", lr.status_code in (200, 201), f"{lr.status_code} {lr.text}")
both = "Warranty and Returns: how long is the battery Warranty?"
j = post("/v1/memory/answer", {**Q, "question": both, "project": "proof-warranty-area"}).json()
check("a project confines retrieval to its own subjects", j.get("subjects_tried") == ["Warranty"] and j.get("status") == "answered", j)
j = post("/v1/memory/answer", {**Q, "question": both, "project": projects["proof-returns-area"]}).json()
check("another project (by id) cannot see the warranty text", j.get("subjects_tried") == ["Returns"] and all(e["subject"] == "Returns" for e in j["evidence"]), j)
for pid in projects.values():
    for linked in c.get(f"/v1/projects/{pid}", headers=H).json()["project"]["subjects"]:
        c.delete(f"/v1/projects/{pid}/subjects/{linked['id']}", headers=H)      # unlink first: DELETE project would orphan them
    c.delete(f"/v1/projects/{pid}", headers=H)
for d in doc_ids:
    if d: c.delete(f"/v1/documents/{d}", headers=H)
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
