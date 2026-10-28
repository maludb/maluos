"""The runner service: the runner API (8815) and the ledger proxy (8816) in one process.

    POST /runs                 {agent_member_id, trigger, instructions, requested_by?, duty_id?, parent_run_id?} -> 202 {run_id}
    GET  /runs/{id}            the run as the database has it, plus its live events
    POST /runs/{id}/cancel
    POST /runs/{id}/events     from the bos_hermes observer plugin (authenticated by the run's proxy key)
    GET  /health

Callers present X-Runner-Key (shared with PHP through config/.env). A run is refused, never
queued, when its agent is already running: one Hermes home, one process (H6 adds the queue).
The runner owns the run's life — row, credentials, finalisation, the completion callback — so
nothing depends on which lifecycle hooks a harness happens to fire.
"""
from __future__ import annotations

import asyncio
import collections
import hmac
import logging
import secrets

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import config, evals, ledger_proxy, memory, registry, run_token, scheduler, skills, store
from .harness import RunContext, RunOutcome

log = logging.getLogger("agent_runner")
TRIGGERS = {"duty", "manual", "delegation", "location_task", "chat", "eval"}
_slots: asyncio.Semaphore | None = None
_tasks: dict[int, asyncio.Task] = {}
_events: dict[int, collections.deque] = {}
_event_seq: dict[int, int] = {}
_evals: dict[int, asyncio.Task] = {}


def _record(run_id: int, event: dict) -> None:
    """An event goes to the live view AND to the database (db/122). Kept: the runner's memory was the
    only place tool calls, their outcomes and their durations existed, and a restart lost them."""
    _events.setdefault(run_id, collections.deque(maxlen=500)).append(event)
    _event_seq[run_id] = seq = _event_seq.get(run_id, 0) + 1

    async def keep() -> None:
        try:
            await store.add_event(run_id, seq, event)
        except Exception as exc:  # noqa: BLE001 - telemetry never breaks a run
            log.warning("run %s: event %s was not kept: %s", run_id, seq, exc)
    asyncio.get_running_loop().create_task(keep())


def _authorised(request: Request) -> bool:
    return hmac.compare_digest(request.headers.get("x-runner-key", ""), config.require("RUNNER_KEY", 32))


async def launch(*, agent_member_id: int, trigger: str, instructions: str, requested_by: int | None = None,
                 duty_id: int | None = None, parent_run_id: int | None = None,
                 config_version_id: int | None = None) -> dict:
    """Start one run — the single door for the API, the duty scheduler, delegation continuations and
    eval trials. `config_version_id` names the version to run (an evaluation weighing a change names
    one that is not live); omitted, it is the agent's active version.
    Raises store.RunRefused (agent inactive, busy, no active version) or LookupError (no harness built)."""
    agent = await store.load_agent(agent_member_id, config_version_id)
    harness = registry.get(agent["model"]["harness"])
    request_id = "run-" + secrets.token_hex(8)
    run_id = await store.create_run(
        agent=agent, trigger=trigger, instructions=instructions, request_id=request_id, harness=harness.key,
        sdk_version=await asyncio.to_thread(harness.version), requested_by=requested_by,
        duty_id=duty_id, parent_run_id=parent_run_id)
    _events[run_id] = collections.deque(maxlen=500)
    _tasks[run_id] = asyncio.create_task(_run(run_id, request_id, agent, harness, instructions, trigger))
    return {"run_id": run_id, "request_id": request_id, "status": "running"}


async def start_run(request: Request) -> JSONResponse:
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    instructions = str(body.get("instructions") or "").strip()
    trigger = body.get("trigger") or "manual"
    if not instructions or trigger not in TRIGGERS or not isinstance(body.get("agent_member_id"), int):
        return JSONResponse({"error": "agent_member_id, instructions and a known trigger are required."}, status_code=422)
    if trigger == "delegation" and not isinstance(body.get("parent_run_id"), int):
        return JSONResponse({"error": "A delegated run names the run that delegated it."}, status_code=422)
    try:
        started = await launch(agent_member_id=body["agent_member_id"], trigger=trigger, instructions=instructions,
                               requested_by=body.get("requested_by"), duty_id=body.get("duty_id"),
                               parent_run_id=body.get("parent_run_id"))
    except (store.RunRefused, LookupError) as refused:
        return JSONResponse({"error": str(refused)}, status_code=409)
    return JSONResponse(started, status_code=202)


