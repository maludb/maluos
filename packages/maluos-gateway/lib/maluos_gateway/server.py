"""The gateway daemon: OpenAI- and Ollama-compatible HTTP on a Unix socket
(peer-credential identity) and optionally TCP (bearer tokens), resolution of
tiers and aliases to backend models under the caller's policy, admission
through the per-backend scheduler, streaming passthrough, a ledger row per
call, live status, and the engine's model request queue drained as batch work."""
import asyncio, collections, json, os, pwd, secrets, signal, socket, struct, sys, time
import aiohttp, psycopg
from aiohttp import web

from . import VERSION
from .config import Config
from .db import Database
from .ollama import OllamaBackend, BackendError, usage_from
from .scheduler import Scheduler, Job, AdmissionError
from .alerts import Alerts


def log(msg):
    print(f"maluos-gateway: {msg}", file=sys.stderr, flush=True)


class ApiError(Exception):
    def __init__(self, status, code, message, **extra):
        super().__init__(message); self.status, self.code, self.message, self.extra = status, code, message, extra

    def body(self):
        return {"error": {"message": self.message, "type": self.code, "code": self.code, **self.extra}}


class Caller:
    def __init__(self, ref, linux_user=None, uid=None, process_ref=None, via="socket"):
        self.ref, self.linux_user, self.uid, self.process_ref, self.via = ref, linux_user, uid, process_ref, via
        self.enrolled, self.kind, self.scopes, self.operator, self.token_name = False, None, set(), False, None

    def as_dict(self):
        return {"principal": self.ref, "enrolled": self.enrolled, "kind": self.kind, "user": self.linux_user, "uid": self.uid,
                "process": self.process_ref, "via": self.via, "operator": self.operator, "scopes": sorted(self.scopes)}


class Call:
    """One request through the gateway: who, what was asked, where it went."""
    __slots__ = ("id", "caller", "kind", "requested", "tier", "backend", "model", "reason", "cls", "route", "task", "hints",
                 "job", "t0", "queued_ms", "endpoint", "stream", "engine_request_id", "rungs", "rung", "keys", "attempts",
                 "cost_est", "currency", "warnings")

    def __init__(self, caller, kind, requested, hints, endpoint, stream):
        self.id = f"mg-{secrets.token_hex(6)}"
        self.caller, self.kind, self.requested, self.hints, self.endpoint, self.stream = caller, kind, requested, hints, endpoint, stream
        self.tier = self.backend = self.model = self.reason = self.cls = None
        self.route, self.task, self.job, self.t0, self.queued_ms, self.engine_request_id = [], hints.get("task"), None, time.monotonic(), None, None
        self.rungs, self.rung, self.keys, self.attempts = [], None, {}, 0
        self.cost_est, self.currency, self.warnings = None, None, []


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
    return f"{comm}@{unit}" if comm and unit else (comm or unit)


# ---------------------------------------------------------------- OpenAI <-> Ollama
def openai_to_ollama_chat(body):
    msgs = []
    for m in body.get("messages") or []:
        role, content, images = m.get("role", "user"), m.get("content"), []
        if isinstance(content, list):
            parts = []
            for p in content:
                if p.get("type") == "text":
                    parts.append(p.get("text", ""))
                elif p.get("type") == "image_url":
                    url = (p.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        images.append(url.split(",", 1)[1])
            content = "\n".join(parts)
        om = {"role": "system" if role == "developer" else role, "content": content or ""}
        if images:
            om["images"] = images
        if m.get("tool_calls"):
            om["tool_calls"] = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"_raw": args}
                om["tool_calls"].append({"id": tc.get("id"), "function": {"name": fn.get("name"), "arguments": args or {}}})
        if role == "tool":
            if m.get("name"):
                om["tool_name"] = m["name"]
            if m.get("tool_call_id"):
                om["tool_call_id"] = m["tool_call_id"]
        msgs.append(om)
    opts = {}
    for src, dst in (("temperature", "temperature"), ("top_p", "top_p"), ("seed", "seed"), ("presence_penalty", "presence_penalty"),
                     ("frequency_penalty", "frequency_penalty"), ("max_tokens", "num_predict"), ("max_completion_tokens", "num_predict")):
        if body.get(src) is not None:
            opts[dst] = body[src]
    if body.get("stop"):
        opts["stop"] = [body["stop"]] if isinstance(body["stop"], str) else list(body["stop"])
    if isinstance(body.get("options"), dict):
        opts.update(body["options"])
    out = {"messages": msgs}
    if opts:
        out["options"] = opts
    if body.get("tools"):
        out["tools"] = body["tools"]
    rf = body.get("response_format")
    if isinstance(rf, dict):
        if rf.get("type") == "json_object":
            out["format"] = "json"
        elif rf.get("type") == "json_schema":
            out["format"] = (rf.get("json_schema") or {}).get("schema") or "json"
    if body.get("keep_alive") is not None:
        out["keep_alive"] = body["keep_alive"]
    return out


