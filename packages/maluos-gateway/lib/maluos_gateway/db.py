"""Database access for the gateway: the catalogue (backends, tiers, aliases,
classes, policies), principals and tokens, the ledger, status publishing,
and the engine's model request queue."""
import asyncio, hashlib, json, time
import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row


class Catalog:
    def __init__(self, backends, tiers, aliases, classes, policies, prices=()):
        self.backends = {b["name"]: b for b in backends}
        self.tiers = {t["name"]: t for t in tiers}
        self.aliases = aliases
        self.classes = {c["name"]: c for c in classes}
        self.policies = policies
        self.prices = {(p["backend"], p["model"]): p for p in prices}
        self.loaded_at = time.time()

    def default_class(self):
        if not self.classes:
            return "interactive"
        return sorted(self.classes.values(), key=lambda c: c["priority"])[0]["name"]

    def candidates(self, requested, known_models):
        """[(backend, model, reason)] in ladder order for a requested name."""
        if requested in self.tiers:
            rows = sorted((a for a in self.aliases if a["tier"] == requested and a["enabled"]), key=lambda a: (a["position"], a["name"]))
            return [(a["backend"], a["model"], f"tier {requested}") for a in rows if self.backends.get(a["backend"], {}).get("enabled")]
        rows = sorted((a for a in self.aliases if a["name"] == requested and a["enabled"] and a["tier"] is None), key=lambda a: a["position"])
        if rows:
            return [(a["backend"], a["model"], "alias") for a in rows if self.backends.get(a["backend"], {}).get("enabled")]
        out = []
        for name, models in known_models.items():
            b = self.backends.get(name)
            if b and b["enabled"] and (requested in models or requested + ":latest" in models):
                out.append((name, requested, "direct"))
        # local backends first, then remote nodes, then cloud, as a stable default ladder for bare model names
        cloud = ("anthropic", "openai", "openai_compat", "ollama_cloud")
        return sorted(out, key=lambda c: (self.backends[c[0]]["kind"] in cloud, self.backends[c[0]]["kind"] == "remote", c[0]))

    def policy_for(self, principal_ref, scopes=()):
        merged = {"allowed_tiers": None, "allowed_backends": None, "cloud_allowed": True, "remote_allowed": True, "default_class": None,
                  "max_egress_sensitivity": None, "ladder": None, "budget": None}
        layers = [p for p in self.policies if p["subject_kind"] == "default"]
        layers += [p for p in self.policies if p["subject_kind"] == "scope" and p["subject_ref"] in set(scopes)]
        layers += [p for p in self.policies if p["subject_kind"] == "principal" and p["subject_ref"] == principal_ref]
        for p in layers:
            for k in merged:
                if p.get(k) is not None:
                    merged[k] = p[k]
        return merged


