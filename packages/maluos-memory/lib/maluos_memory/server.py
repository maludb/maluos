"""The memory face (docs/phase13-slice4-memory.md): one HTTP service on two listeners.

The Unix socket (/run/maluos/memory.sock) serves local principals, identified by the peer's uid through the vault's
identities map: recall (this host's memories, and with `estate` the holders the directory publishes), remember,
forget, the facts the heartbeat carries, usage, sync, status. The overlay listener (port 11437 when exposed) serves
the estate: a query carries a slice 2 envelope; the face verifies it against the peers cache (each peer's public key
and the scopes the policy lets it read here), intersects that with what this host shares (the guest principal's
grants and ceiling), binds the engine to the guest principal narrowed to the scopes asked, and answers claims.
Every query answered or asked is one ledger row: the scopes and the counts, never the text."""
import datetime, http.server, json, os, pwd, socket, socketserver, struct, sys, threading, time, urllib.request

from . import VERSION, API_VERSION, DEFAULT_PORT, SENSITIVITY
from .engine import Engine, EngineError, Config, utc, shareable, KINDS, Embedder

ESTATE_CONF = os.environ.get("MALUOS_ESTATE_CONF", "/etc/maluos/estate.yaml")
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
FILES = {"node": (os.environ.get("MALUOS_ESTATE_MEMORY", "/run/maluos/estate/memory.json"), os.environ.get("MALUOS_ESTATE_MEMORY_PEERS", "/run/maluos/estate/memory-peers.json")),
         "desk": (os.environ.get("MALUOS_OFFICE_MEMORY", "/run/maluos/office/memory.json"), os.environ.get("MALUOS_OFFICE_MEMORY_PEERS", "/run/maluos/office/memory-peers.json"))}
KEYS_CACHE = os.environ.get("MALUOS_ESTATE_KEYS", "/run/maluos/estate/keys.json")
STATE_DIR = os.environ.get("MALUOS_MEMORY_STATE", "/var/lib/maluos/memory")
SYNC_STATE = os.path.join(STATE_DIR, "sync.json")
VAULT_SOCKET = os.environ.get("MALUOS_VAULT_SOCKET", "/run/maluos/vault.sock")
QUERY_MAX = 1000
LIMIT_MAX = 50
LIMIT_DEFAULT = 12
ENVELOPE_LIFE_S = 120


def log(msg):
    sys.stderr.write(f"maluos-memory: {msg}\n"); sys.stderr.flush()


def _rank(s):
    return SENSITIVITY.get(s or "internal", 1)


def _yaml(path):
    try:
        import yaml
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def overlay_address():
    for p in (ESTATE_CONF, OFFICE_CONF):
        a = (_yaml(p).get("overlay") or {}).get("address")
        if a:
            return a
    return None


def memberships():
    """This host's memberships: a node (estate.yaml) and/or a desk (office.yaml), each with its node ref and the vault ref of
    its signing key (the face holds a read grant on it: `maluctl memory keys`)."""
    out = {}
    e = _yaml(ESTATE_CONF)
    if (e.get("node") or {}).get("id"):
        out["node"] = {"source": "node", "node": f"{e['node'].get('kind', 'server')}:{e['node']['id']}", "principal": e.get("principal"),
                       "key": f"{e.get('principal')}/estate-node-key", "url": e.get("url")}
    o = _yaml(OFFICE_CONF)
    if (o.get("desk") or {}).get("id"):
        owner = (o.get("owner") or {}).get("principal")
        out["desk"] = {"source": "desk", "node": f"desk:{o['desk']['id']}", "principal": owner, "key": f"{owner}/office-desk-key", "url": o.get("url")}
    return out


def _trusted(path, source):
    """A node's cache is the daemon's; a desk's must be root's or the desk owner's (as the gateway trusts the inference caches)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if source == "node" or st.st_uid == 0:
        return True
    try:
        owner = ((_yaml(OFFICE_CONF)).get("owner") or {}).get("login")
        return bool(owner) and pwd.getpwnam(owner).pw_uid == st.st_uid
    except Exception:
        return False


def read_caches(idx):
    """Every trusted cache of a kind (0 the holders, 1 the peers), the node's first: [(data, source, mtime)]."""
    out = []
    for source in ("node", "desk"):
        path = FILES[source][idx]
        if not os.path.exists(path) or not _trusted(path, source):
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                out.append((data, source, os.stat(path).st_mtime))
        except (OSError, ValueError) as e:
            log(f"cache {path}: {e.__class__.__name__}: {str(e)[:80]}")
    return out


