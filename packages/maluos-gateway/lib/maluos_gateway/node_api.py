"""The node API (Phase 13 G2): /node/v1 on the gateway, the management contract
of docs/inference-node-api.md. Opened by a node key (kind node) over TCP or
by an operator on the socket; inference keys are refused. Never serves an
inference and never reads a key back."""
import hashlib, json, os, platform, re, secrets, socket, time
from aiohttp import web

from . import VERSION

API_VERSION = 1
LANE_KINDS = ("local", "remote", "cloud")


def now_iso():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int((t % 1) * 1000):03d}Z"


def lane_kind(b):
    return "cloud" if b.is_cloud else "remote" if getattr(b, "is_remote", False) else "local"


async def node_caller(request):
    from .server import ApiError
    gw = request.app["gw"]
    caller = await gw.caller(request)
    if not (caller.operator or caller.token_kind == "node"):
        raise ApiError(403, "forbidden", "the node API needs a node key (maluctl gateway key issue --kind node) or an operator on the socket (root or one of the estate's operators)")
    if caller.token_kind == "node":
        gw.manager_seen = time.time()
    return caller


def envelope(gw, obj):
    obj.update({"node_id": gw.node_id, "node_name": gw.node_name, "api_version": API_VERSION, "clock": now_iso()})
    return web.json_response(obj, headers={"X-Node-Id": gw.node_id})


def machine():
    m = {"hostname": socket.gethostname(), "os": None, "arch": platform.machine(), "cpu_count": os.cpu_count()}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    m["os"] = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
        m["memory_total"], m["memory_available"] = info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError):
        pass
    try:
        m["load_1m"] = os.getloadavg()[0]
    except OSError:
        pass
    return m


def lanes(gw):
    out = {}
    for name, sch in gw.schedulers.items():
        b = gw.backends.get(name)
        s = sch.snapshot()
        out[name] = {"kind": lane_kind(b) if b else "local", "capacity": s["capacity"], "running": s["running"], "queued": s["queued"], "paused": s["paused"],
                     "resident": s["resident"], "oldest_queued_ms": s["oldest_queued_ms"], "healthy": b.healthy if b else None,
                     "classes": {c: {"queued": v["queued"], "expected_wait_ms": int(v["expected_wait_s"] * 1000)} for c, v in s["classes"].items()}}
    return out


def lane_names(gw, lane):
    if lane in LANE_KINDS:
        return [n for n, b in gw.backends.items() if lane_kind(b) == lane and n in gw.schedulers]
    return [lane] if lane in gw.schedulers else []


# -- status and health
async def h_status(request):
    gw = request.app["gw"]
    await node_caller(request)
    totals = {"admitted": 0, "rejected": 0, "cancelled": 0, "completed": 0}
    for sch in gw.schedulers.values():
        for k in totals:
            totals[k] += sch.totals.get(k, 0)
    m = machine()
    try:
        import maluos_gpu
        g = maluos_gpu.status()
        m["gpus"], m["chassis"] = g.get("gpus", []), g.get("chassis")
    except Exception as e:
        m["gpus"], m["chassis"], m["gpu_error"] = [], None, f"{e.__class__.__name__}: {str(e)[:80]}"
    loaded = [{"name": l.get("name"), "backend": b.name, "size_vram": l.get("size_vram"), "expires_at": l.get("expires_at")} for b in gw.backends.values() for l in b.loaded]
    return envelope(gw, {"name": gw.node_name, "version": VERSION, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gw.started)),
                         "uptime_s": int(time.time() - gw.started), "backends": [b.status() for b in gw.backends.values()], "machine": m, "lanes": lanes(gw),
                         "share": gw.share_state(), "counters": {"jobs": totals, "async_jobs": gw.jobs.counters()}, "loaded": loaded,
                         "exposed": gw.exposed(), "last_manager_seen_at": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gw.manager_seen)) if gw.manager_seen else None)})


async def h_health(request):
    gw = request.app["gw"]
    ok = any(b.healthy for b in gw.backends.values())
    return web.json_response({"ok": ok, "node_id": gw.node_id, "backends": {n: b.healthy for n, b in gw.backends.items()}}, status=200 if ok else 503,
                             headers={"X-Node-Id": gw.node_id})