async def _run(run_id: int, request_id: str, agent: dict, harness, instructions: str, trigger: str) -> None:
    global _slots
    _slots = _slots or asyncio.Semaphore(config.MAX_WORKERS)
    timeout = int((agent.get("runtime_config") or {}).get("run_timeout_seconds") or config.DEFAULT_RUN_TIMEOUT)
    outcome = RunOutcome("failed", error="The run did not start.")
    try:
        async with _slots:
            context = RunContext(
                run_id=run_id, request_id=request_id, agent=agent, instructions=instructions, trigger=trigger,
                run_token=run_token.mint_run_token(agent["member_id"], run_id, timeout + 60, config.require("ACTION_TOKEN_KEY", 32)),
                proxy_key=run_token.mint_proxy_key(run_id, timeout + 60, config.require("PROXY_KEY_SECRET", 32)),
                timeout_seconds=timeout)
            context.memory = await memory.context_for(agent, instructions)
            for warning in context.memory.get("warnings", []):
                _record(run_id, {"event": "warning", "message": warning})
            if context.memory.get("content_flags"):
                try:
                    await store.add_content_flags(agent["member_id"], run_id, context.memory["content_flags"])
                except Exception as exc:  # noqa: BLE001 - recording a flag never stops a run
                    log.warning("run %s: content flags were not recorded: %s", run_id, exc)
            # Skills first, then the profile: the Claude persona carries the synced skills inline
            # (claude_render, A7 g), so what is on disk when prepare() renders must be this run's.
            profile_dir = config.AGENTS_DIR / str(agent["member_id"])
            skills_snapshot, skill_warnings = await skills.sync_down(agent, profile_dir)
            for warning in skill_warnings:
                _record(run_id, {"event": "warning", "message": warning})
            prepared = await asyncio.to_thread(harness.prepare, context)
            prepared.skills = skills_snapshot
            await store.note_prepared(run_id, prepared.profile_hash, prepared.skills)
            for warning in prepared.warnings:
                _record(run_id, {"event": "warning", "message": warning})
            outcome = await harness.execute(prepared)
    except asyncio.CancelledError:
        outcome = RunOutcome("cancelled")
    except Exception as exc:
        log.exception("run %s crashed", run_id)
        outcome = RunOutcome("failed", error=f"{type(exc).__name__}: {exc}")

    if run_id in ledger_proxy.unledgered_runs:        # "every model call, no exceptions"
        ledger_proxy.unledgered_runs.discard(run_id)
        outcome = RunOutcome("failed", result=outcome.result, usage_report=outcome.usage_report,
                             error="A model call could not be written to the prompt ledger; the run is void.")
    # An action that needed the manager's approval answered pending_approval and changed nothing;
    # the run did its part and now waits. H3 executes the action on approval.
    waiting_on = await store.pending_approval_for(run_id) if outcome.status == "succeeded" else None
    if waiting_on is not None:
        outcome.status = "awaiting_approval"
    totals = await store.finish_run(run_id, status=outcome.status, result=outcome.result, error=outcome.error,
                                    usage_report=outcome.usage_report, approval_request_id=waiting_on)
    if outcome.status in ("succeeded", "awaiting_approval"):       # a skill the agent wrote becomes a proposal
        for message in await skills.sync_up(run_id, config.AGENTS_DIR / str(agent["member_id"])):
            _record(run_id, {"event": "skill", "message": message})
    if outcome.status in ("succeeded", "awaiting_approval"):       # keep the transcript where session_search finds it
        warning = await memory.archive_run(agent, run_id, instructions, await store.last_payload(run_id))
        if warning:
            _record(run_id, {"event": "warning", "message": warning})
    _tasks.pop(run_id, None)
    await _callback(run_id, outcome.status, totals)
    await scheduler.continue_family(run_id, launch)      # a finished delegation may complete a family


