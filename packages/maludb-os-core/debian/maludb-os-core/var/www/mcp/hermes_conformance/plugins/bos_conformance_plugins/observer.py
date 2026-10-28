"""Observer-hooks plugin that logs the keys (and the few scalar values we care about) of every
hook payload. It tells us which hooks fire in a one-shot run, what correlation ids they carry,
and whether the model-call hooks see the auxiliary calls the wire-level proxy sees."""
from __future__ import annotations

from . import log

HOOKS = (
    "on_session_start", "on_session_end", "on_session_finalize",
    "pre_llm_call", "post_llm_call",
    "pre_api_request", "post_api_request", "api_request_error",
    "pre_tool_call", "post_tool_call",
    "subagent_start", "subagent_stop",
    "on_skill_lifecycle",
)
SCALARS = ("telemetry_schema_version", "session_id", "task_id", "turn_id", "api_request_id",
           "api_call_count", "tool_call_id", "tool_name", "status", "model", "provider", "base_url",
           "api_mode", "platform", "finish_reason", "api_duration", "duration_ms")


def _make(hook: str):
    def callback(**kwargs):
        fields = {k: kwargs.get(k) for k in SCALARS if k in kwargs}
        if "usage" in kwargs:
            fields["usage"] = kwargs["usage"]
        for big in ("request", "response"):
            if big in kwargs:
                fields[f"{big}_type"] = type(kwargs[big]).__name__
                fields[f"{big}_chars"] = len(str(kwargs[big]))
        log("observer", hook, keys=sorted(kwargs.keys()), **fields)
        return None
    return callback


def register(ctx) -> None:
    log("observer", "register")
    for hook in HOOKS:
        try:
            ctx.register_hook(hook, _make(hook))
        except Exception as exc:  # a hook name this Hermes version does not know
            log("observer", "register_failed", hook=hook, error=str(exc))
