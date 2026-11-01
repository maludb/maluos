"""The engine behind the face: PostgreSQL as the face's own role (maluos-memory, peer-authenticated), the tenant's
memory facades, and every read or write bound to a principal and a scope set for the length of one transaction
(maludb-core 0.106.0 principal scoping, docs/principal-scoping.md there). Nothing here decides who may ask what:
the server does, and hands the engine the principal and the scopes it settled on."""
import datetime, json, os, re, threading, time
import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row

from . import SENSITIVITY, SCOPE_SHAREABLE, API_VERSION, DEFAULT_PORT

CONF = os.environ.get("MALUOS_MEMORY_CONFIG", "/etc/maluos/memory.yaml")
VAULT_CONF = os.environ.get("MALUOS_VAULT_CONF", "/etc/maluos/vault.yaml")
DEFAULTS = {"database": "maludb", "tenant": "maluos", "pg_host": "/var/run/postgresql", "pg_user": None, "pg_role": None,
            "socket": "/run/maluos/memory.sock", "tcp": {"enabled": False, "host": "overlay", "port": DEFAULT_PORT},
            "guest": "estate:guest", "sync_principal": "estate:sync", "fanout_s": 5.0, "fanout_max": 8, "sync_every_s": 3600, "query_timeout_s": 10,
            "ask_self": False}   # a host never asks (or replicates from) its own identities; tests on one host set it
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


def connect(cfg):
    d = cfg.data
    kw = {"dbname": d["database"], "host": d["pg_host"], "autocommit": True, "row_factory": dict_row,
          "options": f"-c search_path={d['tenant']},maludb_core,public"}
    if d.get("pg_user"):
        kw["user"] = d["pg_user"]
    conn = psycopg.connect(**kw)
    if d.get("pg_role"):
        conn.execute(pgsql.SQL("SET ROLE {}").format(pgsql.Identifier(d["pg_role"])))
    return conn


def _rank(s):
    return SENSITIVITY.get(s or "internal", 1)


class Engine:
    def __init__(self, cfg):
        self.cfg, self.lock, self._conn = cfg, threading.RLock(), None

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

        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, scopes, readonly=True)
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(int(self.cfg["query_timeout_s"] * 1000)),))
                q = query.strip()
                like = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
                rows = conn.execute("""
                    SELECT memory_id, memory_kind, title, summary, payload_jsonb, occurred_at, recorded_at, sensitivity, principal_ref, scope,
                           ts_rank_cd(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '')), plainto_tsquery('simple', %(q)s)) AS rank
                      FROM maludb_memory
                     WHERE scope = ANY(%(scopes)s) AND lifecycle_state <> 'tombstoned'
                       AND (CASE sensitivity WHEN 'public' THEN 0 WHEN 'internal' THEN 1 WHEN 'restricted' THEN 2 ELSE 3 END) <= %(ceil)s
                       AND (%(kinds)s::text[] IS NULL OR memory_kind = ANY(%(kinds)s::text[]))
                       AND (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '')) @@ plainto_tsquery('simple', %(q)s)
                            OR coalesce(title, '') ILIKE %(like)s OR coalesce(summary, '') ILIKE %(like)s)
                     ORDER BY rank DESC, recorded_at DESC NULLS LAST, memory_id DESC
                     LIMIT %(limit)s""", {"q": q, "scopes": scopes, "ceil": _rank(classification), "kinds": list(kinds) if kinds else None, "like": like, "limit": int(limit)}).fetchall()
            return [self.claim(r, holder, i + 1, detail) for i, r in enumerate(rows)]
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

        def go(conn):
            with conn.transaction():
                self.bind(conn, ref, [scope], readonly=False)
                try:
                    row = conn.execute("""INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, occurred_at, sensitivity, scope)
                                          VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s) RETURNING memory_id, recorded_at""",
                                       (kind, title, text.strip(), json.dumps(payload), occurred_at, sensitivity, scope)).fetchone()
                except psycopg.errors.InsufficientPrivilege as e:
                    msg = str(e).splitlines()[0][:160]
                    if "may not write" not in msg:
                        raise EngineError(500, "internal", f"the face's role lacks a grant: {msg}")
                    raise EngineError(403, "scope_write", f"{ref} may not write {scope}: {msg}")
                except psycopg.errors.WithCheckOptionViolation:
                    # the stamp trigger allowed the scope; the facade's check option refused a row the writer could not read back:
                    # a sensitivity above the principal's ceiling (maludb_principal.max_sensitivity)
                    raise EngineError(403, "classification", f"{ref} may not write {sensitivity} into {scope}: above its ceiling")
            return {"id": int(row["memory_id"]), "recorded_at": utc(row["recorded_at"]), "scope": scope, "kind": kind}
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
                    conn.execute("""INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, occurred_at, sensitivity, scope, principal_ref)
                                    VALUES ('summary', %s, %s, %s::jsonb, %s, %s, %s, %s)""",
                                 (c.get("title"), c.get("text") or "", json.dumps(payload), c.get("observed_at"), c.get("sensitivity") or "internal", scope, sync_ref))
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
