"""The delegation envelope (Phase 13 slice 2, docs/phase13-slice2-delegation.md): what a sender puts on
tasks/send across the estate, signed with its node's ed25519 key and verified by the kernel and again by the
agent's host against the directory's keys.

Canonical form for signing: the object without `sig`, every member whose value is None, [] or {} omitted,
keys sorted at every level, no whitespace, unicode and slashes unescaped — the kernel's PHP produces the
same bytes (maludb-os-core app/features/estate/delegation.php, proven by its bin/test_estate_delegation.php).

    import maluos_estate.envelope as E
    priv, pub = E.genkey("desk:42")                  # OpenSSH private key text, "ssh-ed25519 AAAA… desk:42"
    env = E.make({"principal": "user:ed", "kind": "human", "node": "desk:42"}, {"principal": "user:ed", "node": "desk:42"},
                 {"agent": "helpdesk", "node": "server:57"}, "investigate …")
    env = E.sign(env, "desk:42", priv)
    ok, reason, message = E.verify(env, keys={"desk:42": pub}, expect_signer="desk:42", nonces=E.Nonces())

Keys are `ssh-ed25519 …` lines (ssh-keygen's and the node key of slice 1); private keys are OpenSSH text
(what ssh-keygen writes and what the vault holds as estate-node-key / office-desk-key).
"""
import base64, json, os, secrets, threading, time

VERSION = 1
MAX_LIFE_S = 3600
SKEW_S = 60
CLASSIFICATIONS = ("public", "internal", "restricted", "prohibited")
KEYS_CACHE = os.environ.get("MALUOS_ESTATE_KEYS", "/run/maluos/estate/keys.json")


