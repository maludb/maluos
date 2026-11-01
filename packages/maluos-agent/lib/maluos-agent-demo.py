#!/usr/bin/python3
"""A demonstration agent: asks the gateway one question through the socket
(as itself: the unit's user is its identity), logs the answer, then waits.
Used by the image boot test; a real agent replaces this with its loop.
A task "what do we know about X" or "recall X" (Phase 13 slice 4) is answered from memory instead: the face's
/v1/recall over the estate, with the task's envelope, one line per claim."""
import http.client, json, os, re, socket, sys, time

SOCK = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")
MODEL = os.environ.get("MALUOS_DEMO_MODEL", "fast")
RECALL = re.compile(r"^\s*(?:what do we know about|recall)\s+(.+?)\s*\??\s*$", re.S | re.I)


def recall_answer(tasks, subject):
    """The memory face's claims about a subject as a short text: one line per claim, or why there is none."""
    r = tasks.memory_recall(subject)
    if not r.get("ok"):
        return f"memory is not available: {(r.get('error') or {}).get('message') or (r.get('error') or {}).get('code') or 'unknown error'}"
    claims = r.get("claims") or []
    if not claims:
        return f"nothing in memory about {subject}" + (f" (asked {', '.join(r['holders'])})" if r.get("holders") else "")
    lines = [f"- {c.get('text') or ''} ({c.get('scope')}, {c.get('sensitivity')}, from {c.get('holder') or 'this host'})" for c in claims]
    failed = r.get("holders_failed") or []
    if failed:
        lines.append(f"(no answer from {', '.join(str(f.get('holder')) for f in failed)})")
    return "\n".join(lines)


class U(http.client.HTTPConnection):
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(SOCK); self.sock = s


def ask(prompt):
    c = U("gateway", timeout=120)
    headers = {"Content-Type": "application/json", "X-MaluOS-Task": f"demo:{os.environ.get('MALUOS_AGENT', 'agent')}"}
    if TASKS is not None:
        headers.update(TASKS.gateway_headers())          # slice 2: an estate task's classification and envelope id reach the ledger
    c.request("POST", "/v1/chat/completions", body=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}]}).encode(), headers=headers)
    r = c.getresponse(); body = json.loads(r.read()); c.close()
    if r.status != 200:
        raise RuntimeError(json.dumps(body)[:300])
    if TASKS is not None:
        TASKS.record_model_call(dict(r.getheaders()))    # the provenance's models list
    return body["choices"][0]["message"]["content"]


TASKS = None
try:
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_agent_tasks as TASKS
except Exception:
    TASKS = None


print(f"demo agent {os.environ.get('MALUOS_AGENT')} as {os.environ.get('MALUOS_PRINCIPAL')} via {SOCK}", flush=True)
# Tasks from the owner (the Agents app, maluctl agent send): each one is a question to the gateway (Phase 12 slice 8).
try:
    if TASKS is None:
        raise RuntimeError("maluos_agent_tasks not importable")
    maluos_agent_tasks = TASKS
    def handle(t):
        m = RECALL.match(t["text"])
        if m:                                              # slice 4: a question to memory, not to the model
            t["progress"](f"recalling: {m.group(1)[:80]}\n")
            return recall_answer(TASKS, m.group(1))
        # Slice 9: partial text first (the client shows it while the gateway answers), then the answer.
        t["progress"](f"working on: {t['text'][:80]}\n")
        return ask(t["text"])
    if maluos_agent_tasks.serve(handle, card={"description": "the demonstration agent: answers each task through the gateway; \"what do we know about X\" from memory", "capabilities": ["chat", "memory"]}):
        print(f"tasks: serving {maluos_agent_tasks.socket_path()}", flush=True)
except Exception as e:
    print(f"tasks: not served ({e.__class__.__name__}: {str(e)[:120]})", flush=True)
for attempt in range(30):
    try:
        print("answer: " + ask("Say hello from the demo agent."), flush=True); break
    except Exception as e:
        print(f"gateway not ready ({e.__class__.__name__}: {str(e)[:120]}); retrying", flush=True); time.sleep(5)
while True:
    time.sleep(3600)