def needs_of(body):
    """What a request requires of a model, and rough token estimates for budgets."""
    msgs = body.get("messages") or []
    text = json.dumps(msgs) if msgs else (body.get("prompt") or "") + json.dumps(body.get("input") or "")
    opts = body.get("options") or {}
    return {"tools": bool(body.get("tools")), "vision": any(m.get("images") for m in msgs) or bool(body.get("images")),
            "context": len(text) // 4, "tokens_in_est": len(text) // 4, "tokens_out_est": opts.get("num_predict") or 1024}


def openai_tool_calls(tcs):
    out = []
    for tc in tcs or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments", {})
        out.append({"id": tc.get("id") or f"call_{secrets.token_hex(8)}", "type": "function",
                    "function": {"name": fn.get("name"), "arguments": args if isinstance(args, str) else json.dumps(args)}})
    return out


def finish_reason(res):
    if (res.get("message") or {}).get("tool_calls"):
        return "tool_calls"
    return "length" if res.get("done_reason") == "length" else "stop"


def openai_usage(res):
    u = usage_from(res)
    pi, po = u["tokens_in"] or 0, u["tokens_out"] or 0
    out = {"prompt_tokens": pi, "completion_tokens": po, "total_tokens": pi + po}
    if res.get("cached_tokens"):
        out["prompt_tokens_details"] = {"cached_tokens": res["cached_tokens"]}
    return out


def sse(obj):
    return f"data: {json.dumps(obj)}\n\n".encode()


# ---------------------------------------------------------------- the gateway
SENS = {"public": 0, "internal": 1, "restricted": 2, "prohibited": 3}
CLOUD_KINDS = ("anthropic", "openai", "openai_compat", "ollama_cloud")


class Gateway:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db = Database(cfg)
        self.catalog = None
        self.backends, self.schedulers = {}, {}
        self.session = None
        self.principal_cache, self.token_cache, self.spend_cache = {}, {}, {}
        self.routes = collections.deque(maxlen=200)
        self.started = time.time()
        self.tasks = []
        self.engine_inflight = 0
        self.alerts = Alerts(self)
        self.inflight_file = os.path.join(cfg.get("state_dir") or "/var/lib/maluos-gateway", "engine-inflight.json")
        self.inflight = set()

    # -- lifecycle
    async def start(self):
        self.session = aiohttp.ClientSession()
        await self.reload_catalog(initial=True)
        await self.recover_restart()
        for coro in (self.catalog_loop(), self.health_loop(), self.status_loop(), self.warm_loop(), self.drain_loop(), self.alerts.monitor_loop()):
            self.spawn(coro)

    # -- restart accounting (FR-47): engine requests this gateway had claimed and lost
    def save_inflight(self):
        try:
            os.makedirs(os.path.dirname(self.inflight_file), exist_ok=True)
            tmp = self.inflight_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(sorted(self.inflight), f)
            os.replace(tmp, self.inflight_file)
        except OSError as e:
            log(f"cannot save in-flight state: {e}")

    async def recover_restart(self):
        try:
            with open(self.inflight_file) as f:
                lost = [int(x) for x in json.load(f)]
        except (OSError, ValueError):
            lost = []
        if not lost:
            return
        conn = None
        finished = []
        try:
            conn = await self.db.connection()
            for rid in lost:
                cur = await conn.execute("""SELECT status FROM maludb_core."malu$model_request" WHERE request_id=%s""", (rid,))
                r = await cur.fetchone()
                if r and r["status"] == "running":
                    await self.db.finish_engine_request(conn, rid, "failed", error_class="gateway_restart", user_safe_error="the gateway restarted while this request was running")
                    finished.append(rid)
        except Exception as e:
            log(f"restart recovery: {e.__class__.__name__}: {str(e)[:160]}")
        finally:
            if conn:
                await conn.close()
        self.inflight = set(); self.save_inflight()
        await self.ledger_write({"event": "gateway.restart", "status": "ok", "reason": f"{len(finished)} engine request(s) lost", "detail": {"lost": finished, "checked": lost}})
        if finished:
            await self.alerts.fire("restart_lost_work", f"gateway restarted; {len(finished)} engine request(s) failed: {finished}", {"requests": finished})

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self.tasks.append(t)
        def done(task):
            if task in self.tasks:
                self.tasks.remove(task)
            if not task.cancelled() and task.exception():
                e = task.exception()
                log(f"task {getattr(coro, '__name__', coro)} died: {e.__class__.__name__}: {str(e)[:200]}")
        t.add_done_callback(done)
        return t

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        if self.session:
            await self.session.close()

    async def reload_catalog(self, initial=False):
        try:
            cat = await self.db.load_catalog()
        except Exception as e:
            log(f"catalogue load failed: {e.__class__.__name__}: {str(e)[:160]}")
            if initial or self.catalog is None:
                from .db import Catalog
                self.catalog = Catalog([], [], [], [], [], [])
            return
        from .cloud import make_backend
        aff, plimit = self.cfg.get("affinity"), self.cfg.get("principal_queue_limit")
        for name, row in cat.backends.items():
            if name in self.backends and self.backends[name].kind == row["kind"]:
                self.backends[name].update(row)
            else:
                self.backends[name] = make_backend(row, self.session)
                self.spawn(self.backends[name].refresh())
            self.backends[name].cooldown_s = float((self.cfg.get("health") or {}).get("cooldown_s") or 60)
            sch = self.schedulers.get(name)
            cap = self.backends[name].max_concurrent if not self.backends[name].is_cloud else int((row.get("capacity") or {}).get("max_concurrent") or 8)
            if not sch:
                sch = self.schedulers[name] = Scheduler(name, cap, cat.classes, aff, plimit)
            sch.configure(cap, cat.classes, aff, plimit)
        for name in list(self.backends):
            if name not in cat.backends:
                del self.backends[name]; self.schedulers.pop(name, None)
        self.catalog = cat

    async def catalog_loop(self):
        while True:
            await asyncio.sleep(float(self.cfg.get("catalog_reload_s") or 10))
            await self.reload_catalog()

    async def health_loop(self):
        while True:
            await asyncio.gather(*(b.refresh() for b in list(self.backends.values())), return_exceptions=True)
            await asyncio.sleep(float((self.cfg.get("health") or {}).get("probe_s") or 10))

    async def status_loop(self):
        while True:
            try:
                await self.db.publish_status(self.status())
            except Exception as e:
                log(f"status publish failed: {e.__class__.__name__}: {str(e)[:120]}")
            await asyncio.sleep(float(self.cfg.get("status_publish_s") or 5))

    async def warm_loop(self):
        await asyncio.sleep(15)
        while True:
            for b in list(self.backends.values()):
                if not b.healthy or b.kind not in ("ollama_local", "mock"):
                    continue
                want = list(b.options.get("keep_warm") or []) or (list(self.cfg["ollama"].get("keep_warm") or []) if b.kind == "ollama_local" else [])
                loaded = {m.get("name") for m in b.loaded} | {m.get("model") for m in b.loaded}
                sch = self.schedulers.get(b.name)
                for model in want:
                    if model in loaded or (model + ":latest") in loaded or not b.has_model(model):
                        continue
                    if sch and (sch.queued or sch.running):
                        break
                    try:
                        await b.warm(model)
                        log(f"warmed {model} on {b.name}")
                        if sch:
                            sch.resident = model
                    except Exception as e:
                        log(f"warm {model} on {b.name} failed: {str(e)[:120]}")
                await b.refresh()
            await asyncio.sleep(60)

    # -- identity
    async def caller(self, request):
        sock = request.transport.get_extra_info("socket") if request.transport else None
        if sock is not None and sock.family == socket.AF_UNIX:
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII"))
            pid, uid, gid = struct.unpack("iII", creds)
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError:
                user = str(uid)
            ref = (self.cfg.get("identities") or {}).get(user, f"user:{user}")
            c = Caller(ref, user, uid, process_ref(pid), "socket")
            c.operator = uid == 0
        else:
            auth = request.headers.get("Authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
            if not token:
                raise ApiError(401, "unauthorized", "a bearer token is required on the TCP listener (maluctl gateway token issue)")
            row = self.token_cache.get(token)
            if not row or row[1] < time.time() - 30:
                r = await self.db.token_lookup(token)
                if not r:
                    raise ApiError(401, "unauthorized", "unknown, expired or revoked token")
                row = self.token_cache[token] = (r, time.time())
            r = row[0]
            peer = request.transport.get_extra_info("peername") if request.transport else None
            c = Caller(r["principal_ref"], None, None, f"tcp:{peer[0]}" if peer else "tcp", "token")
            c.token_name = r["name"]
        await self.enrich(c)
        return c

    async def enrich(self, c):
        ent = self.principal_cache.get(c.ref)
        if not ent or ent[2] < time.time() - 30:
            row = await self.db.principal(c.ref)
            scopes = await self.db.principal_scopes(c.ref, row["home_scope"] if row else None) if row else set()
            ent = self.principal_cache[c.ref] = (row, scopes, time.time())
        row, scopes = ent[0], ent[1]
        if row:
            if not row["enabled"]:
                raise ApiError(403, "principal_disabled", f"principal {c.ref} is disabled")
            c.enrolled, c.kind, c.scopes = True, row["principal_kind"], set(scopes)
        return c

    # -- hints and resolution
    def hints(self, request, body=None):
        h = {}
        ext = body.pop("maluos", None) if isinstance(body, dict) else None
        ext = ext if isinstance(ext, dict) else {}
        def pick(header, key, conv=str):
            v = request.headers.get(header)
            if v is None:
                v = ext.get(key)
            if v is None or v == "":
                return None
            try:
                return conv(v)
            except Exception:
                raise ApiError(400, "bad_hint", f"bad value for {key}: {v!r}")
        flag = lambda v: str(v).lower() in ("1", "true", "yes")
        h["class"] = pick("X-MaluOS-Class", "class")
        h["max_wait"] = pick("X-MaluOS-Max-Wait", "max_wait", float)
        h["task"] = pick("X-MaluOS-Task", "task")
        h["strict"] = pick("X-MaluOS-Strict", "strict", flag)
        h["local_only"] = pick("X-MaluOS-Local-Only", "local_only", flag)
        h["sensitivity"] = pick("X-MaluOS-Sensitivity", "sensitivity", lambda v: str(v).lower())
        if h["sensitivity"] and h["sensitivity"] not in SENS:
            raise ApiError(400, "bad_hint", f"sensitivity must be one of {', '.join(SENS)}")
        h["prefer"] = pick("X-MaluOS-Prefer", "prefer", lambda v: str(v).lower())
        return h

    def known_models(self):
        return {name: set(b.models) for name, b in self.backends.items()}

    async def credential(self, backend, caller, call):
        """(key, reason_if_none): the caller's own key first, then granted shared ones (FR-13), through the vault."""
        ref = backend.secret_ref or {"anthropic": "anthropic", "openai": "openai", "openai_compat": backend.name, "ollama_cloud": "ollama"}.get(backend.kind, backend.name)
        if not caller.enrolled:
            return None, "not_enrolled"
        try:
            from maluos_vault_client import Vault, VaultError
        except ImportError:
            return None, "vault_unavailable"
        v = Vault(self.cfg.get("vault_socket"), on_behalf_of=caller.ref)
        try:
            r = await asyncio.to_thread(v.use, ref, f"{call.id} {backend.name}")
            return r["value"], None
        except VaultError as e:
            return None, {"no_secret": "no_credential", "forbidden": "no_credential", "use_requires_broker": "not_a_broker",
                          "not_a_broker": "not_a_broker", "unavailable": "vault_unavailable", "locked": "credential_locked",
                          "expired": "credential_expired"}.get(e.code, e.code)

    async def prepare(self, caller, kind, requested, hints, endpoint, stream=False, needs=None):
        cat = self.catalog
        call = Call(caller, kind, requested, hints, endpoint, stream)
        needs = needs or {}
        policy = cat.policy_for(caller.ref, caller.scopes)
        cls = hints.get("class") or policy.get("default_class") or ("agent" if caller.kind == "agent" and "agent" in cat.classes else None) or cat.default_class()
        if cls not in cat.classes and cat.classes:
            await self.ledger_denied(call, "bad_class", f"unknown class {cls}")
            raise ApiError(400, "bad_class", f"unknown class {cls!r}; classes: {', '.join(cat.classes)}")
        call.cls = cls
        if not requested:
            raise ApiError(400, "model_required", "model is required (a tier, an alias or a model name)")
        call.tier = requested if requested in cat.tiers else None
        if policy["allowed_tiers"] is not None and call.tier and call.tier not in policy["allowed_tiers"]:
            await self.ledger_denied(call, "policy_tier", f"tier {call.tier} not allowed")
            raise ApiError(403, "policy", f"your policy does not allow tier {call.tier}")
        cands = cat.candidates(requested, self.known_models())
        if not cands:
            await self.ledger_denied(call, "model_not_found", f"no route for {requested}", status="error")
            names = sorted(set(list(cat.tiers) + [a["name"] for a in cat.aliases if a["tier"] is None]))
            raise ApiError(404, "model_not_found", f"model {requested!r} is not a tier, an alias or a model present on a local backend; known names: {', '.join(names[:12])}")
        if policy.get("ladder"):
            order = {n: i for i, n in enumerate(policy["ladder"])}
            cands = sorted((c for c in cands if c[0] in order), key=lambda c: order[c[0]])
        req_sens = hints.get("sensitivity") or "internal"
        egress = policy.get("max_egress_sensitivity") or ("public" if caller.kind == "agent" else "internal")
        cls_row = cat.classes.get(cls) or {}
        rungs, keys = [], {}
        for backend, model, reason in cands:
            b = self.backends.get(backend)
            e = {"backend": backend, "model": model, "reason": reason, "taken": False}
            skip = None
            if not b or not b.enabled:
                skip = "disabled" if b else "unknown backend"
            elif policy["allowed_backends"] is not None and backend not in policy["allowed_backends"]:
                skip = "policy"
            elif b.healthy is False:
                skip = "unhealthy"
            elif b.is_cloud:
                if hints.get("local_only"):
                    skip = "local_only"
                elif not policy.get("cloud_allowed", True):
                    skip = "cloud_not_allowed"
                elif SENS[req_sens] > SENS.get(egress, 1):
                    skip = f"sensitivity:{req_sens}>{egress}"
                else:
                    key, why = await self.credential(b, caller, call)
                    if not key:
                        skip = why or "no_credential"
                    else:
                        keys[backend] = key
            else:
                caps = b.capabilities(model)
                if needs.get("tools") and caps.get("tools") is False:
                    skip = "no_tools"
                elif needs.get("vision") and caps.get("vision") is False:
                    skip = "no_vision"
                elif needs.get("context") and caps.get("context_length") and needs["context"] > caps["context_length"]:
                    skip = "context_too_long"
            if skip:
                e["skipped"] = skip
            rungs.append(e)
        eligible = [r for r in rungs if "skipped" not in r]
        cloud_ok = any(self.backends[r["backend"]].is_cloud for r in eligible)
        if cloud_ok and any(not self.backends[r["backend"]].is_cloud for r in eligible):
            fw = cls_row.get("fallback_wait_s")
            if hints.get("prefer") == "cloud":
                for r in eligible:
                    if not self.backends[r["backend"]].is_cloud:
                        r["skipped"] = "prefer_cloud"
            elif fw is not None:
                for r in eligible:
                    if not self.backends[r["backend"]].is_cloud:
                        ew = self.schedulers[r["backend"]].expected_wait(cls, r["model"])
                        if ew > float(fw):
                            r["skipped"] = f"wait_exceeds_fallback:{ew}s>{fw}s"
            eligible = [r for r in rungs if "skipped" not in r]
        if hints.get("prefer") == "local":
            local = [r for r in eligible if not self.backends[r["backend"]].is_cloud]
            if local:
                for r in eligible:
                    if self.backends[r["backend"]].is_cloud:
                        r["skipped"] = "prefer_local"
                eligible = local
        call.route, call.keys = rungs, keys
        if not eligible:
            reasons = {r.get("skipped", "").split(":")[0] for r in rungs}
            policy_only = reasons <= {"policy", "cloud_not_allowed", "sensitivity", "no_credential", "local_only", "not_enrolled", "credential_locked", "credential_expired", "disabled", "prefer_local"}
            code = "policy" if policy_only else "backend_unavailable"
            if "vault_unavailable" in reasons:
                code = "vault_unavailable"
            elif reasons <= {"unhealthy", "local_only", "disabled"} and (hints.get("local_only") or not any(self.backends[r["backend"]].is_cloud for r in rungs if r["backend"] in self.backends)):
                code = "local_unavailable"      # FR-45: the GPU or local Ollama is down and the request may not leave the host
            elif reasons <= {"unhealthy", "disabled"} and all(self.backends[r["backend"]].is_cloud for r in rungs if r["backend"] in self.backends):
                code = "cloud_unreachable"      # FR-46: cloud-only work with no reachable provider
            await self.ledger_denied(call, code, "no eligible rung", status="denied" if policy_only else "error")
            raise ApiError(403 if policy_only else 503, code, f"no eligible backend for {requested}: " +
                           "; ".join(f"{r['backend']}/{r['model']} {r.get('skipped')}" for r in rungs), route=rungs)
        call.rungs = eligible
        self.select(call, eligible[0])
        await self.check_budget(call, policy, needs)
        return call

    def select(self, call, rung):
        call.backend, call.model, call.reason = rung["backend"], rung["model"], rung["reason"]
        call.rung = rung

    # -- budgets and prices (FR-21, FR-39)
    def price(self, backend, model):
        return self.catalog.prices.get((backend, model)) or self.catalog.prices.get((backend, "*"))

    def cost(self, backend, model, tokens_in, tokens_out, cached=0):
        p = self.price(backend, model)
        if not p:
            return None, None
        ti, to, tc = (tokens_in or 0) - (cached or 0), tokens_out or 0, cached or 0
        c = ti * float(p["input_per_mtok"] or 0) / 1e6 + to * float(p["output_per_mtok"] or 0) / 1e6 + tc * float(p["cached_per_mtok"] or 0) / 1e6
        return round(c, 6), p.get("currency") or "USD"

    async def spent(self, principal_ref, period):
        key = (principal_ref, period)
        ent = self.spend_cache.get(key)
        if ent and ent[1] > time.time() - 10:
            return ent[0]
        row = await self.db.fetchone(f"SELECT coalesce(sum(cost_actual), 0) AS c FROM maluos_ledger WHERE principal_ref=%s AND event='model.call' AND ts >= date_trunc(%s, now())",
                                     (principal_ref, period))
        v = float(row["c"]) if row else 0.0
        self.spend_cache[key] = (v, time.time())
        return v

    async def check_budget(self, call, policy, needs):
        est_in, est_out = needs.get("tokens_in_est") or 0, needs.get("tokens_out_est") or 1024
        call.cost_est, call.currency = self.cost(call.backend, call.model, est_in, est_out)
        budget = policy.get("budget") or {}
        if not budget or call.cost_est is None:
            return
        warn_at = float(budget.get("warn_at") or 0.8)
        for key, period in (("usd_per_day", "day"), ("usd_per_month", "month")):
            limit = budget.get(key)
            if limit is None:
                continue
            spent = await self.spent(call.caller.ref, period)
            if spent + call.cost_est > float(limit):
                await self.ledger_denied(call, "budget_exceeded", f"{period}: spent {spent:.4f} + est {call.cost_est:.4f} > {limit}")
                await self.alerts.fire("budget_exceeded", f"{call.caller.ref} exhausted the {period} budget ({spent:.4f}/{limit} {call.currency})",
                                       {"principal": call.caller.ref, "period": period, "spent": spent, "limit": limit},
                                       once_key=f"budget_exceeded:{call.caller.ref}:{period}", cooldown_s=3600)
                raise ApiError(403, "budget_exceeded", f"{period} budget of {limit} {call.currency} exhausted (spent {spent:.4f}, this call ~{call.cost_est:.4f})",
                               period=period, spent=spent, limit=limit)
            if spent + call.cost_est > warn_at * float(limit):
                call.warnings.append(f"{period} budget {spent + call.cost_est:.4f}/{limit} {call.currency}")
                await self.alerts.fire("budget", f"{call.caller.ref} is at {spent + call.cost_est:.4f}/{limit} {call.currency} of the {period} budget",
                                       {"principal": call.caller.ref, "period": period, "spent": spent, "estimate": call.cost_est, "limit": limit},
                                       once_key=f"budget:{call.caller.ref}:{period}", cooldown_s=3600)

    # -- admission and ledger
    async def admit(self, call):
        sch = self.schedulers[call.backend]
        call.job = Job(call.id, call.caller.ref, call.cls, call.model, call.kind)
        t = time.monotonic()
        try:
            await sch.acquire(call.job, call.hints.get("max_wait"))
        except AdmissionError as e:
            await self.ledger_denied(call, e.code, e.message, expected_wait=e.expected_wait)
            raise ApiError(503, e.code, e.message, expected_wait_s=e.expected_wait, **{"class": call.cls}, retry_after_s=e.expected_wait)
        call.queued_ms = (call.queued_ms or 0) + int((time.monotonic() - t) * 1000)

    def release(self, call, final=None, error=False):
        sch = self.schedulers.get(call.backend)
        if not sch or not call.job:
            return
        if final and not error:
            u = usage_from(final)
            service = (u["total_ms"] or 0) / 1000.0 or (time.monotonic() - call.job.started)
            load = (u["load_ms"] or 0) / 1000.0
            sch.release(call.job, max(0.05, service - load), load, u["tokens_out"])
        else:
            sch.release(call.job)
        call.job = None

    def base_row(self, call):
        c = call.caller
        return {"event": "model.call", "principal_ref": c.ref, "linux_user": c.linux_user, "linux_uid": c.uid, "process_ref": c.process_ref,
                "class": call.cls, "tier": call.tier, "requested_model": call.requested, "route": call.route, "attempts": call.attempts,
                "backend": call.backend, "model": call.model, "queue_wait_ms": call.queued_ms, "task_ref": call.task,
                "purpose": call.endpoint, "cost_est": call.cost_est, "currency": call.currency}

    async def ledger_denied(self, call, reason, message, status="denied", expected_wait=None):
        row = self.base_row(call)
        row.update({"status": status, "reason": reason, "error_class": reason,
                    "detail": {"message": message[:300], "expected_wait_s": expected_wait, "via": call.caller.via}})
        await self.ledger_write(row)
        self.routes.appendleft({"ts": time.time(), "id": call.id, "principal": call.caller.ref, "requested": call.requested,
                                "class": call.cls, "route": call.route, "status": status, "reason": reason})

    async def ledger_done(self, call, final=None, error=None, cancelled=False):
        row = self.base_row(call)
        elapsed_ms = int((time.monotonic() - call.t0) * 1000) - (call.queued_ms or 0)
        detail = {"endpoint": call.endpoint, "stream": call.stream, "via": call.caller.via, "reason": call.reason}
        if call.warnings:
            detail["warnings"] = call.warnings
        if call.engine_request_id:
            detail["engine_request_id"] = call.engine_request_id
        if final:
            u = usage_from(final)
            cached = final.get("cached_tokens") or 0
            cost, cur = self.cost(call.backend, call.model, u["tokens_in"], u["tokens_out"], cached)
            row.update({"service_ms": u["total_ms"] or elapsed_ms, "gpu_ms": ((u["prompt_ms"] or 0) + (u["eval_ms"] or 0) or None) if not self.backends[call.backend].is_cloud else None,
                        "tokens_in": u["tokens_in"], "tokens_out": u["tokens_out"], "tokens_cached": cached or None,
                        "cost_actual": cost, "currency": cur or call.currency, "provider_request_id": final.get("provider_request_id")})
            detail.update({"load_ms": u["load_ms"], "done_reason": u["done_reason"]})
        else:
            row["service_ms"] = elapsed_ms
        if cancelled:
            row.update({"status": "error", "error_class": "cancelled", "reason": "client_disconnected"})
        elif error is not None:
            row.update({"status": "error", "error_class": getattr(error, "error_class", None) or getattr(error, "code", None) or error.__class__.__name__,
                        "reason": str(getattr(error, "message", error))[:200]})
        else:
            row["status"] = "ok"
        row["detail"] = detail
        if call.task and row["status"] == "ok" and (self.cfg.get("episodes") or {}).get("enabled", True):
            try:
                ep = await self.db.fetchone("SELECT maluos_record_episode('maluos.model_call', %s, %s, %s, %s) AS id",
                                            (f"{call.model} for {call.task}"[:200],
                                             f"{call.caller.ref} called {call.backend}/{call.model} ({call.cls}) for task {call.task}: {row.get('tokens_in') or 0} in, {row.get('tokens_out') or 0} out",
                                             json.dumps({"task_ref": call.task, "principal": call.caller.ref, "backend": call.backend, "model": call.model, "class": call.cls,
                                                         "tokens_in": row.get("tokens_in"), "tokens_out": row.get("tokens_out"), "cost": row.get("cost_actual"),
                                                         "request": call.id, "route": call.route}, default=str),
                                             call.hints.get("sensitivity") or "internal"))
                row["episode_id"] = ep["id"] if ep else None
            except Exception as e:
                log(f"episode for {call.task} not recorded: {e.__class__.__name__}: {str(e)[:120]}")
        await self.ledger_write(row)
        if row.get("cost_actual"):
            for key in [k for k in self.spend_cache if k[0] == call.caller.ref]:
                del self.spend_cache[key]   # the next budget check re-reads the ledger
        self.routes.appendleft({"ts": time.time(), "id": call.id, "principal": call.caller.ref, "requested": call.requested, "class": call.cls,
                                "route": call.route, "status": row["status"], "reason": row.get("reason"), "queue_wait_ms": call.queued_ms,
                                "service_ms": row.get("service_ms"), "tokens_in": row.get("tokens_in"), "tokens_out": row.get("tokens_out"),
                                "cost": row.get("cost_actual"), "attempts": call.attempts})

    async def ledger_write(self, row):
        try:
            await self.db.ledger(**row)
        except Exception as e:
            log(f"ledger write failed: {e.__class__.__name__}: {str(e)[:160]}")

    # -- execution with fallback across the ladder (FR-29, FR-31)
    FALLBACK_ERRORS = ("model_not_found", "capability", "no_credential", "bad_credential", "rate_limited", "backend_unavailable", "timeout", "backend_error")

    async def run(self, call, path, body, stream, timeout_s=None):
        """Admit and start the call on the first eligible rung, moving down the ladder on failure.
        Returns the final object (non-stream) or (generator, first_chunk) for streaming."""
        timeout_s = timeout_s or float(self.cfg.get("request_timeout_s") or 600)
        last = None
        idx = 0
        while idx < len(call.rungs):
            rung = call.rungs[idx]
            self.select(call, rung)
            b = self.backends[call.backend]
            await self.admit(call)
            call.attempts += 1
            key = call.keys.get(call.backend)
            fwd = dict(body, model=call.model)
            try:
                if stream:
                    gen = b.stream(path, fwd, timeout_s, key=key)
                    first = await anext(gen)
                    rung["taken"] = True
                    return gen, first
                res = await b.call(path, fwd, timeout_s, key=key)
                rung["taken"] = True
                self.release(call, res)
                return res
            except BackendError as e:
                self.release(call, error=True)
                last = e
                rung.setdefault("failed", []).append(e.error_class)
                retry_local = (not b.is_cloud and e.error_class in ("backend_error", "timeout") and not rung.get("retried"))
                if retry_local:
                    rung["retried"] = True
                    continue
                if e.error_class in self.FALLBACK_ERRORS and idx + 1 < len(call.rungs):
                    idx += 1
                    continue
                raise
            except asyncio.CancelledError:
                self.release(call, error=True)
                raise
        raise last

    def error_code(self, call, e):
        """FR-45/46: a dead local backend is local_unavailable, a dead cloud one cloud_unreachable."""
        if e.error_class == "backend_unavailable" and call.backend in self.backends:
            return "cloud_unreachable" if self.backends[call.backend].is_cloud else "local_unavailable"
        return e.error_class

    async def execute(self, call, path, body, timeout_s=None):
        """Non-streaming call: admit, run (with fallback), account."""
        try:
            res = await self.run(call, path, body, False, timeout_s)
        except BackendError as e:
            await self.ledger_done(call, error=e)
            raise ApiError(e.status if e.status in (401, 403, 404, 429, 503, 504) else 502, self.error_code(call, e), e.message, backend=call.backend, route=call.route)
        except asyncio.CancelledError:
            await self.ledger_done(call, cancelled=True)
            raise
        await self.ledger_done(call, res)
        return res

    async def stream(self, request, call, path, body, on_chunk, on_end, on_error, content_type):
        """Streaming call: admission and the first chunk happen before the headers go out, so
        admission errors and dead rungs are still HTTP errors and fallback still works."""
        try:
            gen, first = await self.run(call, path, body, True)
        except BackendError as e:
            await self.ledger_done(call, error=e)
            raise ApiError(e.status if e.status in (401, 403, 404, 429, 503, 504) else 502, self.error_code(call, e), e.message, backend=call.backend, route=call.route)
        except asyncio.CancelledError:
            await self.ledger_done(call, cancelled=True)
            raise
        resp = web.StreamResponse(status=200, headers={"Content-Type": content_type, "Cache-Control": "no-cache", **self.headers_for(call)})
        await resp.prepare(request)
        final, err = None, None
        try:
            obj = first
            while True:
                for out in on_chunk(obj):
                    await resp.write(out)
                if obj.get("done"):
                    final = obj
                    break
                obj = await anext(gen)
            for out in on_end(final):
                await resp.write(out)
        except StopAsyncIteration:
            for out in on_end(final):
                await resp.write(out)
        except BackendError as e:
            err = e
            try:
                for out in on_error(e):
                    await resp.write(out)
            except Exception:
                pass
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
            self.release(call, error=True)
            await self.ledger_done(call, final, cancelled=True)
            raise
        self.release(call, final, error=err is not None)
        await self.ledger_done(call, final, error=err)
        try:
            await resp.write_eof()
        except Exception:
            pass
        return resp

    def headers_for(self, call):
        return {"X-MaluOS-Route": f"{call.backend}/{call.model} ({call.reason})", "X-MaluOS-Request": call.id, "X-MaluOS-Class": call.cls,
                "X-MaluOS-Attempts": str(call.attempts or 1)}

    # -- status
    def status(self):
        snaps = {n: s.snapshot() for n, s in self.schedulers.items()}
        local = [s for n, s in snaps.items() if not self.backends[n].is_cloud]
        ew = {}
        for cls in (self.catalog.classes if self.catalog else {}):
            ew[cls] = max([s["classes"].get(cls, {}).get("expected_wait_s", 0) for s in local] or [0])
        return {"version": VERSION, "uptime_s": int(time.time() - self.started),
                "backends": [b.status() for b in self.backends.values()],
                "queue": {"queued": sum(s["queued"] for s in snaps.values()), "running": sum(s["running"] for s in snaps.values())},
                "expected_wait_s": ew, "schedulers": snaps,
                "engine_queue": {"enabled": bool(self.cfg["engine_queue"].get("enabled", True)), "inflight": self.engine_inflight},
                "catalog": {"tiers": {t: [f"{a['backend']}/{a['model']}" for a in sorted(self.catalog.aliases, key=lambda a: a["position"]) if a["tier"] == t]
                                      for t in self.catalog.tiers},
                            "aliases": {a["name"]: f"{a['backend']}/{a['model']}" for a in self.catalog.aliases if a["tier"] is None},
                            "classes": {c: {k: v for k, v in r.items() if k in ("priority", "weight", "max_queue", "max_wait_s", "fallback_wait_s")}
                                        for c, r in self.catalog.classes.items()}}}

    # -- the engine queue (malu$model_request)
    async def drain_loop(self):
        await asyncio.sleep(5)
        conn = None
        while True:
            eq = self.cfg["engine_queue"]
            if not eq.get("enabled", True):
                await asyncio.sleep(10); continue
            try:
                if conn is None or conn.closed:
                    conn = await self.db.connection()
                if self.engine_inflight >= 4:
                    await asyncio.sleep(0.5); continue
                row = await self.db.claim_engine_request(conn)
            except Exception as e:
                log(f"engine queue: {e.__class__.__name__}: {str(e)[:160]}")
                conn = None
                await asyncio.sleep(10); continue
            if not row:
                await asyncio.sleep(float(eq.get("poll_s") or 2)); continue
            self.spawn(self.run_engine_request(row))

    async def run_engine_request(self, row):
        self.engine_inflight += 1
        conn = None
        rid = row["request_id"]
        self.inflight.add(rid); self.save_inflight()
        interrupted = False
        try:
            conn = await self.db.connection()
            caller = Caller(self.cfg["engine_queue"].get("principal") or "service:engine", None, None, "maludb-engine", "engine")
            caller.kind = "service"
            await self.enrich(caller)
            hints = {"class": self.cfg["engine_queue"].get("class") or "batch", "task": f"model_request:{rid}",
                     "sensitivity": self.cfg["engine_queue"].get("sensitivity") or "internal"}
            params = row.get("generation_params") or {}
            body = {"prompt": row["rendered_prompt"]}
            opts = {}
            for src, dst in (("temperature", "temperature"), ("top_p", "top_p"), ("seed", "seed"), ("max_tokens", "num_predict"), ("num_predict", "num_predict")):
                if params.get(src) is not None:
                    opts[dst] = params[src]
            if params.get("stop"):
                opts["stop"] = params["stop"] if isinstance(params["stop"], list) else [params["stop"]]
            if isinstance(params.get("options"), dict):
                opts.update(params["options"])
            if opts:
                body["options"] = opts
            if params.get("format"):
                body["format"] = params["format"]
            if row.get("runtime_params") and isinstance(row["runtime_params"], dict) and row["runtime_params"].get("options"):
                body.setdefault("options", {}).update(row["runtime_params"]["options"])
            call = None
            needs = {"tokens_in_est": len(row["rendered_prompt"]) // 4, "tokens_out_est": opts.get("num_predict") or 1024}
            for requested in (row["alias_name"], row["model_identifier"]):
                try:
                    call = await self.prepare(caller, "generate", requested, hints, "engine:model_request", needs=needs)
                    break
                except ApiError as e:
                    if e.code != "model_not_found":
                        raise
            if call is None:
                raise ApiError(404, "model_not_found", f"neither alias {row['alias_name']} nor model {row['model_identifier']} is routable")
            call.engine_request_id = rid
            if await self.db.engine_cancel_requested(conn, rid):
                await self.db.finish_engine_request(conn, rid, "cancelled", error_class="cancelled", user_safe_error="cancelled before dispatch")
                return
            timeout = max(1.0, (row.get("timeout_ms") or 30000) / 1000.0)
            t0 = time.monotonic()
            task = asyncio.create_task(self.execute(call, "/api/generate", body, timeout_s=timeout))
            while True:   # the contract: re-read cancel_requested while the adapter runs
                done, _ = await asyncio.wait({task}, timeout=1.0)
                if done:
                    break
                if time.monotonic() - t0 > timeout + 5:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await self.db.finish_engine_request(conn, rid, "timeout", error_class="timeout", user_safe_error=f"no result within {timeout:.0f}s",
                                                        latency_ms=int((time.monotonic() - t0) * 1000))
                    return
                if await self.db.engine_cancel_requested(conn, rid):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await self.db.finish_engine_request(conn, rid, "cancelled", error_class="cancelled", user_safe_error="cancelled while running",
                                                        latency_ms=int((time.monotonic() - t0) * 1000))
                    return
            res = task.result()
            u = usage_from(res)
            raw = {k: v for k, v in res.items() if k not in ("response", "context")}
            raw["gateway"] = {"backend": call.backend, "model": call.model, "class": call.cls, "request": call.id, "route": call.route}
            await self.db.finish_engine_request(conn, rid, "succeeded", output_text=res.get("response", ""), prompt_tokens=u["tokens_in"],
                                                completion_tokens=u["tokens_out"], latency_ms=u["total_ms"] or int((time.monotonic() - t0) * 1000),
                                                finish_reason=u["done_reason"], raw=raw)
        except ApiError as e:
            try:
                await self.db.finish_engine_request(conn, rid, "failed", error_class=e.code, user_safe_error=e.message[:300])
            except Exception as e2:
                log(f"engine request {rid}: could not record failure: {e2}")
        except Exception as e:
            log(f"engine request {rid}: {e.__class__.__name__}: {str(e)[:200]}")
            try:
                await self.db.finish_engine_request(conn, rid, "failed", error_class=e.__class__.__name__, user_safe_error=str(e)[:300])
            except Exception:
                pass
        except asyncio.CancelledError:
            interrupted = True      # shutting down: leave the request in the in-flight file for recovery (FR-47)
            raise
        finally:
            self.engine_inflight -= 1
            if not interrupted:
                self.inflight.discard(rid); self.save_inflight()
            if conn:
                await conn.close()


# ---------------------------------------------------------------- HTTP handlers
def build_app(gw):
    app = web.Application(middlewares=[errors_middleware], client_max_size=64 * 1024 * 1024)
    app["gw"] = gw
    r = app.router
    r.add_post("/v1/chat/completions", h_openai_chat)
    r.add_post("/v1/embeddings", h_openai_embeddings)
    r.add_get("/v1/models", h_openai_models)
    r.add_get("/v1/models/{id:.+}", h_openai_model)
    r.add_post("/api/chat", h_ollama_chat)
    r.add_post("/api/generate", h_ollama_generate)
    r.add_post("/api/embed", h_ollama_embed)
    r.add_post("/api/embeddings", h_ollama_embeddings_legacy)
    r.add_get("/api/tags", h_ollama_tags)
    r.add_get("/api/ps", h_ollama_ps)
    r.add_get("/api/version", h_ollama_version)
    r.add_post("/api/show", h_ollama_show)
    r.add_post("/api/pull", h_ollama_pull)
    r.add_get("/", h_root)
    r.add_get("/v1/maluos/health", h_health)
    r.add_get("/v1/maluos/status", h_status)
    r.add_get("/v1/maluos/whoami", h_whoami)
    r.add_get("/v1/maluos/routes", h_routes)
    r.add_post("/v1/maluos/reload", h_reload)
    r.add_post("/v1/maluos/warm", h_warm)
    r.add_post("/v1/maluos/alert", h_alert)
    return app


@web.middleware
async def errors_middleware(request, handler):
    try:
        return await handler(request)
    except ApiError as e:
        return web.json_response(e.body(), status=e.status)
    except web.HTTPException:
        raise
    except (asyncio.CancelledError, ConnectionResetError):
        raise
    except psycopg.OperationalError as e:
        # The database is not there (yet): before first boot has provisioned it, or while PostgreSQL restarts.
        log(f"not ready on {request.method} {request.path}: database unavailable: {str(e).strip()[:160]}")
        return web.json_response({"error": {"message": "the gateway's database is not available yet", "type": "unavailable", "code": "not_ready"}}, status=503)
    except Exception as e:
        log(f"internal error on {request.method} {request.path}: {e.__class__.__name__}: {str(e)[:200]}")
        return web.json_response({"error": {"message": f"internal error: {e.__class__.__name__}", "type": "internal", "code": "internal"}}, status=500)


async def read_json(request):
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "bad_json", "request body is not JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_json", "request body must be a JSON object")
    return body


def need_operator(caller):
    if not caller.operator:
        raise ApiError(403, "forbidden", "operators only (run as root on the socket)")


# -- OpenAI
async def h_openai_chat(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    body = await read_json(request)
    hints = gw.hints(request, body)
    if not body.get("messages"):
        raise ApiError(400, "bad_request", "messages is required")
    requested = body.get("model") or ("standard" if "standard" in gw.catalog.tiers else None)
    obody = openai_to_ollama_chat(body)
    stream = bool(body.get("stream"))
    include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
    call = await gw.prepare(caller, "chat", requested, hints, "/v1/chat/completions", stream, needs=needs_of(obody))
    created, rid = int(time.time()), f"chatcmpl-{secrets.token_hex(10)}"
    if not stream:
        res = await gw.execute(call, "/api/chat", obody)
        msg = res.get("message") or {}
        m = {"role": "assistant", "content": msg.get("content", "")}
        if msg.get("tool_calls"):
            m["tool_calls"] = openai_tool_calls(msg["tool_calls"])
            if not m["content"]:
                m["content"] = None
        out = {"id": rid, "object": "chat.completion", "created": created, "model": call.model, "system_fingerprint": f"maluos/{call.backend}",
               "choices": [{"index": 0, "message": m, "finish_reason": finish_reason(res)}], "usage": openai_usage(res)}
        return web.json_response(out, headers=gw.headers_for(call))
    state = {"first": True}

    def chunk(delta, fin=None):
        return {"id": rid, "object": "chat.completion.chunk", "created": created, "model": call.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}

    def on_chunk(obj):
        msg = obj.get("message") or {}
        delta = {}
        if state["first"]:
            delta["role"] = "assistant"; state["first"] = False
        if msg.get("content"):
            delta["content"] = msg["content"]
        if msg.get("tool_calls"):
            delta["tool_calls"] = [dict(tc, index=i) for i, tc in enumerate(openai_tool_calls(msg["tool_calls"]))]
        if obj.get("done"):
            return []
        return [sse(chunk(delta))] if delta else []

    def on_end(final):
        out = [sse(chunk({}, finish_reason(final or {})))]
        if include_usage and final:
            u = chunk({}); u["choices"] = []; u["usage"] = openai_usage(final); out.append(sse(u))
        out.append(b"data: [DONE]\n\n")
        return out

    def on_error(e):
        return [sse({"error": {"message": e.message, "type": e.error_class, "code": e.error_class}}), b"data: [DONE]\n\n"]
    return await gw.stream(request, call, "/api/chat", obody, on_chunk, on_end, on_error, "text/event-stream")


async def h_openai_embeddings(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    body = await read_json(request)
    hints = gw.hints(request, body)
    inp = body.get("input")
    if inp is None:
        raise ApiError(400, "bad_request", "input is required")
    requested = body.get("model") or ("embed" if "embed" in gw.catalog.tiers else None)
    call = await gw.prepare(caller, "embed", requested, hints, "/v1/embeddings", needs={"tokens_in_est": len(json.dumps(inp)) // 4, "tokens_out_est": 0})
    res = await gw.execute(call, "/api/embed", {"input": inp})
    embs = res.get("embeddings") or []
    n = res.get("prompt_eval_count") or 0
    out = {"object": "list", "model": call.model,
           "data": [{"object": "embedding", "index": i, "embedding": e} for i, e in enumerate(embs)],
           "usage": {"prompt_tokens": n, "total_tokens": n}}
    return web.json_response(out, headers=gw.headers_for(call))


def model_entries(gw):
    cat = gw.catalog
    now = int(time.time())
    out = []
    for t in cat.tiers:
        out.append({"id": t, "object": "model", "created": now, "owned_by": "maluos", "maluos": {"kind": "tier",
                    "ladder": [f"{a['backend']}/{a['model']}" for a in sorted(cat.aliases, key=lambda a: a["position"]) if a["tier"] == t]}})
    for a in cat.aliases:
        if a["tier"] is None:
            out.append({"id": a["name"], "object": "model", "created": now, "owned_by": "maluos", "maluos": {"kind": "alias", "target": f"{a['backend']}/{a['model']}"}})
    seen = {m["id"] for m in out}
    for b in gw.backends.values():
        for name, info in sorted(b.models.items()):
            if name in seen or (name.endswith(":latest") and name[:-7] in b.models):
                continue
            seen.add(name)
            out.append({"id": name, "object": "model", "created": now, "owned_by": b.name, "maluos": {"kind": "model", "backend": b.name, "cloud": b.is_cloud}})
    return out


async def h_openai_models(request):
    gw = request.app["gw"]
    await gw.caller(request)
    return web.json_response({"object": "list", "data": model_entries(gw)})


async def h_openai_model(request):
    gw = request.app["gw"]
    await gw.caller(request)
    mid = request.match_info["id"]
    for m in model_entries(gw):
        if m["id"] == mid:
            return web.json_response(m)
    raise ApiError(404, "model_not_found", f"no model {mid}")


# -- Ollama native
def ndjson(obj):
    return (json.dumps(obj) + "\n").encode()


async def ollama_passthrough(request, kind, path, endpoint, required):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    body = await read_json(request)
    hints = gw.hints(request, body)
    for k in required:
        if body.get(k) is None:
            raise ApiError(400, "bad_request", f"{k} is required")
    requested = body.get("model")
    stream = body.get("stream", True) if kind != "embed" else False
    fwd = {k: v for k, v in body.items() if k not in ("model", "stream")}
    call = await gw.prepare(caller, kind, requested, hints, endpoint, bool(stream), needs=needs_of(fwd))
    if not stream:
        res = await gw.execute(call, path, fwd)
        return web.json_response(res, headers=gw.headers_for(call))
    return await gw.stream(request, call, path, fwd, lambda o: [ndjson(o)], lambda f: [],
                           lambda e: [ndjson({"error": e.message, "error_class": e.error_class})], "application/x-ndjson")


async def h_ollama_chat(request):
    return await ollama_passthrough(request, "chat", "/api/chat", "/api/chat", ("messages",))


async def h_ollama_generate(request):
    return await ollama_passthrough(request, "generate", "/api/generate", "/api/generate", ())


async def h_ollama_embed(request):
    return await ollama_passthrough(request, "embed", "/api/embed", "/api/embed", ("input",))


async def h_ollama_embeddings_legacy(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    body = await read_json(request)
    hints = gw.hints(request, body)
    call = await gw.prepare(caller, "embed", body.get("model"), hints, "/api/embeddings")
    res = await gw.execute(call, "/api/embed", {"input": body.get("prompt", "")})
    embs = res.get("embeddings") or [[]]
    return web.json_response({"embedding": embs[0]}, headers=gw.headers_for(call))


async def h_ollama_tags(request):
    gw = request.app["gw"]
    await gw.caller(request)
    models = []
    seen = set()
    for b in gw.backends.values():
        if b.kind in ("ollama_local", "mock"):
            for name, info in b.models.items():
                if name in seen or (name.endswith(":latest") and name[:-7] in b.models):
                    continue
                seen.add(name)
                m = dict(info); m["maluos"] = {"backend": b.name}; models.append(m)
    cat = gw.catalog
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for t in cat.tiers:
        models.append({"name": t, "model": t, "modified_at": now, "size": 0, "digest": "", "details": {"family": "maluos-tier"},
                       "maluos": {"kind": "tier", "ladder": [f"{a['backend']}/{a['model']}" for a in sorted(cat.aliases, key=lambda a: a["position"]) if a["tier"] == t]}})
    for a in cat.aliases:
        if a["tier"] is None:
            models.append({"name": a["name"], "model": a["name"], "modified_at": now, "size": 0, "digest": "", "details": {"family": "maluos-alias"},
                           "maluos": {"kind": "alias", "target": f"{a['backend']}/{a['model']}"}})
    return web.json_response({"models": models})


async def h_ollama_ps(request):
    gw = request.app["gw"]
    await gw.caller(request)
    await asyncio.gather(*(b.refresh() for b in gw.backends.values() if not b.is_cloud), return_exceptions=True)
    out = []
    for b in gw.backends.values():
        for m in b.loaded:
            d = dict(m); d["maluos"] = {"backend": b.name}; out.append(d)
    return web.json_response({"models": out})


async def h_ollama_version(request):
    return web.json_response({"version": VERSION, "maluos": True})


async def h_ollama_show(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    body = await read_json(request)
    call = await gw.prepare(caller, "show", body.get("model") or body.get("name"), {}, "/api/show")
    b = gw.backends[call.backend]
    try:
        res = await b.call("/api/show", {"model": call.model}, timeout_s=30)
    except BackendError as e:
        raise ApiError(502, e.error_class, e.message)
    res["maluos"] = {"backend": call.backend, "model": call.model, "reason": call.reason}
    return web.json_response(res)


async def h_ollama_pull(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    need_operator(caller)
    body = await read_json(request)
    name = body.get("model") or body.get("name")
    bname = body.get("backend") or next((n for n, b in gw.backends.items() if b.kind in ("ollama_local", "mock") and b.healthy), None)
    if not name or not bname:
        raise ApiError(400, "bad_request", "model (and a healthy local backend) required")
    b = gw.backends[bname]
    resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson"})
    await resp.prepare(request)
    try:
        async for obj in b.stream("/api/pull", {"model": name}, timeout_s=3600):
            await resp.write(ndjson(obj))
    except BackendError as e:
        await resp.write(ndjson({"error": e.message}))
    await b.refresh()
    await gw.ledger_write({"event": "model.pull", "principal_ref": caller.ref, "linux_user": caller.linux_user, "linux_uid": caller.uid,
                           "process_ref": caller.process_ref, "backend": bname, "model": name, "status": "ok"})
    await resp.write_eof()
    return resp


# -- MaluOS
async def h_root(request):
    return web.Response(text="MaluOS inference gateway is running\n")


async def h_health(request):
    gw = request.app["gw"]
    return web.json_response({"ok": True, "version": gw.VERSION if hasattr(gw, "VERSION") else VERSION, "backends": {n: b.healthy for n, b in gw.backends.items()},
                              "catalog_loaded_at": gw.catalog.loaded_at if gw.catalog else None})


async def h_status(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    st = gw.status()
    if not caller.operator:
        for s in st["schedulers"].values():
            s["jobs"] = [j for j in s["jobs"] if j["principal"] == caller.ref]
    return web.json_response(st)


async def h_whoami(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    d = caller.as_dict()
    d["policy"] = gw.catalog.policy_for(caller.ref, caller.scopes)
    d["spend"] = {"day": await gw.spent(caller.ref, "day"), "month": await gw.spent(caller.ref, "month")}   # the caller's own, for budgets
    return web.json_response(d)


async def h_routes(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    rows = [r for r in gw.routes if caller.operator or r["principal"] == caller.ref]
    return web.json_response({"routes": rows[: int(request.query.get("limit", 50))]})


async def h_reload(request):
    gw = request.app["gw"]
    need_operator(await gw.caller(request))
    gw.cfg.reload()
    await gw.reload_catalog()
    for b in gw.backends.values():
        b.cooldown_until = 0
    await asyncio.gather(*(b.refresh() for b in gw.backends.values()), return_exceptions=True)
    return web.json_response({"reloaded": True, "backends": list(gw.backends)})


async def h_warm(request):
    gw = request.app["gw"]
    caller = await gw.caller(request)
    need_operator(caller)
    body = await read_json(request)
    name = body.get("model")
    bname = body.get("backend") or next((n for n, b in gw.backends.items() if b.kind in ("ollama_local", "mock") and b.healthy), None)
    if not name or not bname:
        raise ApiError(400, "bad_request", "model and a healthy local backend are required")
    try:
        res = await gw.backends[bname].warm(name, body.get("keep_alive"))
    except BackendError as e:
        raise ApiError(502, e.error_class, e.message)
    await gw.backends[bname].refresh()
    gw.schedulers[bname].resident = name
    return web.json_response({"warmed": name, "backend": bname, "load_ms": usage_from(res)["load_ms"]})


async def h_alert(request):
    """Operators: raise an alert by hand (tests, external monitors)."""
    gw = request.app["gw"]
    need_operator(await gw.caller(request))
    body = await read_json(request)
    fired = await gw.alerts.fire(body.get("kind") or "manual", body.get("title") or "manual alert", body.get("detail") or {})
    return web.json_response({"fired": fired})


# ---------------------------------------------------------------- main
async def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="MaluOS inference gateway")
    ap.add_argument("--socket", help="bind this path (default: inherited from systemd, else config)")
    ap.add_argument("--tcp", help="also listen on host:port (overrides config)")
    args = ap.parse_args(argv)
    cfg = Config()
    gw = Gateway(cfg)
    await gw.start()
    app = build_app(gw)
    runner = web.AppRunner(app, handler_cancellation=True, access_log=None)
    await runner.setup()
    sites = []
    fds = int(os.environ.get("LISTEN_FDS") or 0)
    if fds and os.environ.get("LISTEN_PID") in (None, str(os.getpid())) and not args.socket:
        sock = socket.socket(fileno=3)
        sites.append(web.SockSite(runner, sock))
        log("listening on the inherited socket (activation)")
    else:
        path = args.socket or cfg["socket"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.remove(path)
        sites.append(web.UnixSite(runner, path))
        log(f"listening on {path}")
    tcp = cfg["tcp"]
    if args.tcp:
        host, port = args.tcp.rsplit(":", 1)
        sites.append(web.TCPSite(runner, host, int(port))); log(f"listening on tcp {host}:{port} (tokens required)")
    elif tcp.get("enabled"):
        sites.append(web.TCPSite(runner, tcp.get("host", "127.0.0.1"), int(tcp.get("port", 11435))))
        log(f"listening on tcp {tcp.get('host', '127.0.0.1')}:{tcp.get('port', 11435)} (tokens required)")
    for s in sites:
        await s.start()
    if not fds and not args.socket:
        pass
    if args.socket or not fds:
        try:
            os.chmod(args.socket or cfg["socket"], 0o666)
        except OSError:
            pass
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    loop.add_signal_handler(signal.SIGHUP, lambda: asyncio.create_task(gw.reload_catalog()))
    log(f"maluos-gateway {VERSION} ready; tenant {cfg['tenant']}, {len(gw.backends)} backend(s)")
    await stop.wait()
    await gw.stop()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
