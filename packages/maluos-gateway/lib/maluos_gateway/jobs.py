"""Async jobs (Phase 13 G2, docs/inference-node-api.md §5): a face request
with mode async is accepted at once (202, a job id) and runs as a task; the
caller polls /v1/jobs/{id} for the result in the face's own shape, or
cancels it. Finished jobs are kept in memory for result_retention_hours and
at most max_finished_jobs; the ledger keeps the metadata for ever."""
import asyncio, secrets, time


class Jobs:
    def __init__(self, gw):
        self.gw = gw
        self.jobs = {}
        self.totals = {"accepted": 0, "done": 0, "failed": 0, "cancelled": 0}

    def submit(self, caller, face, kind, requested, runner):
        """runner() is a coroutine that prepares and executes the call and returns the face-shaped result;
        it must set job['call'] once the call is prepared (so the queue and the ledger can name it)."""
        jid = "job-" + secrets.token_hex(8)
        job = {"id": jid, "principal": caller.ref, "key": caller.token_name, "face": face, "kind": kind, "requested_model": requested,
               "accepted_at": time.time(), "finished_at": None, "call": None, "result": None, "error": None, "cancel_reason": None, "task": None}
        self.jobs[jid] = job
        self.totals["accepted"] += 1

        async def run():
            try:
                job["result"] = await runner(job)
                self.totals["done"] += 1
            except asyncio.CancelledError:
                job["error"] = {"code": "cancelled", "message": f"cancelled by {job['cancel_reason'] or 'the caller'}"}
                self.totals["cancelled"] += 1
            except Exception as e:
                job["error"] = {"code": getattr(e, "code", None) or getattr(e, "error_class", None) or e.__class__.__name__,
                                "message": str(getattr(e, "message", e))[:300], "status": getattr(e, "status", 500)}
                self.totals["failed"] += 1
            finally:
                job["finished_at"] = time.time()
        job["task"] = self.gw.spawn(run())
        return job

    def status(self, job):
        if job["finished_at"] is None:
            c = job["call"]
            return "running" if c and c.started_at else "queued"
        if job["error"] is None:
            return "done"
        return "cancelled" if job["error"].get("code") == "cancelled" else "failed"

    def describe(self, job, with_result=True):
        c = job["call"]
        st = self.status(job)
        d = {"job_id": job["id"], "status": st, "face": job["face"], "kind": job["kind"], "requested_model": job["requested_model"],
             "accepted_at": job["accepted_at"], "finished_at": job["finished_at"], "principal": job["principal"], "key": job["key"],
             "status_url": f"/v1/jobs/{job['id']}", "result_url": f"/v1/jobs/{job['id']}"}
        if c:
            d.update({"call": c.id, "lane": c.backend, "model": c.model, "class": c.cls, "queue_wait_ms": c.queued_ms, "started_at": c.started_at})
            if st == "queued" and c.backend in self.gw.schedulers:
                d["expected_wait_ms"] = int(self.gw.schedulers[c.backend].expected_wait(c.cls, c.model) * 1000)
        if st == "done" and with_result:
            d["result"] = job["result"]
        if job["error"]:
            d["error"] = job["error"]
        return d

    def cancel(self, job, reason="the caller"):
        if job["finished_at"] is not None:
            return False
        job["cancel_reason"] = reason
        if job["call"] is not None:
            job["call"].cancel_reason = reason
        if job["task"] and not job["task"].done():
            job["task"].cancel()
        return True

    def counters(self):
        return dict(self.totals, live=sum(1 for j in self.jobs.values() if j["finished_at"] is None))

    def prune(self, retention_s, max_finished):
        now = time.time()
        finished = sorted((j for j in self.jobs.values() if j["finished_at"] is not None), key=lambda j: j["finished_at"])
        for j in finished:
            if now - j["finished_at"] > retention_s or len(finished) > max_finished:
                self.jobs.pop(j["id"], None); finished.remove(j)
