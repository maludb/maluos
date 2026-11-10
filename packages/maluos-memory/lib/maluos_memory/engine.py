"""The engine behind the face: PostgreSQL as the face's own role (maluos-memory, peer-authenticated), the tenant's
memory facades, and every read or write bound to a principal and a scope set for the length of one transaction
(maludb-core 0.106.0 principal scoping, docs/principal-scoping.md there). Nothing here decides who may ask what:
the server does, and hands the engine the principal and the scopes it settled on."""
import datetime, http.client, json, os, re, socket, struct, threading, time, urllib.error, urllib.request, zlib
import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row

from . import SENSITIVITY, SCOPE_SHAREABLE, API_VERSION, DEFAULT_PORT

CONF = os.environ.get("MALUOS_MEMORY_CONFIG", "/etc/maluos/memory.yaml")
VAULT_CONF = os.environ.get("MALUOS_VAULT_CONF", "/etc/maluos/vault.yaml")
DEFAULTS = {"database": "maludb", "tenant": "maluos", "pg_host": "/var/run/postgresql", "pg_user": None, "pg_role": None,
            "socket": "/run/maluos/memory.sock", "tcp": {"enabled": False, "host": "overlay", "port": DEFAULT_PORT},
            "guest": "estate:guest", "sync_principal": "estate:sync", "fanout_s": 5.0, "fanout_max": 8, "sync_every_s": 3600, "query_timeout_s": 10,
            "ask_self": False,   # a host never asks (or replicates from) its own identities; tests on one host set it
            # slice 4b: semantic recall. model null = text recall alone; url "gateway" = the gateway's OpenAI face over its socket,
            # else an http(s) URL (…/v1/embeddings OpenAI-shaped, …/api/embed Ollama-shaped); the space is memory/<model>
            "embed": {"model": None, "url": "gateway", "gateway_socket": "/run/maluos/gateway.sock", "timeout_s": 5.0, "min_score": 0.35}}
KINDS = ("note", "summary", "observation", "decision", "profile")
SCOPE_RE = re.compile(SCOPE_SHAREABLE)
TEXT_MAX = 8000
DETAIL_MAX = 16 * 1024


def utc(t=None):
    return (t or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def shareable(scope):
    return isinstance(scope, str) and bool(SCOPE_RE.match(scope))


class EngineError(Exception):
    def __init__(self, status, code, message, extra=None):
        super().__init__(message); self.status, self.code, self.message, self.extra = status, code, message, extra or {}


class Config:
    """/etc/maluos/memory.yaml (written by first boot) plus the identities map of vault.yaml, re-read when either changes."""

    def __init__(self, path=CONF):
        self.path, self.data, self.mtime, self.vmtime, self.identities = path, dict(DEFAULTS), None, None, {}
        self.reload()

    def reload(self):
        import yaml
        changed = False
        for p, attr in ((self.path, "mtime"), (VAULT_CONF, "vmtime")):
            try:
                mt = os.stat(p).st_mtime
            except OSError:
                mt = None
            if mt != getattr(self, attr):
                setattr(self, attr, mt); changed = True
        if not changed:
            return False
        d = dict(DEFAULTS)
        try:
            with open(self.path) as fh:
                conf = yaml.safe_load(fh) or {}
            for k, v in conf.items():
                if isinstance(v, dict) and isinstance(d.get(k), dict):
                    d[k] = {**d[k], **v}
                else:
                    d[k] = v
        except OSError:
            pass
        self.data = d
        ids = {}
        try:
            with open(VAULT_CONF) as fh:
                ids = (yaml.safe_load(fh) or {}).get("identities") or {}
        except OSError:
            pass
        self.identities = {str(k): str(v) for k, v in ids.items()}
        return True

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)


_PG_PASSWORD = {}


