"""Observer hooks -> the agent runner's /runs/{id}/events.

This is the run's LIVE telemetry and its tool-call record: which tool, how long, ok or not, under
which turn. It is NOT the prompt ledger — Hermes' hooks never see auxiliary model calls (H0), so
the ledger is the wire-level proxy. Read-only and fail-open: a telemetry problem must never
change or stop a run, so every error is swallowed and posts go out on a background thread.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
import urllib.request

HOOKS = ("on_session_start", "pre_api_request", "post_api_request", "api_request_error",
         "pre_tool_call", "post_tool_call", "on_skill_lifecycle", "on_session_end")
KEEP = ("session_id", "turn_id", "api_request_id", "api_call_count", "tool_call_id", "tool_name", "status",
        "duration_ms", "api_duration", "finish_reason", "error_type", "error_message", "status_code",
        "skill_name", "action", "telemetry_schema_version")

_outbox: "queue.Queue[dict]" = queue.Queue(maxsize=1000)


def _sender(url: str, key: str) -> None:
    while True:
        event = _outbox.get()
        try:
            req = urllib.request.Request(url, data=json.dumps(event).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:
            pass
        finally:
            _outbox.task_done()


def _drain(seconds: float = 3.0) -> None:
    """At interpreter exit, give the sender a moment to deliver what is queued. The sender is a daemon
    thread, so without this the LAST events of a run — the final tool result, on_session_end — were
    dropped whenever Hermes exited before they were posted."""
    deadline = time.monotonic() + seconds
    while _outbox.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)


def _hook(name: str):
    def callback(**kwargs):
        try:
            event = {"event": name, **{k: kwargs[k] for k in KEEP if kwargs.get(k) is not None}}
            if name == "post_api_request" and isinstance(kwargs.get("usage"), dict):
                event["usage"] = kwargs["usage"]
            _outbox.put_nowait(event)
        except Exception:
            pass
        return None
    return callback


def register(ctx) -> None:
    run_id, base, key = os.environ.get("BOS_RUN_ID"), os.environ.get("BOS_RUNNER_URL"), os.environ.get("BOS_PROXY_KEY")
    if not (run_id and base and key):
        return                      # not a Business OS run: stay silent
    threading.Thread(target=_sender, args=(f"{base}/runs/{run_id}/events", key), daemon=True).start()
    atexit.register(_drain)
    for name in HOOKS:
        try:
            ctx.register_hook(name, _hook(name))
        except Exception:
            pass
