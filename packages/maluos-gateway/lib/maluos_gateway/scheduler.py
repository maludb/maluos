"""Admission control and dispatch for one backend (FR-20 to FR-26).

Strict priority between classes, round-robin by principal within a class,
a cap on concurrent jobs, model affinity (keep serving the resident model
unless other work has waited too long), and a continuously updated expected
wait per class from measured service times.
"""
import asyncio, time

DEFAULT_SERVICE_S = 8.0
DEFAULT_LOAD_S = 4.0


class AdmissionError(Exception):
    def __init__(self, code, message, expected_wait=None):
        super().__init__(message); self.code, self.message, self.expected_wait = code, message, expected_wait


class Job:
    __slots__ = ("id", "principal", "cls", "model", "kind", "est_s", "enqueued", "started", "fut", "cancelled")

    def __init__(self, id, principal, cls, model, kind="chat"):
        self.id, self.principal, self.cls, self.model, self.kind = id, principal, cls, model, kind
        self.est_s = None; self.enqueued = self.started = None; self.fut = None; self.cancelled = False


class ModelStats:
    __slots__ = ("service_s", "load_s", "n", "tokens_per_s")

    def __init__(self):
        self.service_s, self.load_s, self.n, self.tokens_per_s = None, None, 0, None

    def observe(self, service_s, load_s=None, tokens=None):
        a = 0.3
        self.service_s = service_s if self.service_s is None else (1 - a) * self.service_s + a * service_s
        if load_s is not None and load_s > 0.05:
            self.load_s = load_s if self.load_s is None else (1 - a) * self.load_s + a * load_s
        if tokens and service_s > 0:
            tps = tokens / service_s
            self.tokens_per_s = tps if self.tokens_per_s is None else (1 - a) * self.tokens_per_s + a * tps
        self.n += 1


