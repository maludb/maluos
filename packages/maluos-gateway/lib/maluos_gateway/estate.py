"""Shared inference across the estate (Phase 13 slice 3, docs/phase13-slice3-inference.md).

The estate's directory publishes the backends this host may use (endpoints.inference); maluos-estate (a node) or
maluos-desk (a desk) writes that answer to a cache file, and the gateway makes an ESTATE RUNG of each backend: a
remote backend (G2's transport, unchanged) whose endpoint is the serving host's overlay address and whose
credential is this host's own INFERENCE KEY, read from the vault for the gateway's own use. On the serving side the
PEERS cache (the members the kernel allows to call this host, each with the SHA-256 of its key and its ceilings)
authenticates a presented key: a peer is the principal `node:<ref>` here, served under the kernel's class and
classification ceilings, never with this host's cloud credit. With the `scheduler` entitlement the gateway asks the
kernel to PLACE a call first (1.5 s by default, MALUOS_PLACE_TIMEOUT_S; the inference key as the credential) and falls back to its own ranking.

Cache files (JSON, written by the member's enrolment side, read by the gateway at every catalogue reload):
  /run/maluos/estate/inference.json, /run/maluos/estate/peers.json   a node's (maluos-estated, as maluos-estate)
  /run/maluos/office/inference.json, /run/maluos/office/peers.json   a desk's (maluctl office, as the owner)
A desk's file is trusted only when root or the desk's owner (office.yaml) owns it: the directory is 1777.
  {"fetched_at", "self", "secret" (the vault ref of this host's inference key), "principal", "backends": [...],
   "editions": [...], "place": URL|null, "lease_s", "version"}
Environment (tests): MALUOS_ESTATE_INFERENCE, MALUOS_ESTATE_PEERS, MALUOS_OFFICE_INFERENCE, MALUOS_OFFICE_PEERS.
"""
import asyncio, hashlib, json, os, pwd, time
import aiohttp

from .remote import RemoteBackend

FILES = {"node": (os.environ.get("MALUOS_ESTATE_INFERENCE", "/run/maluos/estate/inference.json"), os.environ.get("MALUOS_ESTATE_PEERS", "/run/maluos/estate/peers.json")),
         "desk": (os.environ.get("MALUOS_OFFICE_INFERENCE", "/run/maluos/office/inference.json"), os.environ.get("MALUOS_OFFICE_PEERS", "/run/maluos/office/peers.json"))}
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
PREFIX = "estate:"
CLASS_ORDER = {"interactive": 0, "agent": 1, "batch": 2}
PLACE_TIMEOUT_S = float(os.environ.get("MALUOS_PLACE_TIMEOUT_S", "1.5"))     # the kernel is a PHP request over the overlay; a slow or absent answer falls back to the gateway's own ranking


def log(msg):
    from .server import log as _log
    _log(msg)


