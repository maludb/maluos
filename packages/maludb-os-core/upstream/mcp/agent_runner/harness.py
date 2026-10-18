"""The one interface every harness implements (build plan, phase 5 step 1).

Job description in, MCP tools attached, telemetry out, budget metered — whatever runs underneath.
The runner owns the run's life (row, credentials, finalisation); a harness only prepares and
executes. Adding a harness is one class here plus one value in model_registry.harness.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunContext:
    run_id: int
    request_id: str
    agent: dict                 # store.load_agent(): member, profile, active config version, model, endpoints
    instructions: str
    trigger: str
    run_token: str              # per-run; process environment only, never on disk
    proxy_key: str              # per-run; the run's identity at the ledger proxy
    timeout_seconds: int
    memory: dict = field(default_factory=dict)   # {'core': {...}, 'recalled': [...]} — never part of profile_hash


@dataclass
class PreparedRun:
    context: RunContext
    profile_dir: Path
    profile_hash: str
    skills: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass
class RunOutcome:
    status: str                 # succeeded | failed | awaiting_approval | cancelled
    result: str | None = None
    error: str | None = None
    usage_report: dict | None = None


class Harness(ABC):
    key: str                    # = model_registry.harness

    @abstractmethod
    def version(self) -> str: ...            # -> agent_runs.sdk_version

    @abstractmethod
    def prepare(self, context: RunContext) -> PreparedRun: ...

    @abstractmethod
    async def execute(self, prepared: PreparedRun) -> RunOutcome: ...

    @abstractmethod
    async def cancel(self, run_id: int) -> None: ...
