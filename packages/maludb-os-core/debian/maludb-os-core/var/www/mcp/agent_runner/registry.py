"""model_registry.harness -> the class that runs it."""
from __future__ import annotations

from .harness import Harness
from .claude_harness import ClaudeAgentHarness
from .hermes_harness import HermesHarness
from .system_one.harness import SystemOneHarness

_HARNESSES: dict[str, Harness] = {}


def _load() -> None:
    if not _HARNESSES:
        for cls in (HermesHarness, ClaudeAgentHarness, SystemOneHarness):
            _HARNESSES[cls.key] = cls()


def built_keys() -> list[str]:
    """Which model_registry.harness values actually have a harness. The hire and activation
    handlers refuse the others by name rather than letting a run discover it at dispatch."""
    _load()
    return sorted(_HARNESSES)


def get(key: str) -> Harness:
    _load()
    if key not in _HARNESSES:
        raise LookupError(f"No harness is built for '{key}' yet. Built: {', '.join(sorted(_HARNESSES)) or 'none'}.")
    return _HARNESSES[key]