def remote_kwargs(d):
    """Phase 14: the database on another server. The port, TLS, and the role's password: from a file, or from the
    vault (`pg_password_ref`, a read grant to this service's own principal: the face is not a broker), fetched once and again after a failure."""
    kw = {}
    if d.get("pg_port"):
        kw["port"] = int(d["pg_port"])
    if d.get("pg_sslmode"):
        kw["sslmode"] = d["pg_sslmode"]
    if d.get("pg_sslrootcert"):
        kw["sslrootcert"] = d["pg_sslrootcert"]
    if d.get("pg_password_file"):
        with open(d["pg_password_file"]) as f:
            kw["password"] = f.read().strip()
    elif d.get("pg_password_ref"):
        ref = d["pg_password_ref"]
        if ref not in _PG_PASSWORD:
            import sys
            sys.path.insert(0, "/usr/lib/maluos")
            from maluos_vault_client import Vault
            _PG_PASSWORD[ref] = Vault(d.get("vault_socket") or os.environ.get("MALUOS_VAULT_SOCKET") or "/run/maluos/vault.sock").value(ref, "read", "the database password")["value"]
        kw["password"] = _PG_PASSWORD[ref]
    return kw


def forget_password():
    _PG_PASSWORD.clear()


def connect(cfg):
    d = cfg.data
    kw = {"dbname": d["database"], "host": d["pg_host"], "autocommit": True, "row_factory": dict_row,
          "options": f"-c search_path={d['tenant']},maludb_core,public"}
    if d.get("pg_user"):
        kw["user"] = d["pg_user"]
    kw.update(remote_kwargs(d))
    conn = psycopg.connect(**kw)
    if d.get("pg_role"):
        conn.execute(pgsql.SQL("SET ROLE {}").format(pgsql.Identifier(d["pg_role"])))
    return conn


def _rank(s):
    return SENSITIVITY.get(s or "internal", 1)


def _max_sens(values):
    """The highest classification among values (internal when none): what a batch of texts is embedded as."""
    best = "internal"
    for v in values:
        if v in SENSITIVITY and _rank(v) > _rank(best):
            best = v
    return best


class Embedder:
    """Vectors for the engine's semantic rail (maludb-core: malu$object_embedding, maludb_register_object_embedding,
    maludb_semantic_search), computed outside the database: the engine never calls a model. The face asks the gateway over
    its socket as user:maluos-memory (a model call in the gateway's ledger like any other), or a URL the configuration names.
    One model per space (memory/<model>): changing the model is a new space, old vectors never mix with new ones. On any
    failure the answer is None and recall is text alone; the last failure is kept for `maluctl memory embed`."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.last_error, self.last_error_at, self.last_ok_at, self.dim = None, None, None, None

    def conf(self):
        return self.cfg.get("embed") or {}

    @property
    def model(self):
        m = self.conf().get("model")
        return str(m) if m else None

    @property
    def space(self):
        return f"memory/{self.model}" if self.model else None

    @staticmethod
    def pack(vec):
        return struct.pack(f"<{len(vec)}f", *[float(x) for x in vec])

    @staticmethod
    def text_of(title, summary):
        return ((title or "").strip() + " " + (summary or "").strip()).strip()

    def embed(self, texts, sensitivity="internal"):
        """A list of float vectors for the texts, or None (the error kept). sensitivity is the texts' highest classification,
        sent as the call's: the gateway's egress policy and the rungs' ceilings apply to it, so a restricted note is embedded
        on this host or not at all (a URL embedder is the operator's own choice: nothing is sent with the texts)."""
        model = self.model
        if not model or not texts:
            return None
        c = self.conf()
        url = str(c.get("url") or "gateway")
        timeout = float(c.get("timeout_s") or 5.0)
        try:
            if url == "gateway":
                vecs = self._gateway(model, texts, str(c.get("gateway_socket") or DEFAULTS["embed"]["gateway_socket"]), timeout, sensitivity)
            elif url.rstrip("/").endswith("/api/embed"):
                d = self._http(url, {"model": model, "input": texts}, timeout)
                vecs = d.get("embeddings") or []
            else:
                d = self._http(url, {"model": model, "input": texts}, timeout)
                vecs = [x.get("embedding") for x in sorted(d.get("data") or [], key=lambda x: x.get("index", 0))]
            if len(vecs) != len(texts) or not all(isinstance(v, list) and v for v in vecs):
                raise ValueError(f"the embedder answered {len(vecs)} vector(s) for {len(texts)} text(s)")
            self.dim, self.last_ok_at = len(vecs[0]), utc()
            return vecs
        except Exception as e:
            self.last_error, self.last_error_at = f"{e.__class__.__name__}: {str(e)[:160]}", utc()
            return None

    @staticmethod
    def _http(url, body, timeout):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    @staticmethod
    def _gateway(model, texts, sock_path, timeout, sensitivity="internal"):
        class U(http.client.HTTPConnection):
            def connect(self):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout); s.connect(sock_path); self.sock = s
        c = U("maluos-gateway", timeout=timeout)
        try:
            c.request("POST", "/v1/embeddings", body=json.dumps({"model": model, "input": texts}),
                      headers={"Content-Type": "application/json", "X-MaluOS-Sensitivity": str(sensitivity or "internal")})
            r = c.getresponse(); data = r.read()
            if r.status != 200:
                try:
                    err = (json.loads(data or b"{}").get("error") or {})
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                except ValueError:
                    msg = data[:120].decode("utf-8", "replace")
                raise RuntimeError(f"gateway {r.status}: {msg}")
            d = json.loads(data or b"{}")
        finally:
            c.close()
        return [x.get("embedding") for x in sorted(d.get("data") or [], key=lambda x: x.get("index", 0))]