# -- the queue
def queue_rows(gw):
    rows = []
    for name, sch in gw.schedulers.items():
        for j in sch.snapshot()["jobs"]:
            c = gw.calls.get(j["id"])
            row = {"id": j["id"], "lane": name, "model": j["model"], "class": j["class"], "kind": j["kind"], "principal": j["principal"], "state": j["state"],
                   "waited_ms": int(j.get("waited_s", 0) * 1000) if "waited_s" in j else None, "elapsed_ms": int(j.get("elapsed_s", 0) * 1000) if "elapsed_s" in j else None,
                   "expected_wait_ms": int(sch.expected_wait(j["class"], j["model"]) * 1000) if j["state"] == "queued" else 0}
            if c:
                row.update({"requested_model": c.requested, "key": c.caller.token_name, "face": c.face, "mode": c.mode, "job": c.async_job,
                            "queued_at": c.accepted_at, "started_at": c.started_at, "origin_request": c.origin_request})
            rows.append(row)
    return rows


async def h_queue(request):
    gw = request.app["gw"]
    await node_caller(request)
    return envelope(gw, {"queue": queue_rows(gw), "lanes": lanes(gw)})   # the lanes ride along: one call draws a queue page


async def read_body(request):
    from .server import read_json
    return await read_json(request) if request.can_read_body else {}


async def h_queue_priority(request):
    from .server import ApiError
    gw = request.app["gw"]
    await node_caller(request)
    body = await read_body(request)
    jid = request.match_info["id"]
    cls = body.get("class")
    if cls is None and body.get("priority") is not None:
        cls = next((n for n, c in gw.catalog.classes.items() if c["priority"] == int(body["priority"])), None)
    if cls not in gw.catalog.classes:
        raise ApiError(400, "bad_class", f"class must be one of {', '.join(gw.catalog.classes)}")
    for sch in gw.schedulers.values():
        if sch.reprioritise(jid, cls):
            c = gw.calls.get(jid)
            if c:
                c.cls = cls
            await gw.ledger_write({"event": "queue.priority", "principal_ref": (await gw.caller(request)).ref, "status": "ok", "reason": f"{jid} -> {cls}", "detail": {"job": jid, "class": cls}})
            return envelope(gw, {"id": jid, "class": cls, "state": "queued"})
    raise ApiError(404, "not_queued", f"no queued job {jid} (running jobs keep their class)")


async def h_queue_cancel(request):
    from .server import ApiError
    gw = request.app["gw"]
    caller = await node_caller(request)
    jid = request.match_info["id"]
    for sch in gw.schedulers.values():
        if sch.cancel_queued(jid):
            await gw.ledger_write({"event": "queue.cancel", "principal_ref": caller.ref, "status": "ok", "reason": f"{jid} queued", "detail": {"job": jid, "state": "queued"}})
            return envelope(gw, {"id": jid, "cancelled": True, "state": "queued"})
    c = gw.calls.get(jid)
    if c and c.aio_task and not c.aio_task.done():
        c.cancel_reason = "operator"
        c.aio_task.cancel()
        await gw.ledger_write({"event": "queue.cancel", "principal_ref": caller.ref, "status": "ok", "reason": f"{jid} running", "detail": {"job": jid, "state": "running"}})
        return envelope(gw, {"id": jid, "cancelled": True, "state": "running"})
    raise ApiError(404, "not_found", f"no queued or running job {jid}")


async def h_queue_pause(request):
    return await _pause(request, True)


async def h_queue_resume(request):
    return await _pause(request, False)


async def _pause(request, paused):
    from .server import ApiError
    gw = request.app["gw"]
    caller = await node_caller(request)
    body = await read_body(request)
    lane = body.get("lane") or "local"
    names = lane_names(gw, lane)
    if not names:
        raise ApiError(404, "no_lane", f"no lane {lane!r}; lanes: {', '.join(gw.schedulers)} or local|remote|cloud")
    for n in names:
        gw.schedulers[n].pause(paused)
    await gw.ledger_write({"event": "queue.pause" if paused else "queue.resume", "principal_ref": caller.ref, "status": "ok", "reason": lane, "detail": {"lanes": names}})
    return envelope(gw, {"lane": lane, "lanes": names, "paused": paused})


# -- runs
RUN_COLS = ("ledger_id", "ts", "principal_ref", "class", "tier", "requested_model", "route", "attempts", "backend", "model", "queue_wait_ms", "service_ms",
            "gpu_ms", "tokens_in", "tokens_out", "tokens_cached", "cost_actual", "currency", "status", "reason", "error_class", "provider_request_id", "task_ref", "detail")