def utc(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def parse_ts(s):
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (TypeError, ValueError):
        return None


# -- canonical form
def _prune(v):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            y = _prune(x)
            if y is None or y == [] or y == {}:
                continue
            out[k] = y
        return out
    if isinstance(v, (list, tuple)):
        return [y for y in (_prune(x) for x in v) if not (y is None or y == [] or y == {})]
    return v


def canonical(env):
    e = {k: v for k, v in env.items() if k != "sig"}
    return json.dumps(_prune(e), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# -- keys
def _crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return serialization, ed25519


def genkey(comment=""):
    """A new ed25519 key: (OpenSSH private key text, 'ssh-ed25519 AAAA… comment')."""
    serialization, ed25519 = _crypto()
    priv = ed25519.Ed25519PrivateKey.generate()
    text = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
    return text, public_line(priv, comment)


def load_private(text):
    """An OpenSSH private key (text), or a raw 32-byte seed in base64."""
    serialization, ed25519 = _crypto()
    data = text.encode() if isinstance(text, str) else text
    if b"OPENSSH PRIVATE KEY" in data or b"PRIVATE KEY" in data:
        return serialization.load_ssh_private_key(data, password=None) if b"OPENSSH" in data else serialization.load_pem_private_key(data, password=None)
    raw = base64.b64decode(data.strip())
    if len(raw) == 64:
        raw = raw[:32]
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def public_line(priv, comment=""):
    serialization, _ = _crypto()
    line = priv.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    return line + (" " + comment if comment else "")


def public_of_private(text, comment=""):
    return public_line(load_private(text), comment)


def raw_public(line):
    """The 32 raw bytes of an 'ssh-ed25519 …' line, or None."""
    try:
        parts = str(line).split()
        if len(parts) < 2 or parts[0] != "ssh-ed25519":
            return None
        blob = base64.b64decode(parts[1])
        n = int.from_bytes(blob[:4], "big")
        if blob[4:4 + n] != b"ssh-ed25519":
            return None
        off = 4 + n
        m = int.from_bytes(blob[off:off + 4], "big")
        if m != 32:
            return None
        return blob[off + 4:off + 36]
    except Exception:
        return None


# -- make, sign, verify
def new_id():
    return "env_" + secrets.token_hex(12)


def make(originator, sender, target, purpose, authority=None, chain=None, parent=None, life_s=600, env_id=None):
    now = time.time()
    env = {"v": VERSION, "id": env_id or new_id(), "issued_at": utc(now), "expires_at": utc(now + min(life_s, MAX_LIFE_S)), "nonce": secrets.token_hex(8),
           "originator": dict(originator), "sender": dict(sender),
           "chain": list(chain) if chain else [{"principal": sender["principal"], "node": sender["node"], "ts": utc(now), "task_id": None}],
           "target": dict(target), "purpose": purpose or "",
           "authority": dict(authority) if authority else {"scopes": [], "classification": "internal", "budget": {"usd": 0, "calls": 0}}}
    if parent is not None:
        env["parent"] = parent
    return env


def forward(parent, sender, target, task_id=None, authority=None):
    """A hop that forwards: the same id, originator and (or a narrower) authority, this sender, the chain extended, the received envelope as parent."""
    now = time.time()
    env = {"v": VERSION, "id": parent["id"], "issued_at": utc(now), "expires_at": utc(now + 600), "nonce": secrets.token_hex(8),
           "originator": dict(parent["originator"]), "sender": dict(sender),
           "chain": list(parent.get("chain") or []) + [{"principal": sender["principal"], "node": sender["node"], "ts": utc(now), "task_id": task_id}],
           "target": dict(target), "purpose": parent.get("purpose", ""), "authority": dict(authority or parent.get("authority") or {}), "parent": parent}
    return env


def sign(env, key_node, private_text):
    env = dict(env)
    env["sender"] = dict(env.get("sender") or {}, node=key_node)
    priv = load_private(private_text)
    env["sig"] = {"alg": "ed25519", "key": key_node, "value": base64.b64encode(priv.sign(canonical(env))).decode()}
    return env


class Nonces:
    """Replay memory: a nonce per key, kept for the envelope's life."""

    def __init__(self):
        self.seen, self.lock = {}, threading.Lock()

    def take(self, key_node, nonce, expires):
        with self.lock:
            now = time.time()
            for k in [k for k, e in self.seen.items() if e < now]:
                del self.seen[k]
            k = (key_node, nonce)
            if k in self.seen:
                return False
            self.seen[k] = expires + SKEW_S
            return True


def _node_ref(ref):
    if ref == "coordinator":
        return ("coordinator", None)
    if isinstance(ref, str) and ":" in ref:
        kind, _, num = ref.partition(":")
        if kind in ("desk", "server", "inference") and num.isdigit():
            return (kind, int(num))
    return None


def verify(env, keys, expect_signer=None, nonces=None, now=None, _depth=0):
    """(ok, reason, message). keys: {node_ref: 'ssh-ed25519 …'} (the keys answer, see Keys); nonces: a Nonces
    (None skips the replay check); expect_signer binds the signing key to the caller."""
    now = now or time.time()
    if not isinstance(env, dict) or env.get("v") != VERSION:
        return False, "bad_envelope", "envelope.v must be %d" % VERSION
    if _depth > 8:
        return False, "bad_envelope", "too many parents"
    for k in ("id", "issued_at", "expires_at", "nonce"):
        if not isinstance(env.get(k), str) or not env[k]:
            return False, "bad_envelope", "envelope.%s is required" % k
    if not env["id"].startswith("env_"):
        return False, "bad_envelope", "envelope.id is env_ and hex"
    for k in ("originator", "sender", "target", "sig"):
        if not isinstance(env.get(k), dict):
            return False, "bad_envelope", "envelope.%s is required" % k
    if not isinstance(env.get("chain"), list) or not env["chain"]:
        return False, "bad_envelope", "envelope.chain is required"
    issued, expires = parse_ts(env["issued_at"]), parse_ts(env["expires_at"])
    if issued is None or expires is None:
        return False, "bad_envelope", "issued_at and expires_at are ISO-8601 UTC"
    if expires - issued > MAX_LIFE_S or expires < issued:
        return False, "bad_envelope", "expires_at is at most an hour after issued_at"
    if issued > now + SKEW_S:
        return False, "bad_envelope", "issued_at is in the future"
    if expires < now - SKEW_S:
        return False, "expired", "the envelope has expired"
    sig = env["sig"]
    if sig.get("alg") != "ed25519" or not isinstance(sig.get("key"), str) or not isinstance(sig.get("value"), str):
        return False, "bad_signature", "sig needs alg ed25519, key and value"
    if _node_ref(sig["key"]) is None:
        return False, "bad_signature", "sig.key names a node or the coordinator"
    if env["sender"].get("node") != sig["key"]:
        return False, "bad_signature", "sender.node must be the signing key's node"
    if expect_signer is not None and sig["key"] != expect_signer:
        return False, "bad_signature", "signed by %s, expected %s" % (sig["key"], expect_signer)
    pub = raw_public((keys or {}).get(sig["key"]))
    if pub is None:
        return False, "bad_signature", "no key is known for %s" % sig["key"]
    try:
        _, ed25519 = _crypto()
        ed25519.Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(sig["value"]), canonical(env))
    except Exception:
        return False, "bad_signature", "the signature does not verify"
    last = env["chain"][-1]
    if not isinstance(last, dict) or last.get("principal") != env["sender"].get("principal"):
        return False, "bad_envelope", "the chain's last hop is the sender"
    cls = (env.get("authority") or {}).get("classification", "internal")
    if cls not in CLASSIFICATIONS:
        return False, "bad_envelope", "authority.classification is one of " + ", ".join(CLASSIFICATIONS)
    if env.get("parent") is not None:
        ok, reason, msg = verify(env["parent"], keys, None, None, now, _depth + 1)
        if not ok:
            return False, reason, "parent: " + msg
        if env["parent"].get("id") != env["id"]:
            return False, "bad_envelope", "a forwarded envelope keeps its parent's id"
    if nonces is not None and not nonces.take(sig["key"], env["nonce"], expires):
        return False, "replay", "this nonce was seen before"
    return True, None, None


# -- the keys cache (maluos-estated writes it from GET /api/v1/estate/keys; agents and the session read it)
class Keys:
    def __init__(self, path=None):
        self.path = path or KEYS_CACHE
        self.data = None

    def load(self):
        try:
            with open(self.path) as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = None
        return self.data

    def save(self, answer):
        """The keys answer → {fetched_at, keys: {node: line}, coordinator: line}."""
        d = {"fetched_at": answer.get("fetched_at") or utc(), "coordinator": (answer.get("coordinator") or {}).get("public_key"),
             "keys": {k["node"]: k["public_key"] for k in answer.get("keys") or [] if k.get("node") and k.get("public_key")}}
        if d["coordinator"]:
            d["keys"]["coordinator"] = d["coordinator"]
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh)
        os.chmod(tmp, 0o644); os.replace(tmp, self.path)
        self.data = d
        return d

    def table(self):
        if self.data is None:
            self.load()
        return (self.data or {}).get("keys") or {}

    def age(self):
        if self.data is None:
            self.load()
        t = parse_ts(((self.data or {}).get("fetched_at")) or "")
        return None if t is None else time.time() - t


