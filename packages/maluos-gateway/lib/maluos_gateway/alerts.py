"""Alerts (FR-44): budget thresholds, a backend unhealthy beyond a limit, a
sudden change in a principal's usage, work lost in a restart. Delivered to the
journal, the ledger (event alert.<kind>), the tenant's memory as an episode,
and to hooks in /etc/maluos/alert-hooks.d (JSON on stdin)."""
import asyncio, glob, json, os, time


def log(msg):
    import sys
    print(f"maluos-gateway: {msg}", file=sys.stderr, flush=True)


class Alerts:
    def __init__(self, gw):
        self.gw = gw
        self.fired = {}          # once_key -> ts

    def cfg(self):
        return self.gw.cfg.get("alerts") or {}

    async def fire(self, kind, title, detail=None, once_key=None, cooldown_s=3600):
        detail = dict(detail or {})
        now = time.time()
        if once_key:
            if now - self.fired.get(once_key, 0) < cooldown_s:
                return False
            self.fired[once_key] = now
        log(f"ALERT {kind}: {title}")
        try:
            await self.gw.db.ledger(event=f"alert.{kind}", status="ok", reason=title[:200], detail=detail, principal_ref=detail.get("principal"))
        except Exception as e:
            log(f"alert ledger row failed: {e.__class__.__name__}")
        try:
            await self.gw.db.execute("SELECT maluos_record_episode('maluos.alert', %s, %s, %s, 'internal')",
                                     (title[:200], json.dumps(detail)[:1000], json.dumps(dict(detail, kind=kind, source="maluos-gateway"))))
        except Exception as e:
            log(f"alert episode not recorded: {e.__class__.__name__}: {str(e)[:120]}")
        await self.hooks({"source": "maluos-gateway", "kind": kind, "title": title, "detail": detail, "ts": now})
        return True

    def clear(self, once_key):
        self.fired.pop(once_key, None)

    async def hooks(self, payload):
        hooks_dir = self.cfg().get("hooks_dir") or "/etc/maluos/alert-hooks.d"
        exes = [f for f in sorted(glob.glob(os.path.join(hooks_dir, "*"))) if os.access(f, os.X_OK) and os.path.isfile(f)]
        data = json.dumps(payload, default=str).encode()
        for exe in exes:
            try:
                proc = await asyncio.create_subprocess_exec(exe, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(proc.communicate(data), timeout=15)
            except Exception as e:
                log(f"alert hook {exe}: {e.__class__.__name__}")

    async def monitor_loop(self):
        """Backends down beyond the limit; usage anomalies."""
        down_since = {}
        last_usage_check = 0
        while True:
            await asyncio.sleep(float(self.cfg().get("check_s") or 30))
            try:
                limit = float(self.cfg().get("backend_down_s") or 300)
                now = time.time()
                for name, b in list(self.gw.backends.items()):
                    if not b.enabled:
                        down_since.pop(name, None); continue
                    if b.healthy is False:
                        down_since.setdefault(name, now)
                        if now - down_since[name] >= limit:
                            await self.fire("backend_down", f"backend {name} unhealthy for {int(now - down_since[name])}s: {b.last_error or '?'}",
                                            {"backend": name, "kind": b.kind, "endpoint": b.endpoint, "error": b.last_error, "down_s": int(now - down_since[name])},
                                            once_key=f"backend_down:{name}", cooldown_s=float(self.cfg().get("backend_down_repeat_s") or 3600))
                    elif b.healthy and name in down_since:
                        was = now - down_since.pop(name)
                        if f"backend_down:{name}" in self.fired:
                            self.clear(f"backend_down:{name}")
                            await self.fire("backend_recovered", f"backend {name} healthy again after {int(was)}s", {"backend": name, "down_s": int(was)})
                ua = self.cfg().get("usage_anomaly") or {}
                if ua.get("enabled", True) and now - last_usage_check >= float(ua.get("check_s") or 300):
                    last_usage_check = now
                    rows = await self.gw.db.fetch("""
                        WITH recent AS (SELECT principal_ref, count(*) AS n FROM maluos_ledger
                                         WHERE event='model.call' AND ts >= now() - interval '1 hour' AND principal_ref IS NOT NULL GROUP BY 1),
                             base AS (SELECT principal_ref, count(*) / 168.0 AS per_hour FROM maluos_ledger
                                       WHERE event='model.call' AND ts >= now() - interval '7 days' AND ts < now() - interval '1 hour' GROUP BY 1)
                        SELECT r.principal_ref, r.n, coalesce(b.per_hour, 0) AS per_hour FROM recent r LEFT JOIN base b USING (principal_ref)""")
                    for r in rows:
                        if r["n"] >= int(ua.get("min_calls") or 20) and r["n"] > float(ua.get("factor") or 3) * max(float(r["per_hour"]), 1.0):
                            await self.fire("usage_anomaly", f"{r['principal_ref']} made {r['n']} calls in the last hour (average {float(r['per_hour']):.1f}/h)",
                                            {"principal": r["principal_ref"], "calls_last_hour": r["n"], "average_per_hour": round(float(r["per_hour"]), 2)},
                                            once_key=f"usage:{r['principal_ref']}", cooldown_s=6 * 3600)
            except Exception as e:
                log(f"alert monitor: {e.__class__.__name__}: {str(e)[:160]}")