def run_row(r, full=False):
    d = r.get("detail") or {}
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            d = {}
    out = {"seq": r["ledger_id"], "id": d.get("request"), "at": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else r["ts"], "principal": r["principal_ref"],
           "key": d.get("token"), "face": d.get("face"), "mode": d.get("mode") or "sync", "kind": d.get("kind"), "task": r.get("task_ref"), "job": d.get("job"),
           "requested_model": r["requested_model"], "tier": r["tier"], "backend": r["backend"], "lane": r["backend"], "model": r["model"], "class": r["class"],
           "attempts": r["attempts"], "queue_wait_ms": r["queue_wait_ms"], "service_ms": r["service_ms"], "gpu_ms": r["gpu_ms"],
           "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"], "tokens_cached": r["tokens_cached"],
           "cost": float(r["cost_actual"]) if r["cost_actual"] is not None else None, "currency": r["currency"],
           "status": r["status"], "reason": r["reason"], "error_class": r["error_class"], "provider_request_id": r["provider_request_id"],
           "origin_request": d.get("origin_request"), "origin_node": d.get("origin_node")}
    route = r.get("route")
    if isinstance(route, str):
        try:
            route = json.loads(route)
        except ValueError:
            route = None
    out["route"] = route
    if full:
        out["detail"] = d
    return out


async def h_runs(request):
    from .server import ApiError
    gw = request.app["gw"]
    await node_caller(request)
    q = request.query
    try:
        since, limit = int(q.get("since_seq") or 0), max(1, min(1000, int(q.get("limit") or 200)))
    except ValueError:
        raise ApiError(400, "bad_query", "since_seq and limit are integers")
    where, params = ["event='model.call'", "ledger_id > %s"], [since]
    for key, col in (("status", "status"), ("model", "model"), ("lane", "backend"), ("backend", "backend"), ("principal", "principal_ref"), ("class", "class")):
        if q.get(key):
            where.append(f"{col} = %s"); params.append(q[key])
    if q.get("key"):
        where.append("detail->>'token' = %s"); params.append(q["key"])
    rows = await gw.db.fetch(f"SELECT {', '.join(RUN_COLS)} FROM maluos_ledger WHERE {' AND '.join(where)} ORDER BY ledger_id LIMIT %s", params + [limit])
    return envelope(gw, {"runs": [run_row(r) for r in rows], "since_seq": since, "limit": limit, "more": len(rows) == limit})


async def h_run(request):
    from .server import ApiError
    gw = request.app["gw"]
    await node_caller(request)
    try:
        seq = int(request.match_info["seq"])
    except ValueError:
        raise ApiError(400, "bad_seq", "seq is the run's sequence number")
    r = await gw.db.fetchone(f"SELECT {', '.join(RUN_COLS)} FROM maluos_ledger WHERE event='model.call' AND ledger_id=%s", (seq,))
    if not r:
        raise ApiError(404, "not_found", f"no run {seq}")
    return envelope(gw, {"run": run_row(r, full=True)})


# -- models
def model_rows(gw):
    cat = gw.catalog
    out = []
    for t in cat.tiers:
        out.append({"name": t, "kind": "tier", "ladder": [f"{a['backend']}/{a['model']}" for a in sorted(cat.aliases, key=lambda a: a["position"]) if a["tier"] == t]})
    for a in cat.aliases:
        if a["tier"] is None:
            out.append({"name": a["name"], "kind": "alias", "backend": a["backend"], "model": a["model"]})
    for b in gw.backends.values():
        loaded = {m.get("name") for m in b.loaded} | {m.get("model") for m in b.loaded}
        for name, info in sorted(b.models.items()):
            if name.endswith(":latest") and name[:-7] in b.models:
                continue
            out.append({"name": name, "kind": "model", "backend": b.name, "lane": lane_kind(b), "loaded": name in loaded or (name + ":latest") in loaded,
                        "size": (info or {}).get("size"), "capabilities": b.capabilities(name) or None})
    return out


async def h_models(request):
    from .server import ApiError
    gw = request.app["gw"]
    await node_caller(request)
    try:
        since = int(request.query.get("since_seq") or 0)
    except ValueError:
        raise ApiError(400, "bad_query", "since_seq is an integer")
    seq = gw.catalog_seq()
    return envelope(gw, {"seq": seq, "models": model_rows(gw) if since < seq else []})


# -- keys
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def key_row(r):
    return {"id": r["token_id"], "name": r["name"], "kind": r["kind"], "principal": r["principal_ref"], "limits": r["limits"] or {},
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None, "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
            "revoked_at": r["revoked_at"].isoformat() if r.get("revoked_at") else None, "last_used_at": r["last_used_at"].isoformat() if r.get("last_used_at") else None,
            "policy": r.get("policy")}