class Engine:
    def __init__(self, cfg, embedder=None):
        self.cfg, self.lock, self._conn = cfg, threading.RLock(), None
        self.embedder = embedder or Embedder(cfg)

    # -- the semantic rail (slice 4b)
    def register_vector(self, conn, memory_id, vec):
        """Inside an open transaction: the memory's vector in the active space (an upsert on the engine's object-embedding rail)."""
        conn.execute("SELECT maludb_register_object_embedding('memory', %s, %s, %s, %s, %s, 'title_summary', NULL, 'provided')",
                     (int(memory_id), self.embedder.pack(vec), len(vec), self.embedder.space, self.embedder.model))

    def semantic_ids(self, conn, qvec, k):
        """Inside a bound transaction: (memory_id, score) of the nearest memories in the active space the principal may see,
        at or above min_score; the engine's search applies the memory policy as the invoker."""
        floor = float((self.cfg.get("embed") or {}).get("min_score") or 0.0)
        rows = conn.execute("SELECT object_id, score FROM maludb_semantic_search(%s, ARRAY['memory'], %s, %s, 'cosine')",
                            (self.embedder.pack(qvec), int(k), self.embedder.space)).fetchall()
        return [(int(r["object_id"]), float(r["score"])) for r in rows if r["score"] is not None and float(r["score"]) >= floor]

    def embed_status(self):
        """The model, the space and how much of this host's memory carries a vector in it."""
        e = self.embedder
        out = {"model": e.model, "space": e.space, "url": (self.cfg.get("embed") or {}).get("url") or "gateway", "min_score": (self.cfg.get("embed") or {}).get("min_score"),
               "dim": e.dim, "last_ok_at": e.last_ok_at, "last_error": e.last_error, "last_error_at": e.last_error_at, "total": 0, "embedded": 0}
        if not e.model:
            return out

        def go(conn):
            r = conn.execute("""SELECT count(*) AS total,
                                       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM maludb_core."malu$object_embedding" oe WHERE oe.object_kind = 'memory'
                                                                      AND oe.object_id = m.memory_id AND oe.embedding_space = %s)) AS embedded
                                  FROM maludb_memory m WHERE m.lifecycle_state <> 'tombstoned'""", (e.space,)).fetchone()
            return int(r["total"]), int(r["embedded"])
        out["total"], out["embedded"] = self.run(go)
        return out

    def backfill(self, batch=16, limit=2000):
        """Vectors for the memories that lack one in the active space (an operator's `maluctl memory embed --backfill`, and the
        keeper's hourly pass): embedded in batches, registered as the face. Returns the counts."""
        e = self.embedder
        if not e.model:
            return {"embedded": 0, "failed": 0, "remaining": 0, "note": "no embedding model configured"}

        def pending(conn):
            return conn.execute("""SELECT m.memory_id, m.title, m.summary, m.sensitivity FROM maludb_memory m
                                    WHERE m.lifecycle_state <> 'tombstoned' AND NOT EXISTS (SELECT 1 FROM maludb_core."malu$object_embedding" oe
                                          WHERE oe.object_kind = 'memory' AND oe.object_id = m.memory_id AND oe.embedding_space = %s)
                                    ORDER BY m.sensitivity, m.memory_id LIMIT %s""", (e.space, int(limit))).fetchall()   # batches of one classification, mostly
        rows = self.run(pending)
        done = failed = 0
        for i in range(0, len(rows), int(batch)):
            chunk = rows[i:i + int(batch)]
            vecs = e.embed([e.text_of(r["title"], r["summary"]) or "(empty)" for r in chunk], _max_sens(r["sensitivity"] for r in chunk))
            if not vecs:
                failed += len(rows) - i
                break

            def write(conn, chunk=chunk, vecs=vecs):
                with conn.transaction():
                    for r, v in zip(chunk, vecs):
                        self.register_vector(conn, r["memory_id"], v)
            self.run(write)
            done += len(chunk)
        return {"embedded": done, "failed": failed, "remaining": max(0, len(self.run(pending))), "error": e.last_error if failed else None}

    # -- connections
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = connect(self.cfg)
        return self._conn

    def run(self, fn):
        """fn(conn) under the lock; one reconnect on a dropped connection."""
        with self.lock:
            try:
                return fn(self.conn())
            except psycopg.OperationalError:
                try:
                    if self._conn is not None:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None
                return fn(self.conn())

    @staticmethod
    def bind(conn, ref, scopes, readonly=True):
        """Inside an open transaction: the principal, its narrowing list and the readonly flag, transaction-local."""
        conn.execute("SELECT set_config('maludb_core.principal_ref', %s, true), set_config('maludb_core.principal_scopes', %s, true), "
                     "set_config('maludb_core.principal_readonly', %s, true)", (ref, json.dumps(sorted(set(scopes))), "on" if readonly else "off"))

    # -- principals (unbound reads of the tenant's principal views)
    def principal(self, ref):
        def go(conn):
            row = conn.execute("SELECT principal_ref, principal_kind, display_name, home_scope, max_sensitivity, enabled FROM maludb_principal WHERE principal_ref = %s", (ref,)).fetchone()
            if not row:
                return None
            reads, writes = set(), set()
            if row["home_scope"]:
                reads.add(row["home_scope"]); writes.add(row["home_scope"])
            for g in conn.execute("SELECT scope, access_level FROM maludb_principal_scope WHERE principal_ref = %s AND revoked_at IS NULL", (ref,)).fetchall():
                reads.add(g["scope"])
                if g["access_level"] == "write":
                    writes.add(g["scope"])
            return {"ref": row["principal_ref"], "kind": row["principal_kind"], "display_name": row["display_name"], "home_scope": row["home_scope"],
                    "max_sensitivity": row["max_sensitivity"] or "internal", "enabled": bool(row["enabled"]), "read": sorted(reads), "write": sorted(writes)}
        return self.run(go)

    def owns_agent(self, owner_ref, agent_ref):
        def go(conn):
            try:
                return conn.execute("SELECT 1 FROM maluos_agent WHERE principal_ref = %s AND owner_principal_ref = %s AND removed_at IS NULL", (agent_ref, owner_ref)).fetchone() is not None
            except psycopg.Error:
                return False
        return self.run(go)

    def guest(self):
        """What this host serves: the guest principal's read grants (the shared scopes) and its ceiling."""
        p = self.principal(self.cfg["guest"])
        if not p:
            return {"principal": self.cfg["guest"], "present": False, "shared": [], "max_classification": "internal"}
        return {"principal": p["ref"], "present": True, "enabled": p["enabled"], "shared": sorted(s for s in p["read"] if shareable(s)), "max_classification": p["max_sensitivity"]}

    # -- the facts the heartbeat carries
    def facts(self, port, exposed):
        def go(conn):
            rows = conn.execute("""SELECT scope, memory_kind, count(*) AS n, max(recorded_at) AS last
                                     FROM maludb_memory WHERE scope ~ %s AND lifecycle_state <> 'tombstoned' GROUP BY scope, memory_kind""", (SCOPE_SHAREABLE,)).fetchall()
            by = {}
            for r in rows:
                s = by.setdefault(r["scope"], {"scope": r["scope"], "count": 0, "updated_at": None, "kinds": {}})
                s["count"] += int(r["n"]); s["kinds"][r["memory_kind"]] = int(r["n"])
                if r["last"] is not None and (s["updated_at"] is None or utc(r["last"]) > s["updated_at"]):
                    s["updated_at"] = utc(r["last"])
            return [by[k] for k in sorted(by)]
        g = self.guest()
        return {"scopes": self.run(go), "shared": g["shared"], "max_classification": g["max_classification"], "port": int(port), "api_version": API_VERSION, "exposed": bool(exposed)}

    # -- claims
    @staticmethod
    def claim(r, holder, rank, detail=False):
        p = r.get("payload_jsonb") or {}
        c = {"id": int(r["memory_id"]), "text": r.get("summary") or r.get("title") or "", "title": r.get("title"), "scope": r.get("scope"), "kind": r.get("memory_kind"),
             "sensitivity": r.get("sensitivity") or "internal", "confidence": p.get("confidence") if isinstance(p.get("confidence"), (int, float)) else None,
             "observed_at": utc(r["occurred_at"]) if r.get("occurred_at") else None, "recorded_at": utc(r["recorded_at"]) if r.get("recorded_at") else None,
             "source": {"node": holder, "object": "memory", "id": int(r["memory_id"]), "ref": p.get("source") if isinstance(p.get("source"), str) else None},
             "writer": r.get("principal_ref"), "holder": holder, "rank": rank}
        if isinstance(p.get("origin"), dict):
            c["origin"] = p["origin"]
        if detail:
            c["detail"] = p.get("detail")
        return c

    def recall(self, ref, scopes, query, limit, classification="internal", holder=None, detail=False, kinds=None):
        """The memories the principal may read in these scopes that match the query, as claims; the engine's view holds the
        principal's grants and ceiling, the request's classification narrows further."""
        scopes = sorted(set(scopes))
        if not scopes:
            return []

        q = query.strip()
        qvec = (self.embedder.embed([q], classification) or [None])[0] if self.embedder.model else None   # outside the lock and the transaction

        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, scopes, readonly=True)
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(int(self.cfg["query_timeout_s"] * 1000)),))
                like = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
                # slice 4b: the nearest memories in the active space (the engine's search sees what the principal sees), re-read
                # through the view with the same scope, ceiling, kind and tombstone filters as the text hits; the union, semantic first
                sem = self.semantic_ids(conn, qvec, max(int(limit) * 3, 10)) if qvec else []
                rows = conn.execute("""
                    SELECT m.memory_id, m.memory_kind, m.title, m.summary, m.payload_jsonb, m.occurred_at, m.recorded_at, m.sensitivity, m.principal_ref, m.scope,
                           ts_rank_cd(to_tsvector('simple', coalesce(m.title, '') || ' ' || coalesce(m.summary, '')), plainto_tsquery('simple', %(q)s)) AS rank,
                           s.score
                      FROM maludb_memory m
                      LEFT JOIN unnest(%(sem_ids)s::bigint[], %(sem_scores)s::float8[]) AS s(id, score) ON s.id = m.memory_id
                     WHERE m.scope = ANY(%(scopes)s) AND m.lifecycle_state <> 'tombstoned'
                       AND (CASE m.sensitivity WHEN 'public' THEN 0 WHEN 'internal' THEN 1 WHEN 'restricted' THEN 2 ELSE 3 END) <= %(ceil)s
                       AND (%(kinds)s::text[] IS NULL OR m.memory_kind = ANY(%(kinds)s::text[]))
                       AND (s.id IS NOT NULL
                            OR to_tsvector('simple', coalesce(m.title, '') || ' ' || coalesce(m.summary, '')) @@ plainto_tsquery('simple', %(q)s)
                            OR coalesce(m.title, '') ILIKE %(like)s OR coalesce(m.summary, '') ILIKE %(like)s)
                     ORDER BY s.score DESC NULLS LAST, rank DESC, m.recorded_at DESC NULLS LAST, m.memory_id DESC
                     LIMIT %(limit)s""", {"q": q, "scopes": scopes, "ceil": _rank(classification), "kinds": list(kinds) if kinds else None, "like": like, "limit": int(limit),
                                          "sem_ids": [i for i, _ in sem], "sem_scores": [sc for _, sc in sem]}).fetchall()
            out = []
            for i, r in enumerate(rows):
                c = self.claim(r, holder, i + 1, detail)
                c["match"] = "semantic" if r.get("score") is not None else "text"
                c["score"] = round(float(r["score"]), 3) if r.get("score") is not None else None
                out.append(c)
            return out
        return self.run(go)

    def recent(self, ref, scopes, limit=50, holder=None, kinds=None):
        """The newest memories the principal may read in these scopes (no query): what an agent remembers, for the Agents app."""
        scopes = sorted(set(scopes))
        if not scopes:
            return []

        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, scopes, readonly=True)
                rows = conn.execute("""SELECT memory_id, memory_kind, title, summary, payload_jsonb, occurred_at, recorded_at, sensitivity, principal_ref, scope
                                         FROM maludb_memory WHERE scope = ANY(%s) AND lifecycle_state <> 'tombstoned'
                                          AND (%s::text[] IS NULL OR memory_kind = ANY(%s::text[]))
                                        ORDER BY recorded_at DESC, memory_id DESC LIMIT %s""", (scopes, list(kinds) if kinds else None, list(kinds) if kinds else None, int(limit))).fetchall()
            return [self.claim(r, holder, i + 1) for i, r in enumerate(rows)]
        return self.run(go)

    def remember(self, ref, scope, text, kind="note", title=None, confidence=None, source=None, sensitivity="internal", detail=None, occurred_at=None):
        if not isinstance(text, str) or not text.strip() or len(text) > TEXT_MAX:
            raise EngineError(400, "invalid", f"text is 1 to {TEXT_MAX} characters")
        if kind not in KINDS:
            raise EngineError(400, "invalid", f"kind is one of {', '.join(KINDS)}")
        if sensitivity not in SENSITIVITY:
            raise EngineError(400, "invalid", "sensitivity is public, internal, restricted or prohibited")
        if detail is not None and len(json.dumps(detail)) > DETAIL_MAX:
            raise EngineError(400, "invalid", "detail is over 16 KB")
        payload = {}
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                raise EngineError(400, "invalid", "confidence is a number from 0 to 1")
            if not 0 <= confidence <= 1:
                raise EngineError(400, "invalid", "confidence is a number from 0 to 1")
            payload["confidence"] = confidence
        if source:
            payload["source"] = str(source)[:300]
        if detail is not None:
            payload["detail"] = detail

        vec = (self.embedder.embed([self.embedder.text_of(title, text)], sensitivity) or [None])[0] if self.embedder.model else None   # before the lock

        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, [scope], readonly=False)
                try:
                    row = conn.execute("""INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, occurred_at, sensitivity, scope)
                                          VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s) RETURNING memory_id, recorded_at""",
                                       (kind, title, text.strip(), json.dumps(payload), occurred_at, sensitivity, scope)).fetchone()
                    if vec:
                        self.register_vector(conn, row["memory_id"], vec)
                except psycopg.errors.InsufficientPrivilege as e:
                    msg = str(e).splitlines()[0][:160]
                    if "may not write" not in msg:
                        raise EngineError(500, "internal", f"the face's role lacks a grant: {msg}")
                    raise EngineError(403, "scope_write", f"{ref} may not write {scope}: {msg}")
                except psycopg.errors.WithCheckOptionViolation:
                    # the stamp trigger allowed the scope; the facade's check option refused a row the writer could not read back:
                    # a sensitivity above the principal's ceiling (maludb_principal.max_sensitivity)
                    raise EngineError(403, "classification", f"{ref} may not write {sensitivity} into {scope}: above its ceiling")
            return {"id": int(row["memory_id"]), "recorded_at": utc(row["recorded_at"]), "scope": scope, "kind": kind, "embedded": bool(vec)}
        return self.run(go)

    def forget(self, ref, memory_id):
        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, self.principal(ref)["write"] if self.principal(ref) else [], readonly=False)
                row = conn.execute("SELECT memory_id, scope, payload_jsonb FROM maludb_memory WHERE memory_id = %s AND lifecycle_state <> 'tombstoned'", (int(memory_id),)).fetchone()
                if not row:
                    raise EngineError(404, "not_found", f"no memory {memory_id} you may read")
                if isinstance((row.get("payload_jsonb") or {}).get("origin"), dict):
                    raise EngineError(409, "origin", "a replicated copy is forgotten where it was written; `maluctl memory sync` keeps it in step")
                try:
                    conn.execute("UPDATE maludb_memory SET lifecycle_state = 'tombstoned', updated_at = now() WHERE memory_id = %s", (int(memory_id),))
                except psycopg.errors.InsufficientPrivilege as e:
                    msg = str(e).splitlines()[0][:160]
                    if "may not" not in msg:
                        raise EngineError(500, "internal", f"the face's role lacks a grant: {msg}")
                    raise EngineError(403, "scope_write", f"{ref} may not change {row['scope']}: {msg}")
            return {"id": int(memory_id), "forgotten": True}
        return self.run(go)

    def summaries(self, ref, scope, since=None, limit=200, holder=None):
        """A scope's summaries for replication (bound to the guest): kind summary, newest first, after `since`; never a copy this
        host itself replicated (provenance stays with the origin: a copy of a copy is a loop on a host that is both sides)."""
        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, [scope], readonly=True)
                rows = conn.execute("""SELECT memory_id, memory_kind, title, summary, payload_jsonb, occurred_at, recorded_at, updated_at, sensitivity, principal_ref, scope
                                         FROM maludb_memory WHERE scope = %s AND memory_kind = 'summary' AND lifecycle_state <> 'tombstoned'
                                          AND NOT (payload_jsonb ? 'origin')
                                          AND (%s::timestamptz IS NULL OR updated_at > %s::timestamptz)
                                        ORDER BY updated_at DESC, memory_id DESC LIMIT %s""", (scope, since, since, int(limit))).fetchall()
                gone = conn.execute("""SELECT memory_id FROM maludb_memory WHERE scope = %s AND memory_kind = 'summary' AND lifecycle_state = 'tombstoned'
                                        AND NOT (payload_jsonb ? 'origin') AND (%s::timestamptz IS NULL OR updated_at > %s::timestamptz) LIMIT 1000""", (scope, since, since)).fetchall()
            out = []
            for i, r in enumerate(rows):
                c = self.claim(r, holder, i + 1)
                c["version"] = utc(r["updated_at"]) if r.get("updated_at") else c["recorded_at"]
                out.append(c)
            return out, [int(g["memory_id"]) for g in gone]
        return self.run(go)

    def sync_write(self, origin_node, scope, items, gone):
        """Copies of a holder's summaries into this tenant (unbound: the face is the writer, as principal estate:sync), each with
        payload.origin; a copy whose origin changed is replaced, one the holder retracted is tombstoned. Returns counts."""
        sync_ref = self.cfg["sync_principal"]
        vecs = {}
        if self.embedder.model and items:
            got = self.embedder.embed([self.embedder.text_of(c.get("title"), c.get("text")) or "(empty)" for c in items], _max_sens(c.get("sensitivity") for c in items))
            if got:
                vecs = {id(c): v for c, v in zip(items, got)}

        def go(conn):
            written = replaced = removed = 0
            with conn.transaction():
                for c in items:
                    origin = {"node": origin_node, "id": int(c["id"]), "version": c.get("version"), "copied_at": utc()}
                    old = conn.execute("SELECT memory_id, payload_jsonb FROM maludb_memory WHERE scope = %s AND payload_jsonb->'origin'->>'node' = %s AND (payload_jsonb->'origin'->>'id')::bigint = %s AND lifecycle_state <> 'tombstoned'",
                                       (scope, origin_node, int(c["id"]))).fetchall()
                    if old and all(((o.get("payload_jsonb") or {}).get("origin") or {}).get("version") == c.get("version") for o in old):
                        continue
                    for o in old:
                        conn.execute("UPDATE maludb_memory SET lifecycle_state = 'tombstoned', updated_at = now() WHERE memory_id = %s", (o["memory_id"],)); replaced += 1
                    payload = {"origin": origin}
                    if c.get("confidence") is not None:
                        payload["confidence"] = c["confidence"]
                    if (c.get("source") or {}).get("ref"):
                        payload["source"] = c["source"]["ref"]
                    new = conn.execute("""INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, occurred_at, sensitivity, scope, principal_ref)
                                          VALUES ('summary', %s, %s, %s::jsonb, %s, %s, %s, %s) RETURNING memory_id""",
                                       (c.get("title"), c.get("text") or "", json.dumps(payload), c.get("observed_at"), c.get("sensitivity") or "internal", scope, sync_ref)).fetchone()
                    if vecs.get(id(c)):
                        self.register_vector(conn, new["memory_id"], vecs[id(c)])
                    written += 1
                for gid in gone or []:
                    r = conn.execute("UPDATE maludb_memory SET lifecycle_state = 'tombstoned', updated_at = now() WHERE scope = %s AND payload_jsonb->'origin'->>'node' = %s AND (payload_jsonb->'origin'->>'id')::bigint = %s AND lifecycle_state <> 'tombstoned'",
                                     (scope, origin_node, int(gid)))
                    removed += r.rowcount
            return {"written": written, "replaced": replaced, "removed": removed}
        return self.run(go)

    def copies(self):
        """What this host holds by replication: per origin node and scope, the count and the newest version."""
        def go(conn):
            return [dict(r, count=int(r["count"])) for r in conn.execute("""SELECT payload_jsonb->'origin'->>'node' AS node, scope, count(*) AS count, max(payload_jsonb->'origin'->>'version') AS version
                                                                               FROM maludb_memory WHERE payload_jsonb ? 'origin' AND lifecycle_state <> 'tombstoned' GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()]
        return self.run(go)

    # -- the ledger (the vault's table; the face writes its own rows as the gateway does)
    def ledger(self, event, principal_ref=None, status="ok", reason=None, purpose=None, route=None, detail=None, task_ref=None, linux_user=None, linux_uid=None, process_ref=None):
        def go(conn):
            conn.execute("""INSERT INTO maluos_ledger (event, principal_ref, linux_user, linux_uid, process_ref, status, reason, purpose, route, detail, task_ref)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)""",
                         (event, principal_ref, linux_user, linux_uid, process_ref, status, reason, purpose, json.dumps(route) if route is not None else None,
                          json.dumps(detail) if detail is not None else None, task_ref))
        try:
            self.run(go)
        except Exception as e:
            from .server import log
            log(f"ledger: {e.__class__.__name__}: {str(e)[:120]}")

    def ledger_rows(self, principal=None, since=None, limit=100):
        def go(conn):
            rows = conn.execute("""SELECT ledger_id, ts, event, principal_ref, linux_user, process_ref, status, reason, purpose, route, detail, task_ref
                                     FROM maluos_ledger WHERE event LIKE 'memory.%%' AND (%s::text IS NULL OR principal_ref = %s OR detail->>'originator' = %s)
                                      AND (%s::timestamptz IS NULL OR ts >= %s::timestamptz) ORDER BY ledger_id DESC LIMIT %s""",
                                (principal, principal, principal, since, since, int(limit))).fetchall()
            return [dict(r, ts=utc(r["ts"]) if r.get("ts") else None) for r in rows]
        return self.run(go)
