"""The system_one harness (db/145; docs/build-specs/system-one-harness.md): an agent whose judgement is
JEV's — TypeSafe's System One model — running a playbook shipped with the kernel instead of a chat loop.

One class, one renderer (the playbook config is the agent's runtime_config: mode and thresholds), one entry
in registry.py — the interface is the one every harness implements. What to run comes from the run's
instructions: a duty says `playbook: health` (or several, comma-separated).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from .. import config
from ..harness import Harness, PreparedRun, RunContext, RunOutcome
from . import playbooks

VERSION = "system_one/1.0"


def playbooks_named(instructions: str) -> list[str]:
    text = (instructions or "").strip()
    try:
        data = json.loads(text)
        names = data.get("playbooks") or [data.get("playbook")] if isinstance(data, dict) else []
    except ValueError:
        m = re.search(r"playbooks?\s*:\s*([a-z_,\s]+)", text, re.I)
        names = [n.strip() for n in m.group(1).split(",")] if m else []
    return [n for n in names if n]


class SystemOneHarness(Harness):
    key = "system_one"

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def version(self) -> str:
        return VERSION

    def prepare(self, context: RunContext) -> PreparedRun:
        profile_dir = config.AGENTS_DIR / str(context.agent["member_id"])
        rc = context.agent.get("runtime_config") or {}
        digest = hashlib.sha256(json.dumps({"v": VERSION, "rc": rc}, sort_keys=True, default=str).encode()).hexdigest()
        prepared = PreparedRun(context=context, profile_dir=profile_dir, profile_hash=digest)
        names = playbooks_named(context.instructions)
        unknown = [n for n in names if n not in playbooks.PLAYBOOKS]
        prepared.detail = {"playbooks": [n for n in names if n in playbooks.PLAYBOOKS], "unknown": unknown}
        if unknown:
            prepared.warnings.append(f"Unknown playbook(s): {', '.join(unknown)}. Known: {', '.join(playbooks.PLAYBOOKS)}.")
        return prepared

    async def execute(self, prepared: PreparedRun) -> RunOutcome:
        ctx0 = prepared.context
        names = prepared.detail.get("playbooks") or []
        if not names:
            return RunOutcome("failed", error="A system_one run names its playbook(s): e.g. 'playbook: health'. "
                                              f"Known: {', '.join(playbooks.PLAYBOOKS)}.")
        results = []
        self._tasks[ctx0.run_id] = asyncio.current_task()
        try:
            for name in names:
                ctx = playbooks.Ctx(ctx0.run_id, ctx0.agent, ctx0.run_token, ctx0.proxy_key)
                results.append(await asyncio.wait_for(playbooks.PLAYBOOKS[name](ctx), ctx0.timeout_seconds))
        except asyncio.TimeoutError:
            return RunOutcome("failed", result="\n".join(results), error="The playbook ran past the run's time limit.")
        finally:
            self._tasks.pop(ctx0.run_id, None)
        return RunOutcome("succeeded", result="\n".join(results))

    async def cancel(self, run_id: int) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