class EstateBackend(RemoteBackend):
    """A backend the estate's directory published: a remote node reached over the overlay with this host's inference key."""
    is_estate = True

    def __init__(self, row, session):
        super().__init__(row, session)
        self._directory(row)

    def _directory(self, row):
        d = row.get("directory") or {}
        self.node = d.get("node")                       # desk:41, server:57, inference:58
        self.label = d.get("name")                      # the overlay label (NAME.internal)
        self.display_name = d.get("display_name")
        self.class_max = d.get("class_max")
        self.classification_max = d.get("classification_max") or "internal"
        self.priority = int(d.get("priority") or 0)
        self.directory_wait = d.get("expected_wait_s") if isinstance(d.get("expected_wait_s"), dict) else {}
        self.directory_queue = d.get("queue") if isinstance(d.get("queue"), dict) else {}
        self.contribution = d.get("contribution") or "always"
        self.shared = bool(d.get("share", True))

    def update(self, row):
        super().update(row)
        self._directory(row)

    @property
    def max_concurrent(self):
        return int(self.capacity.get("max_concurrent") or 2)

    def rank_wait(self, cls):
        """The serving host's own expected wait for a class, as the directory last heard it (refreshed hourly and on change)."""
        try:
            return float(self.directory_wait.get(cls) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def status(self):
        d = super().status()
        d.update({"estate": True, "node": self.node, "label": self.label, "display_name": self.display_name, "class_max": self.class_max,
                  "classification_max": self.classification_max, "priority": self.priority, "contribution": self.contribution, "shared": self.shared,
                  "directory_wait_s": self.directory_wait, "directory_queue": self.directory_queue})
        return d


# -- the cache files
def _trusted(path, source):
    """A node's file is the daemon's (its directory is 0755, owned by maluos-estate); a desk's must be root's or the owner's."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if source == "node" or st.st_uid == 0:
        return True
    try:
        import yaml
        with open(OFFICE_CONF) as f:
            owner = ((yaml.safe_load(f) or {}).get("owner") or {}).get("login")
        return bool(owner) and pwd.getpwnam(owner).pw_uid == st.st_uid
    except Exception:
        return False


def read_cache(kind):
    """(data, source, mtime) for the backends ('inference') or the peers ('peers'): a node's file first, else a desk's."""
    found = read_caches(kind)
    return found[0] if found else (None, None, None)


def read_caches(kind):
    """Every trusted cache of a kind, the node's first: [(data, source, mtime)]. A host that is both a node and a desk
    holds both memberships' views; the gateway may use what either allows."""
    idx = 0 if kind == "inference" else 1
    out = []
    for source in ("node", "desk"):
        path = FILES[source][idx]
        if not os.path.exists(path) or not _trusted(path, source):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                out.append((data, source, os.stat(path).st_mtime))
        except (OSError, ValueError) as e:
            log(f"estate: {path}: {e.__class__.__name__}: {str(e)[:80]}")
    return out


def backend_rows(data, rows=None):
    """The directory's backends as catalogue rows the gateway's factory understands; each rung carries the vault ref of the
    key its own membership holds. A backend already in `rows` (the node's cache read first) is kept."""
    rows = rows if rows is not None else {}
    secret = data.get("secret")
    for b in data.get("backends") or []:
        if not isinstance(b, dict) or not b.get("name") or not b.get("address"):
            continue
        name = PREFIX + str(b["name"])
        if name in rows:
            continue
        rows[name] = {"name": name, "kind": "estate", "endpoint": f"http://{b['address']}:{int(b.get('port') or 11435)}", "secret_ref": secret, "enabled": True,
                      "options": {"models": [m.get("name") for m in (b.get("models") or []) if isinstance(m, dict) and m.get("name")]},
                      "capacity": {"max_concurrent": 2}, "directory": b, "source": data.get("source")}
    return rows


class Peers:
    """The members allowed to call this host, by their keys' hashes; refreshed from the cache file when it changes."""

    def __init__(self):
        self.by_hash, self.mtime, self.source, self.version, self.fetched_at = {}, None, None, None, None

    def load(self):
        found = read_caches("peers")
        if not found:
            if self.by_hash:
                self.by_hash, self.mtime, self.source = {}, None, None
            return
        stamp = tuple((src, mt) for _, src, mt in found)
        if stamp == self.mtime:
            return
        by_hash = {}
        for data, source, _ in found:
            for p in data.get("peers") or []:
                if isinstance(p, dict) and p.get("key_hash") and p.get("node") and p["key_hash"] not in by_hash:
                    by_hash[p["key_hash"]] = dict(p, source=source)
        self.by_hash, self.mtime, self.source = by_hash, stamp, "+".join(src for _, src, _ in found)
        self.version, self.fetched_at = found[0][0].get("version"), found[0][0].get("fetched_at")
        log(f"estate: peers from the {self.source}'s cache: {len(self.by_hash)} member(s) may call this host (version {self.version})")

    def lookup(self, token):
        if not token or not self.by_hash:
            return None
        return self.by_hash.get(hashlib.sha256(token.encode()).hexdigest())


def cap_class(cls, class_max, classes):
    """The kernel's class ceiling for a peer: a higher (more urgent) class is served as the ceiling's, never refused."""
    if not class_max or class_max not in classes or cls not in classes:
        return cls
    return class_max if classes[cls]["priority"] < classes[class_max]["priority"] else cls


# -- the scheduler client (the `scheduler` entitlement)
async def place(gw, call, candidates):
    """Ask the kernel where this call should go. Returns the rung it chose among `candidates` (estate rungs), or None
    (not entitled, no answer within PLACE_TIMEOUT_S, no capacity): the caller's own ranking stands then."""
    est = gw.estate
    if not est.get("place") or "scheduler" not in (est.get("editions") or []) or not candidates:
        return None
    # The gateway asks as the membership whose rung ranks first, and only that membership's rungs are the kernel's
    # choice: a host that is both a desk and a node holds two keys and two views (the desk may use the servers, the
    # node may use the desk's contribution), and a placement made with one key must land on a rung dialled with it.
    top = gw.backends.get(candidates[0]["backend"])
    ref = getattr(top, "secret_ref", None)
    key = (await gw.remote_key(top)) if ref else None
    if not key:
        key = await gw.estate_key()
    if not key:
        return None
    if ref:
        candidates = [r for r in candidates if getattr(gw.backends.get(r["backend"]), "secret_ref", None) == ref] or candidates
    body = {"class": call.cls, "model": call.requested if call.requested not in (gw.catalog.tiers if gw.catalog else {}) else None,
            "sensitivity": call.hints.get("sensitivity") or "internal", "origin": call.id}
    if call.hints.get("max_wait") is not None:
        body["deadline_s"] = call.hints["max_wait"]
    t0 = time.monotonic()
    try:
        # its own session: the gateway's shared one stalled its first request to a new host for the whole timeout
        # (seen 2026-10-29 in tests/gateway-local-test.sh; a fresh session connects at once), and the kernel's
        # placement traffic should never queue behind a backend's connection pool anyway
        if gw.place_session is None:
            gw.place_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=8))
        async with gw.place_session.post(est["place"], json=body, headers={"Authorization": f"Bearer {key}"}, timeout=aiohttp.ClientTimeout(total=PLACE_TIMEOUT_S)) as r:
            if r.status != 200:
                log(f"estate: place answered {r.status}: {(await r.text())[:120]}")
                return None
            ans = await r.json()
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
        log(f"estate: place: {e.__class__.__name__}: {str(e)[:80]} after {time.monotonic() - t0:.3f} s (ranking locally)")
        return None
    chosen = (ans.get("backend") or {}).get("name") if isinstance(ans.get("backend"), dict) else None
    if not chosen:
        return None
    call.placement = {"reason": ans.get("reason"), "lease_s": ans.get("lease_s"), "backend": PREFIX + chosen, "class": ans.get("class")}
    for r in candidates:
        if r["backend"] == PREFIX + chosen:
            return r
    return None