async def key_rows(gw, where="true", params=()):
    return await gw.db.fetch(f"""SELECT t.token_id, t.name, t.kind, t.principal_ref, t.limits, t.created_at, t.expires_at, t.revoked_at, t.last_used_at,
                                        (SELECT jsonb_build_object('class', p.default_class, 'cloud_allowed', p.cloud_allowed, 'remote_allowed', p.remote_allowed, 'tiers', p.allowed_tiers)
                                           FROM maluos_policy p WHERE p.subject_kind='principal' AND p.subject_ref=t.principal_ref) AS policy
                                   FROM maluos_token t WHERE t.kind IN ('inference','node') AND {where} ORDER BY t.token_id""", params)


async def h_keys(request):
    gw = request.app["gw"]
    await node_caller(request)
    return envelope(gw, {"keys": [key_row(r) for r in await key_rows(gw)]})


def parse_expires(exp):
    if not exp:
        return None
    m = re.match(r"^(\d+)([hdw])$", str(exp))
    if m:
        return f"now() + interval '{int(m.group(1))} {dict(h='hours', d='days', w='weeks')[m.group(2)]}'"
    return None


async def issue_key(gw, body, created_by):
    """Mint a key: the principal key:<name>, its policy, the token. Returns (row, key) with the key shown once."""
    from .server import ApiError
    name, kind = body.get("name"), body.get("kind") or "inference"
    if not name or not KEY_RE.match(str(name)):
        raise ApiError(400, "bad_name", "name: letters, digits, _ . - (64 at most)")
    if kind not in ("inference", "node"):
        raise ApiError(400, "bad_kind", "kind: inference or node")
    for k in body:
        if k not in ("name", "kind", "class", "cloud_allowed", "remote_allowed", "tiers", "max_concurrent", "expires"):
            raise ApiError(400, "bad_field", f"unknown field {k}")
    cls = body.get("class")
    if cls is not None and cls not in gw.catalog.classes:
        raise ApiError(400, "bad_class", f"class must be one of {', '.join(gw.catalog.classes)}")
    tiers = body.get("tiers")
    if tiers is not None and not isinstance(tiers, list):
        raise ApiError(400, "bad_tiers", "tiers is a list of tier names")
    ref = f"key:{name}"
    if await gw.db.fetchone("SELECT 1 FROM maluos_token WHERE name=%s AND kind IN ('inference','node') AND revoked_at IS NULL", (name,)):
        raise ApiError(409, "exists", f"a live key named {name} exists (revoke it first)")
    if not await gw.db.fetchone("SELECT 1 FROM maludb_principal WHERE principal_ref=%s", (ref,)):
        try:
            await gw.db.execute("SELECT maludb_principal_upsert(%s, 'service', %s, 'org')", (ref, f"inference key {name}" if kind == "inference" else f"node key {name} (a manager)"))
        except Exception as e:
            raise ApiError(503, "no_principal", f"cannot create the principal {ref}: {str(e)[:120]} (sudo maluctl gateway key issue creates it as root)")
    gw.principal_cache.pop(ref, None)
    if kind == "inference":
        await gw.db.execute("""INSERT INTO maluos_policy (subject_kind, subject_ref, default_class, cloud_allowed, remote_allowed, allowed_tiers)
                               VALUES ('principal', %s, %s, %s, %s, %s)
                               ON CONFLICT (subject_kind, subject_ref) DO UPDATE SET default_class=EXCLUDED.default_class, cloud_allowed=EXCLUDED.cloud_allowed,
                                   remote_allowed=EXCLUDED.remote_allowed, allowed_tiers=EXCLUDED.allowed_tiers, updated_at=now()""",
                            (ref, cls, bool(body.get("cloud_allowed", False)), bool(body.get("remote_allowed", False)), tiers))
    limits = {}
    if body.get("max_concurrent") is not None:
        limits["max_concurrent"] = max(1, int(body["max_concurrent"]))
    key = "mg_" + secrets.token_urlsafe(32)
    h = hashlib.sha256(key.encode()).hexdigest()
    exp = parse_expires(body.get("expires"))
    row = await gw.db.fetchone(f"""INSERT INTO maluos_token (principal_ref, name, kind, limits, token_hash, created_by, expires_at)
                                   VALUES (%s, %s, %s, %s, %s, %s, {exp or 'NULL'}) RETURNING token_id""", (ref, name, kind, json.dumps(limits), h, created_by))
    await gw.reload_catalog()
    await gw.ledger_write({"event": "key.issue", "principal_ref": created_by, "status": "ok", "reason": f"{kind} key {name}", "detail": {"key": name, "kind": kind, "principal": ref, "limits": limits}})
    rows = await key_rows(gw, "t.token_id=%s", (row["token_id"],))
    return rows[0], key