async def _callback(run_id: int, status: str, totals: dict) -> None:
    """The runner holds no PHP write path and no activity_log grant: PHP logs agent_run.finish."""
    try:
        async with httpx.AsyncClient(base_url=config.PHP_BASE, timeout=10.0) as client:
            await client.post("/agents/run-callback.php", data={"agent_run": run_id, "status": status, **totals},
                              headers={"X-Runner-Key": config.require("RUNNER_KEY", 32)})
    except Exception:
        log.warning("run %s: completion callback failed", run_id, exc_info=True)


async def get_run(request: Request) -> JSONResponse:
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    run_id = int(request.path_params["run_id"])
    run = await store.get_run(run_id)
    if run is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    run = {k: (str(v) if v is not None and not isinstance(v, (int, str)) else v) for k, v in run.items()}
    return JSONResponse({**run, "events": list(_events.get(run_id, []))})


async def cancel_run(request: Request) -> JSONResponse:
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    run_id = int(request.path_params["run_id"])
    run = await store.get_run(run_id)
    if run is None or run["status"] != "running":
        return JSONResponse({"error": "That run is not running."}, status_code=409)
    await registry.get(run["harness"]).cancel(run_id)
    return JSONResponse({"run_id": run_id, "status": "cancelling"}, status_code=202)


async def run_events(request: Request) -> JSONResponse:
    """Live telemetry from the harness's observer plugin. Authenticated by the run's own proxy key."""
    run_id = int(request.path_params["run_id"])
    named = run_token.verify_proxy_key(request.headers.get("authorization", ""), config.require("PROXY_KEY_SECRET", 32))
    if named != run_id or run_id not in _events:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    _record(run_id, await request.json())
    return JSONResponse({"ok": True})


async def start_eval_run(request: Request) -> JSONResponse:
    """Run one evaluation, in the background. It answers at once with the run it is working on:
    an evaluation takes minutes (three trials per case) and nothing waits on it — evals advise,
    they never gate (owner, 2026-09-20)."""
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    eval_run_id = body.get("eval_run_id")
    if not isinstance(eval_run_id, int):
        return JSONResponse({"error": "eval_run_id is required."}, status_code=422)
    if eval_run_id in _evals and not _evals[eval_run_id].done():
        return JSONResponse({"error": "That evaluation is already running."}, status_code=409)
    _evals[eval_run_id] = asyncio.create_task(evals.start(eval_run_id, launch))
    return JSONResponse({"eval_run_id": eval_run_id, "status": "running"}, status_code=202)


async def health(request: Request) -> JSONResponse:
    # `harnesses` is what PHP asks before it lets anyone be hired onto a model: a model_registry
    # row may name a harness nobody has built, and the hire must be refused then, not at dispatch.
    return JSONResponse({"ok": True, "running": sorted(_tasks), "harnesses": registry.built_keys(),
                         # PHP asks before letting anyone be hired onto a subscription model (claude-subscription-auth.md)
                         "subscription": config.subscription_enabled()})


api = Starlette(routes=[
    Route("/runs", start_run, methods=["POST"]),
    Route("/runs/{run_id:int}", get_run, methods=["GET"]),
    Route("/runs/{run_id:int}/cancel", cancel_run, methods=["POST"]),
    Route("/runs/{run_id:int}/events", run_events, methods=["POST"]),
    Route("/eval-runs", start_eval_run, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
])


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for key in ("RUNNER_KEY", "ACTION_TOKEN_KEY", "PROXY_KEY_SECRET"):
        config.require(key, 32)
    await store.pool()
    servers = [uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
               for app, port in ((api, config.API_PORT), (ledger_proxy.app, config.PROXY_PORT))]
    await asyncio.gather(*(s.serve() for s in servers), scheduler.loop(launch), scheduler.message_loop(launch))


if __name__ == "__main__":
    asyncio.run(main())
