"""A MemoryProvider that remembers nothing and logs every call Hermes makes to it.

It answers the questions the real provider (maludb-hermes) depends on: is a pip entry-point
provider loaded by name, which lifecycle methods fire in a one-shot run, what does initialize()
receive, does prefetch text and the system-prompt block actually reach the model, and do the
provider's own tools survive when the built-in memory stores are switched off.
"""
from __future__ import annotations

import json

from agent.memory_provider import MemoryProvider

from . import log

RECALL_MARKER = "BOS-RECALLED-FACT-7731"
CORE_MARKER = "BOS-CORE-MEMORY-4402"


class ConformanceMemoryProvider(MemoryProvider):
    pre_compress_checkpoint_api_version = 2

    @property
    def name(self) -> str:
        return "bos-conformance-memory"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        log("memory", "initialize", session_id=session_id,
            kwargs={k: (v if isinstance(v, (str, int, float, bool, type(None))) else type(v).__name__)
                    for k, v in kwargs.items()})

    def system_prompt_block(self) -> str:
        log("memory", "system_prompt_block")
        return f"## Core memory\n{CORE_MARKER}"

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        log("memory", "prefetch", query=query[:200], session_id=session_id)
        return f"Recalled: {RECALL_MARKER}"

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        log("memory", "queue_prefetch", query=query[:200])

    def sync_turn(self, user, assistant, *, session_id: str = "", messages=None, **kwargs) -> None:
        log("memory", "sync_turn", user=str(user)[:120], assistant=str(assistant)[:120],
            n_messages=len(messages or []))

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        log("memory", "on_turn_start", turn_number=turn_number)

    def on_session_end(self, messages) -> None:
        log("memory", "on_session_end", n_messages=len(messages or []))

    def on_pre_compress(self, messages, *, require_checkpoint: bool = False) -> str:
        log("memory", "on_pre_compress", n_messages=len(messages or []), require_checkpoint=require_checkpoint)
        return "checkpoint: conformance"

    def on_memory_write(self, action, target, content, metadata=None) -> None:
        log("memory", "on_memory_write", action=action, target=target)

    def shutdown(self) -> None:
        log("memory", "shutdown")

    def get_tool_schemas(self):
        log("memory", "get_tool_schemas")
        return [{
            "name": "bos_recall",
            "description": "Recall shared organisational memory (conformance stub).",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                           "required": ["query"]},
        }]

    def handle_tool_call(self, tool_name: str, args, **kwargs) -> str:
        log("memory", "handle_tool_call", tool_name=tool_name, args=args)
        return json.dumps({"ok": True, "recalled": RECALL_MARKER})

    def get_config_schema(self):
        return []

    def save_config(self, values, hermes_home: str) -> None:
        return None


def register(ctx) -> None:
    log("memory", "register")
    ctx.register_memory_provider(ConformanceMemoryProvider())