# -- the agent's accept policy, applied on its host
def accepts(accept_from, owner, originator):
    """accept_from: a list of org, dept:N, user:LOGIN, agent:NAME, node:KIND; empty = the owner only."""
    principal = (originator or {}).get("principal") or ""
    if not accept_from:
        return bool(principal) and principal == (owner or "")
    onode = _node_ref((originator or {}).get("node"))
    depts = [str(d) for d in ((originator or {}).get("departments") or [])]
    for rule in accept_from:
        if rule == "org" and principal:
            return True
        if rule == principal:
            return True
        if rule.startswith("node:") and onode and rule[5:] == onode[0]:
            return True
        if rule.startswith("dept:") and rule[5:] in depts:
            return True
    return False


def classification_within(cls, ceiling):
    """Is the envelope's classification at or below the agent's max_classification? prohibited is the top (local only)."""
    if not ceiling:
        return True
    order = {c: i for i, c in enumerate(CLASSIFICATIONS)}
    return order.get(cls or "internal", 1) <= order.get(ceiling, 3)


def needs_approval(approve, env):
    """Does the policy's approve list name this envelope's classification or originator?"""
    if not approve:
        return False
    cls = (env.get("authority") or {}).get("classification", "internal")
    o = env.get("originator") or {}
    return cls in approve or (o.get("principal") in approve) or ("org" in approve) or any(r.startswith("node:") and _node_ref(o.get("node")) and r[5:] == _node_ref(o.get("node"))[0] for r in approve)