def process_ref(pid):
    comm = unit = None
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                parts = [p for p in line.strip().split(":", 2)[-1].split("/") if p]
                if parts:
                    unit = parts[-1]
    except OSError:
        pass
    return f"{comm}@{unit}" if comm and unit else comm


class Peers:
    """The members allowed to ask this host, scope by scope, with their keys (the memory-peers caches, both memberships)."""

    def __init__(self):
        self.by_node, self.stamp, self.version = {}, None, None

    def load(self):
        found = read_caches(1)
        stamp = tuple((src, mt) for _, src, mt in found)
        if stamp == self.stamp:
            return
        by = {}
        for data, source, _ in found:
            for p in data.get("peers") or []:
                if not isinstance(p, dict) or not p.get("node") or p["node"] in by:
                    continue
                by[p["node"]] = {"node": p["node"], "name": p.get("name"), "address": p.get("address"), "public_key": p.get("public_key"), "source": source,
                                 "scopes": {s["scope"]: s for s in (p.get("scopes") or []) if isinstance(s, dict) and s.get("scope")}}
        self.by_node, self.stamp = by, stamp
        self.version = found[0][0].get("version") if found else None
        if found:
            log(f"peers: {len(by)} member(s) may ask this host (version {self.version}, {'+'.join(s for _, s, _ in found)})")

    def get(self, node):
        self.load()
        return self.by_node.get(node)


class Holders:
    """The holders the directory publishes to this host's memberships (the memory caches), each with the membership it came from.
    A host with two memberships (a desktop that is a desk and a node) is published to itself through the other one: it never
    asks, or replicates from, its own identities (what it holds is local already) unless memory.yaml says `ask_self: true`
    (the one-host tests, where the face is its own peer over the overlay). An own identity is then asked at this face's
    own listener: the directory publishes a desk at the overlay address the office allocated to the desk's key, which a host
    that is also a node never carries (its interface is the node's)."""

    def __init__(self, cfg=None, bound=None):
        self.cfg = cfg
        self.bound = bound          # callable → (address, port) of the face's TCP listener, or None

    def load(self):
        out = []
        seen = set()
        caches = read_caches(0)
        ask_self = bool(self.cfg and self.cfg["ask_self"])
        own = {m["node"] for m in memberships().values()} | {d.get("self") for d, _, _ in caches if d.get("self")}
        for data, source, _ in caches:
            for h in data.get("holders") or []:
                if not isinstance(h, dict) or not h.get("node") or not h.get("address") or h["node"] in seen or (h["node"] in own and not ask_self):
                    continue
                seen.add(h["node"])
                address, port = h["address"], int(h.get("port") or DEFAULT_PORT)
                if h["node"] in own:
                    b = self.bound() if self.bound else None
                    if b:
                        address, port = b[0], int(b[1])
                out.append({"node": h["node"], "name": h.get("name"), "address": address, "port": port, "source": source,
                            "scopes": {s["scope"]: s for s in (h.get("scopes") or []) if isinstance(s, dict) and s.get("scope")}})
        return out


class Caller:
    def __init__(self, pid, uid, gid, identities):
        self.pid, self.uid, self.gid = pid, uid, gid
        try:
            self.user = pwd.getpwuid(uid).pw_name
        except KeyError:
            self.user = str(uid)
        self.operator = uid == 0
        self.ref = identities.get(self.user, f"user:{self.user}")
        self.process_ref = process_ref(pid)


