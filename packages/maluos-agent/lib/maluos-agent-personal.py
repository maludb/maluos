#!/usr/bin/python3
"""The person's own agent (Phase 13 slice 2, decision 8): made by `maluctl agent create me --personal`.

It answers its owner's questions through the gateway (the demo agent's loop), and when a task says
"ask AGENT …" it sends that to AGENT in the estate's directory as the person: an envelope whose originator is
the owner and whose sender is this agent (the chain [owner, agent:me]), signed with the owner's desk key, which
reaches it use-only through a delegation the Agents app renews weekly, like the desk token. The answer comes
back with its provenance. Nothing about it is special: an ordinary agent built from the parts that exist.
"""
import http.client, json, os, re, socket, sys, time

sys.path.insert(0, "/usr/lib/maluos")
import maluos_agent_tasks as T

SOCK = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")
MODEL = os.environ.get("MALUOS_DEMO_MODEL", "fast")
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
ASK = re.compile(r"^\s*ask\s+([a-z][a-z0-9-]{0,30})\s*(?:to\s+|:\s*)?(.*)$", re.S | re.I)


class U(http.client.HTTPConnection):
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(SOCK); self.sock = s


def ask_gateway(prompt):
    c = U("gateway", timeout=120)
    headers = {"Content-Type": "application/json", "X-MaluOS-Task": f"personal:{os.environ.get('MALUOS_AGENT', 'me')}", **T.gateway_headers()}
    c.request("POST", "/v1/chat/completions", body=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}]}).encode(), headers=headers)
    r = c.getresponse(); body = json.loads(r.read()); c.close()
    if r.status != 200:
        raise RuntimeError(json.dumps(body)[:300])
    T.record_model_call(dict(r.getheaders()))
    return body["choices"][0]["message"]["content"]


def office():
    import yaml
    with open(OFFICE_CONF) as fh:
        return yaml.safe_load(fh) or {}


def vault_value(name):
    from maluos_vault_client import Vault
    return Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value(name, "use", purpose=f"personal agent: {name}")["value"]


def ask_agent(name, text, task):
    """A task to an estate agent as the person: the directory, the envelope, the send, the answer with provenance."""
    import urllib.request
    import maluos_estate.envelope as E
    conf = office()
    token = vault_value("office-desk-token")
    key = vault_value("office-desk-key")
    ep = (conf.get("endpoints") or {}).get("agents")
    if not ep:
        raise RuntimeError("the office publishes no agents to this desk")
    req = urllib.request.Request(ep, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        agents = (json.loads(r.read() or b"{}").get("agents") or [])
    target = next((a for a in agents if (a.get("agent") or a.get("name")) == name and a.get("tasks")), None)
    if not target:
        raise RuntimeError(f"no agent {name!r} with a task interface in the directory ({', '.join(a.get('agent') or a.get('name') or '' for a in agents) or 'empty'})")
    owner = conf.get("owner") or {}
    me = os.environ.get("MALUOS_PRINCIPAL") or f"agent:{os.environ.get('MALUOS_AGENT', 'me')}"
    node = f"desk:{(conf.get('desk') or {}).get('id')}"
    originator = {"principal": os.environ.get("MALUOS_AGENT_OWNER") or owner.get("principal") or "user:?", "kind": "human", "node": node, "member_id": owner.get("member_id")}
    now = E.utc()
    env = E.make(originator, {"principal": me, "node": node}, {"agent": target.get("agent") or target.get("name"), "node": target.get("node_ref")}, text[:200],
                 {"scopes": [], "classification": "internal", "budget": {"usd": 0.5, "calls": 20}},
                 chain=[{"principal": originator["principal"], "node": node, "ts": now, "task_id": None}, {"principal": me, "node": node, "ts": now, "task_id": task.get("id")}])
    env = E.sign(env, node, key)
    task["progress"](f"asking {name} on {target.get('node') or target.get('node_ref')}…\n")
    c = T.Client(target["tasks"], token=token)
    t = c.send(text, wait=True, timeout=170, envelope=env)
    prov = t.get("provenance") or {}
    models = prov.get("models") or []
    line = f"\n\n— from {name} on {prov.get('node') or target.get('node_ref')} · {len(models)} model call{'s' if len(models) != 1 else ''} · envelope {env['id']} · task {t.get('id')}"
    if t.get("state") != "completed":
        return f"{name} did not answer: {t.get('state')} {t.get('error') or t.get('reason') or ''}".strip() + line
    return ((t.get("output") or {}).get("text") or "") + line


def handle(t):
    m = ASK.match(t["text"])
    if m:
        return ask_agent(m.group(1).lower(), m.group(2).strip() or "hello", t)
    t["progress"](f"working on: {t['text'][:80]}\n")
    return ask_gateway(t["text"])


print(f"personal agent {os.environ.get('MALUOS_AGENT')} as {os.environ.get('MALUOS_PRINCIPAL')} for {os.environ.get('MALUOS_AGENT_OWNER')}", flush=True)
if T.serve(handle, card={"description": "your own agent: answers you, and asks other agents in the estate on your behalf (\"ask NAME …\")", "capabilities": ["personal", "chat"]}):
    print(f"tasks: serving {T.socket_path()}", flush=True)
while True:
    time.sleep(3600)