async def h_key_create(request):
    from .server import read_json
    gw = request.app["gw"]
    caller = await node_caller(request)
    body = await read_json(request)
    row, key = await issue_key(gw, body, caller.ref)
    out = key_row(row); out["key"] = key
    return envelope(gw, out)


async def find_key(gw, kid):
    from .server import ApiError
    rows = await key_rows(gw, "(t.token_id::text=%s OR t.name=%s) AND t.revoked_at IS NULL", (str(kid), str(kid)))
    if not rows:
        raise ApiError(404, "not_found", f"no live key {kid}")
    return rows[0]


async def h_key_patch(request):
    from .server import ApiError, read_json
    gw = request.app["gw"]
    caller = await node_caller(request)
    body = await read_json(request)
    r = await find_key(gw, request.match_info["id"])
    sets, params = [], []
    for k in body:
        if k not in ("class", "cloud_allowed", "remote_allowed", "tiers", "max_concurrent"):
            raise ApiError(400, "bad_field", f"unknown field {k}")
    if "class" in body:
        if body["class"] is not None and body["class"] not in gw.catalog.classes:
            raise ApiError(400, "bad_class", f"class must be one of {', '.join(gw.catalog.classes)}")
        sets.append("default_class=%s"); params.append(body["class"])
    for k, col in (("cloud_allowed", "cloud_allowed"), ("remote_allowed", "remote_allowed")):
        if k in body:
            sets.append(f"{col}=%s"); params.append(bool(body[k]))
    if "tiers" in body:
        sets.append("allowed_tiers=%s"); params.append(body["tiers"])
    if sets and r["kind"] == "inference":
        await gw.db.execute("INSERT INTO maluos_policy (subject_kind, subject_ref) VALUES ('principal', %s) ON CONFLICT DO NOTHING", (r["principal_ref"],))
        await gw.db.execute(f"UPDATE maluos_policy SET {', '.join(sets)}, updated_at=now() WHERE subject_kind='principal' AND subject_ref=%s", params + [r["principal_ref"]])
    if "max_concurrent" in body:
        limits = dict(r["limits"] or {})
        if body["max_concurrent"] is None:
            limits.pop("max_concurrent", None)
        else:
            limits["max_concurrent"] = max(1, int(body["max_concurrent"]))
        await gw.db.execute("UPDATE maluos_token SET limits=%s, updated_at=now() WHERE token_id=%s", (json.dumps(limits), r["token_id"]))
        gw.token_cache.clear()
    await gw.reload_catalog()
    await gw.ledger_write({"event": "key.update", "principal_ref": caller.ref, "status": "ok", "reason": f"key {r['name']}", "detail": {"key": r["name"], "changes": body}})
    return envelope(gw, key_row(await find_key(gw, r["token_id"])))


async def h_key_delete(request):
    gw = request.app["gw"]
    caller = await node_caller(request)
    r = await find_key(gw, request.match_info["id"])
    await gw.db.execute("UPDATE maluos_token SET revoked_at=now(), updated_at=now() WHERE token_id=%s", (r["token_id"],))
    gw.token_cache.clear()
    await gw.ledger_write({"event": "key.revoke", "principal_ref": caller.ref, "status": "ok", "reason": f"key {r['name']}", "detail": {"key": r["name"], "id": r["token_id"]}})
    return envelope(gw, {"id": r["token_id"], "name": r["name"], "revoked": True})


def add_routes(r):
    p = "/node/v1"
    r.add_get(p + "/status", h_status)
    r.add_get(p + "/health", h_health)
    r.add_get(p + "/queue", h_queue)
    r.add_post(p + "/queue/pause", h_queue_pause)
    r.add_post(p + "/queue/resume", h_queue_resume)
    r.add_post(p + "/queue/{id}/priority", h_queue_priority)
    r.add_delete(p + "/queue/{id}", h_queue_cancel)
    r.add_get(p + "/runs", h_runs)
    r.add_get(p + "/runs/{seq}", h_run)
    r.add_get(p + "/models", h_models)
    r.add_get(p + "/keys", h_keys)
    r.add_post(p + "/keys", h_key_create)
    r.add_patch(p + "/keys/{id}", h_key_patch)
    r.add_delete(p + "/keys/{id}", h_key_delete)