class Face:
    def __init__(self, cfg):
        self.cfg = cfg
        self.embedder = Embedder(cfg)
        self.engine = Engine(cfg, self.embedder)
        self.peers = Peers()
        self.holders = Holders(cfg, bound=lambda: self.tcp_bound)
        self.started = utc()
        self.tcp, self.tcp_thread, self.tcp_bound = None, None, None
        self._keys, self._key_lock = {}, threading.Lock()
        self.nonces = None
        self.lock = threading.Lock()

    # -- envelopes
    def envelope_module(self):
        from maluos_estate import envelope as E
        if self.nonces is None:
            self.nonces = E.Nonces()
        return E

    def node_ref(self, source=None):
        m = memberships()
        if source and source in m:
            return m[source]["node"]
        return (m.get("node") or m.get("desk") or {}).get("node") or "local"

    def private_key(self, membership):
        """The membership's signing key from the vault (a read grant to user:maluos-memory), cached."""
        ref = membership["key"]
        with self._key_lock:
            if ref in self._keys:
                return self._keys[ref]
        from maluos_vault_client import Vault
        text = Vault(VAULT_SOCKET).value(ref, "read", purpose="memory envelope")["value"]
        with self._key_lock:
            self._keys[ref] = text
        return text

    def self_envelope(self, membership, originator_ref, target_node, scopes, classification):
        E = self.envelope_module()
        kind = "agent" if originator_ref.startswith("agent:") else ("service" if ":" in originator_ref and originator_ref.split(":")[0] in ("host", "service", "estate") else "human")
        me = {"principal": originator_ref, "node": membership["node"]}
        env = E.make(dict(me, kind=kind), me, {"node": target_node}, "memory",
                     {"scopes": [f"{s}:read" for s in sorted(scopes)], "classification": classification, "budget": {"usd": 0, "calls": 0}}, life_s=ENVELOPE_LIFE_S)
        try:
            return E.sign(env, membership["node"], self.private_key(membership))
        except Exception:
            with self._key_lock:
                self._keys.pop(membership["key"], None)
            raise

    # -- the estate's gate
    def gate(self, body, replicate=False):
        """Verify a peer's request: the envelope, the peer, the authority, this host's shared scopes and ceilings. Returns
        (envelope, peer, scopes, classification) or raises EngineError."""
        E = self.envelope_module()
        env = body.get("envelope")
        if not isinstance(env, dict):
            raise EngineError(401, "bad_envelope", "a query carries an envelope")
        sender = ((env.get("sender") or {}).get("node")) or ((env.get("sig") or {}).get("key"))
        peer = self.peers.get(sender) if isinstance(sender, str) else None
        if not peer:
            raise EngineError(403, "forbidden", f"{sender} is not a peer of this host (the peers cache)")
        table = {}
        if peer.get("public_key"):
            table[sender] = peer["public_key"]
        else:
            table = E.Keys(KEYS_CACHE).table()
        ok, reason, msg = E.verify(env, table, sender, self.nonces)
        if not ok:
            raise EngineError(409 if reason == "replay" else 401, reason, msg)
        scopes = body.get("scopes") if replicate is False else [body.get("scope")]
        if not isinstance(scopes, list) or not scopes or not all(shareable(s) for s in scopes) or len(scopes) > 32:
            raise EngineError(400, "invalid", "scopes are org or dept:N, at most 32")
        authority = {}
        for s in (env.get("authority") or {}).get("scopes") or []:
            if isinstance(s, str):
                base, _, level = s.rpartition(":") if s.endswith((":read", ":write")) else (s, "", "read")
                authority[base] = level or "read"
        for s in scopes:
            if s not in authority:
                raise EngineError(403, "forbidden", f"the envelope's authority does not cover {s}")
        cls = body.get("classification") or "internal"
        if cls not in SENSITIVITY:
            raise EngineError(400, "invalid", "classification is public, internal, restricted or prohibited")
        ecls = (env.get("authority") or {}).get("classification") or "internal"
        if _rank(cls) > _rank(ecls):
            raise EngineError(403, "classification", f"the envelope's classification is {ecls}")
        guest = self.engine.guest()
        if not guest["present"] or not guest.get("enabled", True):
            raise EngineError(503, "not_shared", "this host shares no memory (no guest principal)")
        for s in scopes:
            if s not in guest["shared"]:
                raise EngineError(403, "forbidden", f"this host does not share {s}")
            ps = peer["scopes"].get(s)
            if not ps:
                raise EngineError(403, "forbidden", f"{sender} may not read {s} from this host")
            if replicate and not ps.get("replicate"):
                raise EngineError(403, "forbidden", f"{sender} may not replicate {s} from this host")
            ceiling = min(_rank(ps.get("classification_max")), _rank(guest["max_classification"]))
            if _rank(cls) > ceiling:
                raise EngineError(403, "classification", f"the ceiling on {s} for {sender} is {[k for k, v in SENSITIVITY.items() if v == ceiling][0]}")
        return env, peer, scopes, cls, guest

    def estate_query(self, body):
        env, peer, scopes, cls, guest = self.gate(body)
        query = body.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > QUERY_MAX:
            raise EngineError(400, "invalid", f"query is 1 to {QUERY_MAX} characters")
        limit = max(1, min(LIMIT_MAX, int(body.get("limit") or LIMIT_DEFAULT)))
        holder = self.node_ref(peer["source"])
        claims = self.engine.recall(guest["principal"], scopes, query, limit, cls, holder=holder, detail=False)
        read = sorted({c["scope"] for c in claims})
        chain = env.get("chain") or []
        task = (chain[-1].get("task_id") if chain and isinstance(chain[-1], dict) else None)
        self.engine.ledger("memory.query", principal_ref=guest["principal"], purpose="estate", task_ref=task,
                           route={"holder": holder, "peer": peer["node"]},
                           detail={"envelope": env.get("id"), "task_id": task, "originator": (env.get("originator") or {}).get("principal"), "peer": peer["node"],
                                   "scopes": scopes, "scopes_read": read, "classification": cls, "count": len(claims)})
        return {"ok": True, "holder": holder, "claims": claims, "scopes_asked": scopes, "scopes_read": read, "count": len(claims), "truncated": len(claims) >= limit, "api_version": API_VERSION}

    def estate_summaries(self, body):
        env, peer, scopes, cls, guest = self.gate(body, replicate=True)
        scope = scopes[0]
        since = body.get("since") if isinstance(body.get("since"), str) and body.get("since") else None
        holder = self.node_ref(peer["source"])
        items, gone = self.engine.summaries(guest["principal"], scope, since=since, limit=int(body.get("limit") or 200), holder=holder)
        items = [c for c in items if _rank(c.get("sensitivity")) <= _rank(cls)]
        self.engine.ledger("memory.summaries", principal_ref=guest["principal"], purpose="estate", route={"holder": holder, "peer": peer["node"]},
                           detail={"envelope": env.get("id"), "peer": peer["node"], "scope": scope, "since": since, "count": len(items), "gone": len(gone)})
        return {"ok": True, "holder": holder, "scope": scope, "summaries": items, "gone": gone, "version": utc(), "count": len(items)}

    # -- the local side
    def resolve(self, caller, body):
        """The principal a local request runs as: the caller's, or --as an agent the caller owns (an operator may be anyone)."""
        ref = body.get("as") if isinstance(body.get("as"), str) and body.get("as") else caller.ref
        if ref != caller.ref and not caller.operator and not self.engine.owns_agent(caller.ref, ref):
            raise EngineError(403, "not_owner", f"{caller.ref} may not act as {ref}")
        p = self.engine.principal(ref)
        if not p:
            raise EngineError(403, "unknown_principal", f"no principal {ref} on this host")
        if not p["enabled"]:
            raise EngineError(403, "principal_disabled", f"principal {ref} is disabled")
        return p

    def local_recall(self, caller, body):
        p = self.resolve(caller, body)
        query = body.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > QUERY_MAX:
            raise EngineError(400, "invalid", f"query is 1 to {QUERY_MAX} characters")
        detail = bool(body.get("detail"))
        scopes = body.get("scopes") or (p["write"] if detail and not caller.operator else p["read"])
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise EngineError(400, "invalid", "scopes is a list")
        for s in scopes:
            if s not in p["read"]:
                raise EngineError(403, "forbidden", f"{p['ref']} may not read {s}")
        cls = body.get("classification") or "internal"
        if cls not in SENSITIVITY:
            raise EngineError(400, "invalid", "classification is public, internal, restricted or prohibited")
        limit = max(1, min(LIMIT_MAX, int(body.get("limit") or LIMIT_DEFAULT)))
        if detail and not caller.operator and not all(s in p["write"] for s in scopes):
            raise EngineError(403, "forbidden", "detail is for a principal that may write every scope asked")
        kinds = body.get("kinds") if isinstance(body.get("kinds"), list) else None
        holder = self.node_ref()
        claims = self.engine.recall(p["ref"], scopes, query, limit, cls, holder=holder, detail=detail, kinds=kinds)
        for c in claims:
            c["local"] = True
        out = {"ok": True, "principal": p["ref"], "scopes": sorted(set(scopes)), "claims": claims, "holders": [], "holders_failed": [], "count": len(claims), "scopes_read": sorted({c["scope"] for c in claims})}
        if body.get("estate"):
            env = body.get("envelope") if isinstance(body.get("envelope"), dict) else None     # a task's envelope travels as it is (the holder verifies its signer)
            remote, asked, failed = self.fanout(p["ref"], [s for s in scopes if shareable(s)], query, limit, cls, envelope=env)
            out["claims"] = sorted(claims + remote, key=lambda c: (int(c.get("rank") or 999), 0 if c.get("local") else 1))[: limit * 2]
            for i, c in enumerate(out["claims"]):
                c["rank"] = i + 1
            out["holders"], out["holders_failed"], out["count"] = asked, failed, len(out["claims"])
            out["scopes_read"] = sorted({c["scope"] for c in out["claims"] if c.get("scope")})
        self.engine.ledger("memory.recall", principal_ref=p["ref"], linux_user=caller.user, linux_uid=caller.uid, process_ref=caller.process_ref, purpose="local",
                           detail={"scopes": sorted(set(scopes)), "classification": cls, "estate": bool(body.get("estate")), "holders": out["holders"], "holders_failed": out["holders_failed"],
                                   "count": out["count"], "as": p["ref"] if p["ref"] != caller.ref else None})
        return out

    def fanout(self, originator_ref, scopes, query, limit, cls, envelope=None):
        """Ask every holder the directory publishes for these scopes, in parallel and bounded; the holder names each claim."""
        holders = [h for h in self.holders.load() if set(h["scopes"]) & set(scopes)][: int(self.cfg["fanout_max"])]
        ms = memberships()
        results, failed, asked = [], [], []
        lock = threading.Lock()

        def ask(h):
            m = ms.get(h["source"]) or ms.get("node") or ms.get("desk")
            if not m:
                with lock:
                    failed.append({"holder": h["node"], "error": "no membership to sign with"})
                return
            want = sorted(set(h["scopes"]) & set(scopes))
            try:
                env = envelope or self.self_envelope(m, originator_ref, h["node"], want, cls)
                req = urllib.request.Request(f"http://{h['address']}:{h['port']}/memory/v1/query", data=json.dumps({"envelope": env, "scopes": want, "query": query, "classification": cls, "limit": limit}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=float(self.cfg["fanout_s"])) as r:
                    d = json.loads(r.read() or b"{}")
                with lock:
                    for c in d.get("claims") or []:
                        if isinstance(c, dict):
                            c["holder"] = h["node"]; c["local"] = False; results.append(c)
            except urllib.error.HTTPError as e:
                try:
                    err = json.loads(e.read() or b"{}").get("error") or {}
                except Exception:
                    err = {}
                with lock:
                    failed.append({"holder": h["node"], "status": e.code, "error": err.get("code") or str(e.code), "message": (err.get("message") or "")[:160]})
            except Exception as e:
                with lock:
                    failed.append({"holder": h["node"], "error": f"{e.__class__.__name__}: {str(e)[:120]}"})
        threads = []
        for h in holders:
            asked.append(h["node"])
            t = threading.Thread(target=ask, args=(h,), daemon=True); t.start(); threads.append(t)
        for t in threads:
            t.join(timeout=float(self.cfg["fanout_s"]) + 1)
        return results, asked, failed

    def local_recent(self, caller, body):
        """The newest memories a principal may read, no query: the Agents app's Memory page."""
        p = self.resolve(caller, body)
        scopes = body.get("scopes") or p["read"]
        if not isinstance(scopes, list) or not all(isinstance(s, str) and s in p["read"] for s in scopes):
            raise EngineError(403, "forbidden", f"{p['ref']} may read {', '.join(p['read']) or 'nothing'}")
        limit = max(1, min(200, int(body.get("limit") or 50)))
        kinds = body.get("kinds") if isinstance(body.get("kinds"), list) else None
        claims = self.engine.recent(p["ref"], scopes, limit, holder=self.node_ref(), kinds=kinds)
        return {"ok": True, "principal": p["ref"], "scopes": sorted(set(scopes)), "read": p["read"], "write": p["write"], "claims": claims, "count": len(claims)}

    def local_remember(self, caller, body):
        p = self.resolve(caller, body)
        scope = body.get("scope") or p["home_scope"]
        if not isinstance(scope, str) or not scope:
            raise EngineError(400, "invalid", "scope is required")
        if scope not in p["write"]:
            raise EngineError(403, "scope_write", f"{p['ref']} may not write {scope} (its write scopes: {', '.join(p['write']) or 'none'})")
        out = self.engine.remember(p["ref"], scope, body.get("text"), kind=body.get("kind") or "note", title=body.get("title"), confidence=body.get("confidence"),
                                   source=body.get("source"), sensitivity=body.get("sensitivity") or "internal", detail=body.get("detail"), occurred_at=body.get("occurred_at"))
        self.engine.ledger("memory.remember", principal_ref=p["ref"], linux_user=caller.user, linux_uid=caller.uid, process_ref=caller.process_ref, purpose="local",
                           detail={"scope": scope, "kind": out["kind"], "id": out["id"], "sensitivity": body.get("sensitivity") or "internal"})
        return dict(out, ok=True, principal=p["ref"])

    def local_forget(self, caller, body):
        p = self.resolve(caller, body)
        out = self.engine.forget(p["ref"], int(body.get("id") or 0))
        self.engine.ledger("memory.forget", principal_ref=p["ref"], linux_user=caller.user, linux_uid=caller.uid, process_ref=caller.process_ref, purpose="local", detail={"id": out["id"]})
        return dict(out, ok=True)

    # -- replication
    def sync(self, caller=None):
        """Pull the summaries of every scope a holder lets this host replicate; copies land in the local tenant with their origin."""
        state = {}
        try:
            with open(SYNC_STATE) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        ms = memberships()
        report = []
        for h in self.holders.load():
            for scope, s in h["scopes"].items():
                if not s.get("replicate"):
                    continue
                m = ms.get(h["source"]) or ms.get("node") or ms.get("desk")
                key = f"{h['node']} {scope}"
                row = {"holder": h["node"], "scope": scope}
                try:
                    if not m:
                        raise RuntimeError("no membership to sign with")
                    env = self.self_envelope(m, m.get("principal") or "host:unknown", h["node"], [scope], "internal")
                    req = urllib.request.Request(f"http://{h['address']}:{h['port']}/memory/v1/summaries", data=json.dumps({"envelope": env, "scope": scope, "since": state.get(key)}).encode(),
                                                 headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=max(5.0, float(self.cfg["fanout_s"]) * 3)) as r:
                        d = json.loads(r.read() or b"{}")
                    counts = self.engine.sync_write(h["node"], scope, d.get("summaries") or [], d.get("gone") or [])
                    state[key] = d.get("version") or utc()
                    row.update(counts, ok=True, version=state[key])
                except urllib.error.HTTPError as e:
                    try:
                        err = json.loads(e.read() or b"{}").get("error") or {}
                    except Exception:
                        err = {}
                    row.update(ok=False, error=err.get("code") or str(e.code), message=(err.get("message") or "")[:160])
                except Exception as e:
                    row.update(ok=False, error=f"{e.__class__.__name__}: {str(e)[:120]}")
                report.append(row)
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = SYNC_STATE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(state, fh)
            os.replace(tmp, SYNC_STATE)
        except OSError as e:
            log(f"sync state: {e}")
        self.engine.ledger("memory.sync", principal_ref=self.cfg["sync_principal"], purpose="replication", detail={"holders": [r for r in report]})
        return {"ok": True, "synced": report, "ts": utc()}

    # -- status, the TCP listener
    def status(self):
        g = self.engine.guest()
        ms = memberships()
        E = self.envelope_module()
        keys = E.Keys(KEYS_CACHE); keys.load()
        self.peers.load()
        holders = self.holders.load()
        keyed = {}
        for src, m in ms.items():
            try:
                self.private_key(m); keyed[src] = True
            except Exception as e:
                keyed[src] = f"{e.__class__.__name__}: {str(e)[:80]}"
        return {"ok": True, "version": VERSION, "api_version": API_VERSION, "started": self.started, "socket": self.cfg["socket"],
                "tcp": {**self.cfg["tcp"], "bound": self.tcp_bound, "overlay_address": overlay_address()}, "guest": g, "memberships": ms, "signing_keys": keyed,
                "embed": self.engine.embed_status(),
                "holders": [{"node": h["node"], "name": h["name"], "address": h["address"], "port": h["port"], "scopes": sorted(h["scopes"]), "source": h["source"]} for h in holders],
                "peers": [{"node": p["node"], "name": p["name"], "scopes": sorted(p["scopes"]), "key": bool(p.get("public_key"))} for p in self.peers.by_node.values()],
                "keys_cached": len(keys.table()), "copies": self.engine.copies(), "fanout_s": self.cfg["fanout_s"], "fanout_max": self.cfg["fanout_max"]}

    def apply_tcp(self):
        tcp = self.cfg["tcp"] or {}
        host = tcp.get("host") or "overlay"
        want = None
        if tcp.get("enabled"):
            addr = overlay_address() if host == "overlay" else host
            if not addr:
                log("tcp: exposed on the overlay but this host has no overlay address yet; not listening")
            else:
                want = (addr, int(tcp.get("port") or DEFAULT_PORT))
        if want == self.tcp_bound:
            return
        if self.tcp is not None:
            try:
                self.tcp.shutdown(); self.tcp.server_close()
            except Exception:
                pass
            self.tcp, self.tcp_bound = None, None
            log("tcp: listener stopped")
        if want is None:
            return
        try:
            srv = http.server.ThreadingHTTPServer(want, Handler)
            srv.daemon_threads = True; srv.kind = "estate"; srv.face = self
            self.tcp, self.tcp_bound = srv, want
            self.tcp_thread = threading.Thread(target=srv.serve_forever, daemon=True); self.tcp_thread.start()
            log(f"tcp: serving the estate on {want[0]}:{want[1]}")
        except OSError as e:
            log(f"tcp: cannot bind {want[0]}:{want[1]}: {e}")

    def reload(self):
        self.cfg.reload()
        self.apply_tcp()
        self.peers.stamp = None; self.peers.load()
        with self._key_lock:
            self._keys.clear()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"maluos-memory/{VERSION}"

    def address_string(self):
        return "unix" if getattr(self.server, "kind", "local") == "local" else super().address_string()

    def log_message(self, fmt, *args):
        if os.environ.get("MALUOS_MEMORY_DEBUG"):
            log(fmt % args)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        if n > 1 << 20:
            raise EngineError(413, "too_large", "body over 1 MiB")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise EngineError(400, "bad_json", "body is not JSON")
        if not isinstance(d, dict):
            raise EngineError(400, "bad_json", "body is an object")
        return d

    def send(self, status, obj):
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def fail(self, e):
        self.send(e.status, {"error": {"code": e.code, "message": e.message, **e.extra}})

    def peer(self):
        creds = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII"))
        pid, uid, gid = struct.unpack("iII", creds)
        self.server.face.cfg.reload()
        return Caller(pid, uid, gid, self.server.face.cfg.identities)

    def do_GET(self):
        face = self.server.face
        p = self.path.split("?", 1)[0]
        qs = {}
        if "?" in self.path:
            import urllib.parse
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(self.path.split("?", 1)[1]).items()}
        try:
            if getattr(self.server, "kind", "local") == "estate":
                if p == "/memory/v1/health":
                    g = face.engine.guest()
                    return self.send(200, {"ok": True, "service": "maluos-memory", "version": VERSION, "api_version": API_VERSION, "node": face.node_ref(), "shared": g["shared"]})
                raise EngineError(404, "not_found", p)
            caller = self.peer()
            if p == "/v1/health":
                return self.send(200, {"ok": True, "service": "maluos-memory", "version": VERSION})
            if p == "/v1/status":
                return self.send(200, face.status())
            if p == "/v1/facts":
                tcp = face.cfg["tcp"] or {}
                return self.send(200, face.engine.facts(tcp.get("port") or DEFAULT_PORT, bool(tcp.get("enabled")) and face.tcp_bound is not None))
            if p == "/v1/embed":
                return self.send(200, {"ok": True, **face.engine.embed_status()})
            if p == "/v1/whoami":
                pr = face.engine.principal(caller.ref)
                return self.send(200, {"ok": True, "user": caller.user, "uid": caller.uid, "principal": caller.ref, "operator": caller.operator, "enrolled": pr is not None,
                                       "read": (pr or {}).get("read"), "write": (pr or {}).get("write"), "max_sensitivity": (pr or {}).get("max_sensitivity")})
            if p == "/v1/usage":
                since = qs.get("since")
                limit = max(1, min(1000, int(qs.get("limit") or 100)))
                rows = face.engine.ledger_rows(None if caller.operator else caller.ref, since, limit)
                return self.send(200, {"ok": True, "events": rows})
            raise EngineError(404, "not_found", p)
        except EngineError as e:
            self.fail(e)
        except Exception as e:
            log(f"GET {p}: {e.__class__.__name__}: {str(e)[:200]}")
            self.send(500, {"error": {"code": "internal", "message": f"{e.__class__.__name__}: {str(e)[:200]}"}})

    def do_POST(self):
        face = self.server.face
        p = self.path.split("?", 1)[0]
        try:
            body = self.body()
            if getattr(self.server, "kind", "local") == "estate":
                if p == "/memory/v1/query":
                    return self.send(200, face.estate_query(body))
                if p == "/memory/v1/summaries":
                    return self.send(200, face.estate_summaries(body))
                raise EngineError(404, "not_found", p)
            caller = self.peer()
            if p == "/v1/recall":
                return self.send(200, face.local_recall(caller, body))
            if p == "/v1/recent":
                return self.send(200, face.local_recent(caller, body))
            if p == "/v1/remember":
                return self.send(200, face.local_remember(caller, body))
            if p == "/v1/forget":
                return self.send(200, face.local_forget(caller, body))
            if p == "/v1/sync":
                if not caller.operator:
                    raise EngineError(403, "not_operator", "sync is an operator's")
                return self.send(200, face.sync(caller))
            if p == "/v1/embed":
                if not caller.operator:
                    raise EngineError(403, "not_operator", "embedding is an operator's")
                face.cfg.reload()
                if body.get("probe"):
                    vec = (face.embedder.embed(["a probe of the embedding model"]) or [None])[0]
                    if not vec:
                        raise EngineError(503, "embed_unavailable", f"the embedder did not answer: {face.embedder.last_error}")
                    face.engine.ledger("memory.embed", principal_ref=caller.ref, purpose="probe", detail={"model": face.embedder.model, "dim": len(vec)}, linux_user=caller.user, linux_uid=caller.uid, process_ref=caller.process_ref)
                    return self.send(200, {"ok": True, "model": face.embedder.model, "space": face.embedder.space, "dim": len(vec)})
                if body.get("backfill"):
                    r = face.engine.backfill()
                    face.engine.ledger("memory.embed", principal_ref=caller.ref, purpose="backfill", detail={"model": face.embedder.model, **{k: v for k, v in r.items() if k != "error"}},
                                       linux_user=caller.user, linux_uid=caller.uid, process_ref=caller.process_ref)
                    return self.send(200, {"ok": True, **r})
                raise EngineError(400, "invalid", "probe or backfill")
            if p == "/v1/reload":
                if not caller.operator:
                    raise EngineError(403, "not_operator", "reload is an operator's")
                face.reload()
                return self.send(200, {"ok": True, "reloaded": True, "tcp": face.tcp_bound})
            raise EngineError(404, "not_found", p)
        except EngineError as e:
            self.fail(e)
        except Exception as e:
            log(f"POST {p}: {e.__class__.__name__}: {str(e)[:200]}")
            self.send(500, {"error": {"code": "internal", "message": f"{e.__class__.__name__}: {str(e)[:200]}"}})


class UnixHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True
    allow_reuse_address = False
    kind = "local"

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "maluos-memory", 0


def serve(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="MaluOS memory face")
    ap.add_argument("--socket", help="bind this path (default: inherit from systemd, else the configuration)")
    ap.add_argument("--no-sync", action="store_true", help="no hourly replication pull")
    args = ap.parse_args(argv)
    cfg = Config()
    face = Face(cfg)
    Handler.face = face
    fds = int(os.environ.get("LISTEN_FDS") or 0)
    if fds and os.environ.get("LISTEN_PID") in (None, str(os.getpid())):
        srv = UnixHTTPServer("", Handler, bind_and_activate=False)
        srv.socket.close()
        srv.socket = socket.socket(fileno=3)
        log(f"serving on inherited socket (activation), tenant {cfg['tenant']}")
    else:
        path = args.socket or cfg["socket"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.remove(path)
        srv = UnixHTTPServer(path, Handler)
        os.chmod(path, 0o666)
        log(f"serving on {path}, tenant {cfg['tenant']}")
    srv.face = face
    face.apply_tcp()

    def keeper():
        """Re-apply the listener when the configuration or the overlay address changes; pull replicas hourly."""
        last_sync = time.time()
        while True:
            time.sleep(15)
            try:
                if cfg.reload():
                    face.apply_tcp()
                elif (cfg["tcp"] or {}).get("enabled") and face.tcp_bound is None:
                    face.apply_tcp()
                if not args.no_sync and time.time() - last_sync > float(cfg["sync_every_s"]):
                    last_sync = time.time()
                    r = face.sync()
                    if r["synced"]:
                        log(f"sync: {json.dumps(r['synced'])[:300]}")
                    if face.embedder.model:
                        b = face.engine.backfill(limit=500)       # what was written while the embedder was away
                        if b.get("embedded") or b.get("failed"):
                            log(f"embed: backfill {json.dumps(b)[:200]}")
            except Exception as e:
                log(f"keeper: {e.__class__.__name__}: {str(e)[:120]}")
    threading.Thread(target=keeper, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