class Scheduler:
    def __init__(self, backend, max_concurrent=1, classes=None, affinity=None, principal_limit=20):
        self.backend = backend
        self.cap = max(1, int(max_concurrent or 1))
        self.classes = classes or {}
        self.affinity = {"max_wait_s": 20, "max_backlog": 4, **(affinity or {})}
        self.principal_limit = principal_limit
        self.queued, self.running = [], {}
        self.resident = None
        self.stats = {}
        self.last_served, self._seq = {}, 0
        self.totals = {"admitted": 0, "rejected": 0, "cancelled": 0, "completed": 0}

    # -- configuration
    def configure(self, max_concurrent=None, classes=None, affinity=None, principal_limit=None):
        if max_concurrent:
            self.cap = max(1, int(max_concurrent))
        if classes is not None:
            self.classes = classes
        if affinity:
            self.affinity.update(affinity)
        if principal_limit:
            self.principal_limit = principal_limit
        self._dispatch()

    def _prio(self, cls):
        c = self.classes.get(cls)
        return c["priority"] if c else 99

    # -- estimates
    def est(self, job):
        st = self.stats.get(job.model)
        s = st.service_s if st and st.service_s else DEFAULT_SERVICE_S
        if job.kind == "embed":
            s = min(s, 1.0)
        if job.model != self.resident:
            s += (st.load_s if st and st.load_s else DEFAULT_LOAD_S)
        return s

    def remaining(self, job):
        return max(0.0, self.est(job) - (time.monotonic() - (job.started or time.monotonic())))

    def expected_wait(self, cls, model=None):
        prio = self._prio(cls)
        work = sum(self.est(j) for j in self.queued if self._prio(j.cls) <= prio)
        work += sum(self.remaining(j) for j in self.running.values())
        free = self.cap - len(self.running)
        if free > 0 and not self.queued:
            return 0.0
        return round(work / self.cap, 1)

    # -- admission
    async def acquire(self, job, max_wait=None):
        cls = self.classes.get(job.cls) or {"max_queue": 100, "max_wait_s": None}
        in_class = sum(1 for j in self.queued if j.cls == job.cls)
        ew = self.expected_wait(job.cls, job.model)
        if in_class >= (cls.get("max_queue") or 100):
            self.totals["rejected"] += 1
            raise AdmissionError("queue_full", f"class {job.cls} queue is full ({in_class}); expected wait {ew}s", ew)
        mine = sum(1 for j in self.queued if j.principal == job.principal)
        if mine >= self.principal_limit:
            self.totals["rejected"] += 1
            raise AdmissionError("principal_queue_full", f"{job.principal} already has {mine} requests queued", ew)
        limit = max_wait if max_wait is not None else cls.get("max_wait_s")
        if limit is not None and ew > float(limit) and not (len(self.running) < self.cap and not self.queued):
            self.totals["rejected"] += 1
            raise AdmissionError("wait_exceeds", f"expected wait {ew}s exceeds the limit {limit}s", ew)
        job.fut = asyncio.get_running_loop().create_future()
        job.enqueued = time.monotonic()
        self.queued.append(job)
        self.totals["admitted"] += 1
        self._dispatch()
        try:
            await job.fut
        except asyncio.CancelledError:
            job.cancelled = True
            if job in self.queued:
                self.queued.remove(job)
            else:
                self.running.pop(job.id, None)
            self.totals["cancelled"] += 1
            self._dispatch()
            raise
        job.started = time.monotonic()

    def release(self, job, service_s=None, load_s=None, tokens=None, switched=None):
        if self.running.pop(job.id, None) is not None:
            self.totals["completed"] += 1
        if service_s is not None:
            self.stats.setdefault(job.model, ModelStats()).observe(service_s, load_s, tokens)
        if job.kind != "embed" or self.resident is None:
            self.resident = job.model
        self._dispatch()

    # -- dispatch
    def _dispatch(self):
        while len(self.running) < self.cap and self.queued:
            job = self._pick()
            self.queued.remove(job)
            self.running[job.id] = job
            job.started = time.monotonic()
            if not job.fut.done():
                job.fut.set_result(True)

    def _pick(self):
        top = min(self._prio(j.cls) for j in self.queued)
        cand = [j for j in self.queued if self._prio(j.cls) == top]
        if self.resident and any(j.model == self.resident for j in cand):
            others = [j for j in cand if j.model != self.resident]
            if others:
                oldest = time.monotonic() - min(j.enqueued for j in others)
                if oldest < self.affinity["max_wait_s"] and len(others) < self.affinity["max_backlog"]:
                    cand = [j for j in cand if j.model == self.resident]
            else:
                cand = [j for j in cand if j.model == self.resident]
        job = min(cand, key=lambda j: (self.last_served.get(j.principal, 0), j.enqueued))
        self._seq += 1
        self.last_served[job.principal] = self._seq
        return job

    # -- reporting
    def snapshot(self):
        now = time.monotonic()
        by_class = {}
        for name in sorted(self.classes, key=lambda n: self.classes[n]["priority"]):
            by_class[name] = {"queued": sum(1 for j in self.queued if j.cls == name),
                              "expected_wait_s": self.expected_wait(name)}
        return {
            "backend": self.backend, "capacity": self.cap, "resident": self.resident,
            "queued": len(self.queued), "running": len(self.running),
            "classes": by_class,
            "jobs": [{"id": j.id, "principal": j.principal, "class": j.cls, "model": j.model, "kind": j.kind,
                      "state": "running", "elapsed_s": round(now - j.started, 1)} for j in self.running.values()]
                    + [{"id": j.id, "principal": j.principal, "class": j.cls, "model": j.model, "kind": j.kind,
                        "state": "queued", "waited_s": round(now - j.enqueued, 1)} for j in self.queued],
            "models": {m: {"service_s": round(s.service_s, 2) if s.service_s else None,
                           "load_s": round(s.load_s, 2) if s.load_s else None,
                           "tokens_per_s": round(s.tokens_per_s, 1) if s.tokens_per_s else None, "n": s.n}
                       for m, s in self.stats.items()},
            "totals": dict(self.totals),
        }