class Database:
    def __init__(self, cfg):
        self.cfg = cfg
        self._conn = None
        self._lock = asyncio.Lock()

    async def _connect(self):
        d = self.cfg.data
        kw = {"dbname": d["database"], "host": d["pg_host"], "autocommit": True, "row_factory": dict_row,
              "options": f"-c search_path={d['tenant']},maludb_core,public"}
        if d.get("pg_user"):
            kw["user"] = d["pg_user"]
        conn = await psycopg.AsyncConnection.connect(**kw)
        if d.get("pg_role"):
            await conn.execute(pgsql.SQL("SET ROLE {}").format(pgsql.Identifier(d["pg_role"])))
        return conn

    async def connection(self):
        """A fresh, independent connection (for transactions / the drain loop)."""
        return await self._connect()

    async def run(self, fn):
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = await self._connect()
                    return await fn(self._conn)
                except psycopg.OperationalError:
                    try:
                        await self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    if attempt == 2:
                        raise

    async def fetch(self, sql, params=()):
        async def f(conn):
            cur = await conn.execute(sql, params)
            return await cur.fetchall()
        return await self.run(f)

    async def fetchone(self, sql, params=()):
        rows = await self.fetch(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql, params=()):
        async def f(conn):
            cur = await conn.execute(sql, params)
            return cur.rowcount
        return await self.run(f)

    # -- catalogue and identity
    async def load_catalog(self):
        return Catalog(
            await self.fetch("SELECT * FROM maluos_backend ORDER BY name"),
            await self.fetch("SELECT * FROM maluos_tier ORDER BY name"),
            await self.fetch("SELECT * FROM maluos_alias ORDER BY tier NULLS LAST, position, name"),
            await self.fetch("SELECT * FROM maluos_class ORDER BY priority"),
            await self.fetch("SELECT * FROM maluos_policy"),
            await self.fetch("SELECT * FROM maluos_price"))

    async def principal(self, ref):
        return await self.fetchone("SELECT principal_ref, principal_kind, home_scope, max_sensitivity, enabled FROM maludb_principal WHERE principal_ref=%s", (ref,))

    async def principal_scopes(self, ref, home_scope=None):
        rows = await self.fetch("SELECT scope FROM maludb_principal_scope WHERE principal_ref=%s AND revoked_at IS NULL", (ref,))
        s = {r["scope"] for r in rows}
        if home_scope:
            s.add(home_scope)
        return s

    async def token_lookup(self, token):
        h = hashlib.sha256(token.encode()).hexdigest()
        row = await self.fetchone("""SELECT token_id, principal_ref, name, kind, limits FROM maluos_token
                                     WHERE token_hash=%s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())""", (h,))
        if row:
            await self.execute("UPDATE maluos_token SET last_used_at=now() WHERE token_id=%s", (row["token_id"],))
        return row

    # -- ledger
    LEDGER_COLS = {"event", "principal_ref", "linux_user", "linux_uid", "process_ref", "broker_ref", "compartment", "secret_name",
                   "secret_id", "grant_level", "purpose", "status", "reason", "class", "tier", "requested_model", "route", "attempts",
                   "backend", "model", "queue_wait_ms", "service_ms", "gpu_ms", "tokens_in", "tokens_out", "tokens_cached",
                   "cost_est", "cost_actual", "currency", "error_class", "provider_request_id", "task_ref", "episode_id", "detail"}

    async def ledger(self, **f):
        cols = [k for k in f if k in self.LEDGER_COLS and f[k] is not None]
        vals = [json.dumps(f[k]) if k in ("route", "detail") else f[k] for k in cols]
        q = pgsql.SQL("INSERT INTO maluos_ledger ({}) VALUES ({}) RETURNING ledger_id").format(
            pgsql.SQL(", ").join(map(pgsql.Identifier, cols)), pgsql.SQL(", ").join(pgsql.Placeholder() * len(cols)))
        row = await self.fetchone(q, vals)
        return row["ledger_id"] if row else None

    async def publish_status(self, status):
        await self.execute("""INSERT INTO maluos_gateway_status (id, updated_at, status) VALUES (1, now(), %s)
                              ON CONFLICT (id) DO UPDATE SET updated_at=now(), status=EXCLUDED.status""", (json.dumps(status, default=str),))

    # -- the engine's model request queue (docs/maludb-modeld-contract.md)
    async def claim_engine_request(self, conn):
        async with conn.transaction():
            cur = await conn.execute("""
                SELECT r.request_id, r.rendered_prompt, r.generation_params, r.timeout_ms, r.cancel_requested,
                       a.alias_name, a.model_identifier, a.runtime_params, acc.account_name
                  FROM maludb_core."malu$model_request" r
                  JOIN maludb_core."malu$model_alias" a ON a.alias_id = r.alias_id
             LEFT JOIN maludb_core."malu$account" acc ON acc.account_id = r.account_id
                 WHERE r.status = 'pending'
                 ORDER BY r.submitted_at
                 LIMIT 1
                   FOR UPDATE OF r SKIP LOCKED""")
            row = await cur.fetchone()
            if not row:
                return None
            await conn.execute("""UPDATE maludb_core."malu$model_request" SET status='running', started_at=now() WHERE request_id=%s""",
                               (row["request_id"],))
            return row

    async def engine_cancel_requested(self, conn, request_id):
        cur = await conn.execute("""SELECT cancel_requested FROM maludb_core."malu$model_request" WHERE request_id=%s""", (request_id,))
        r = await cur.fetchone()
        return bool(r and r["cancel_requested"])

    async def finish_engine_request(self, conn, request_id, status, output_text=None, prompt_tokens=None, completion_tokens=None,
                                    latency_ms=None, error_class=None, user_safe_error=None, raw=None, finish_reason=None, adapter="maluos-gateway"):
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO maludb_core."malu$model_response" (request_id, status, output_text, output_hash, finish_reason,
                       raw_provider_response, prompt_tokens, completion_tokens, latency_ms, error_class, user_safe_error, adapter_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) DO NOTHING""",
                (request_id, status, output_text, hashlib.sha256((output_text or "").encode()).hexdigest() if output_text is not None else None,
                 finish_reason, json.dumps(raw) if raw is not None else None, prompt_tokens, completion_tokens, latency_ms,
                 error_class, user_safe_error, adapter))
            await conn.execute("""UPDATE maludb_core."malu$model_request" SET status=%s, finished_at=now() WHERE request_id=%s""",
                               (status, request_id))