# -- this host's own facts, for its heartbeat (≤ 8 KB)
def facts(gw):
    from .node_api import lanes
    models, seen = [], set()
    for b in gw.backends.values():
        if b.is_cloud or getattr(b, "is_remote", False):
            continue
        loaded = {m.get("name") for m in b.loaded} | {m.get("model") for m in b.loaded}
        for name, info in sorted(b.models.items()):
            if name in seen or (name.endswith(":latest") and name[:-7] in b.models):
                continue
            seen.add(name)
            d = (info or {}).get("details") or {}
            models.append({"name": name, "family": d.get("family") or (info or {}).get("family"), "size": (info or {}).get("size"),
                           "loaded": name in loaded or (name + ":latest") in loaded, "backend": b.name})
            if len(models) >= 120:
                break
    snaps = {n: s.snapshot() for n, s in gw.schedulers.items() if n in gw.backends and not gw.backends[n].is_cloud and not getattr(gw.backends[n], "is_remote", False)}
    ew = {}
    for cls in (gw.catalog.classes if gw.catalog else {}):
        ew[cls] = max([s["classes"].get(cls, {}).get("expected_wait_s", 0) for s in snaps.values()] or [0])
    ln = {n: {k: v for k, v in l.items() if k in ("kind", "capacity", "running", "queued", "paused", "resident", "healthy")} for n, l in lanes(gw).items() if n in snaps}
    share = gw.share_state()
    return {"models": models, "lanes": ln, "queue": {"queued": sum(s["queued"] for s in snaps.values()), "running": sum(s["running"] for s in snaps.values())},
            "expected_wait_s": ew, "share": bool(share.get("enabled")), "contribution": share.get("contribution") or "always",
            "port": int((gw.cfg.get("tcp") or {}).get("port") or 11435), "api_version": 1, "exposed": gw.exposed().get("network", False),
            "idle": share.get("idle")}
