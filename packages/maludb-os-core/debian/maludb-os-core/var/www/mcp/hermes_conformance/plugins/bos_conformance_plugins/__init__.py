"""Logging-only Hermes plugins for the conformance suite. They change nothing; they write what
Hermes called, and when, to the JSONL file named by KIT_PLUGIN_LOG."""
from __future__ import annotations

import json
import os
import threading
import time

_lock = threading.Lock()


def log(kind: str, event: str, **fields) -> None:
    path = os.environ.get("KIT_PLUGIN_LOG")
    if not path:
        return
    row = {"t": time.time(), "kind": kind, "event": event, "pid": os.getpid(), **fields}
    with _lock, open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
