#!/usr/bin/python3
"""A demonstration agent: asks the gateway one question through the socket
(as itself: the unit's user is its identity), logs the answer, then waits.
Used by the image boot test; a real agent replaces this with its loop."""
import http.client, json, os, socket, sys, time

SOCK = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")
MODEL = os.environ.get("MALUOS_DEMO_MODEL", "fast")


class U(http.client.HTTPConnection):
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(SOCK); self.sock = s


def ask(prompt):
    c = U("gateway", timeout=120)
    c.request("POST", "/v1/chat/completions", body=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}]}).encode(),
              headers={"Content-Type": "application/json", "X-MaluOS-Task": f"demo:{os.environ.get('MALUOS_AGENT', 'agent')}"})
    r = c.getresponse(); body = json.loads(r.read()); c.close()
    if r.status != 200:
        raise RuntimeError(json.dumps(body)[:300])
    return body["choices"][0]["message"]["content"]


print(f"demo agent {os.environ.get('MALUOS_AGENT')} as {os.environ.get('MALUOS_PRINCIPAL')} via {SOCK}", flush=True)
# Tasks from the owner (the Agents app, maluctl agent send): each one is a question to the gateway (Phase 12 slice 8).
try:
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_agent_tasks
    if maluos_agent_tasks.serve(lambda t: ask(t["text"]), card={"description": "the demonstration agent: answers each task through the gateway", "capabilities": ["chat"]}):
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
