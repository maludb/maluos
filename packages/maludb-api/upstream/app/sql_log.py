"""
SQL tracing — per-request query log + persistent sql.log file.

Ports PHP's sql_log(), $GLOBALS['__sql_trace'], and the debug buffer from
config/response.php.  Uses contextvars for per-request isolation (replaces
PHP's $GLOBALS).
"""

from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from app import config


def _json_safe_param(p):  # noqa: ANN001, ANN202
    """A loggable stand-in for one query parameter.

    bytea params (document bytes, skill bundle files) are summarized — dumping
    raw bytes into json.dumps raises TypeError and megabyte blobs don't belong
    in sql.log or ?debug=1 responses anyway.
    """
    if isinstance(p, (bytes, bytearray, memoryview)):
        b = bytes(p)
        return f"<{len(b)} bytes sha256:{hashlib.sha256(b).hexdigest()[:12]}>"
    return p

# ---------------------------------------------------------------------------
# SqlTracer — collects queries for one request
# ---------------------------------------------------------------------------

class SqlTracer:
    """Per-request SQL trace collector.

    Mirrors PHP's $GLOBALS['__sql_trace'] array + the sql_log() function.
    Each request gets a fresh SqlTracer via the middleware.
    """

    def __init__(self) -> None:
        self.queries: list[dict] = []
        self.endpoint: str = ""
        self.method: str = ""
        self.uri: str = ""
        self.user_id: int | str = "anon"

    def log(self, sql: str, params: list | tuple, rows: int, dur_ms: float) -> None:
        """Record a query in the in-memory trace and append to the log file."""
        safe_params = [_json_safe_param(p) for p in params]
        self.queries.append({
            "sql": sql.strip(),
            "params": safe_params,
            "rows": rows,
            "dur_ms": round(dur_ms, 1),
        })
        _write_log_line(self, sql, safe_params, rows, dur_ms)


# ---------------------------------------------------------------------------
# Context variable — per-request tracer
# ---------------------------------------------------------------------------

_tracer_var: ContextVar[SqlTracer] = ContextVar("sql_tracer")


def get_tracer() -> SqlTracer:
    """Return the current request's SqlTracer (creates one if none set)."""
    try:
        return _tracer_var.get()
    except LookupError:
        t = SqlTracer()
        _tracer_var.set(t)
        return t


def set_tracer(tracer: SqlTracer) -> None:
    """Install a SqlTracer for the current context (called by middleware)."""
    _tracer_var.set(tracer)


# ---------------------------------------------------------------------------
# Persistent log file
# ---------------------------------------------------------------------------

def _iso_now_ms() -> str:
    """UTC ISO-8601 timestamp with milliseconds, e.g. 2024-03-15T10:23:45.123Z."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _write_log_line(tracer: SqlTracer, sql: str, params: list | tuple, rows: int, dur_ms: float) -> None:
    """Append one entry to LOG_DIR/sql.log, matching the PHP format."""
    log_path = Path(config.LOG_DIR) / "sql.log"
    # Indent continuation lines of the SQL
    formatted_sql = re.sub(r"\n", "\n       ", sql.strip())
    line = (
        f"{_iso_now_ms()}  {tracer.endpoint}  {tracer.method}  {tracer.uri}  user={tracer.user_id}\n"
        f"  SQL: {formatted_sql}\n"
        f"  PARAMS: {json.dumps([_json_safe_param(p) for p in params], default=str)}\n"
        f"  ROWS: {rows}\n"
        f"  DUR:  {dur_ms:.1f} ms\n\n"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line)
    except OSError:
        pass  # Swallow write errors — mirrors PHP's @file_put_contents
