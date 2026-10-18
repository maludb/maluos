"""What the Sysadmin reads (db/145): new log lines since each source's cursor, the kernel's guardrail events,
and the health probes. Everything a collector returns is already REDACTED (redact.py) — the raw lines
never leave this module. The runner user reads the logs through the adm and systemd-journal groups;
agents run as another user and never do.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .. import store
from .redact import redact

JOURNAL_UNITS_GLOBS = ["maludb-os-*", "hr-*", "maludb-api", "apache2", "postgresql*"]
APACHE_ERROR_LOGS = "/var/log/apache2"
POSTGRES_LOG = "/var/log/postgresql/postgresql-17-main.log"
PG_LEVELS = re.compile(r"\b(ERROR|FATAL|PANIC|WARNING):")
APACHE_LEVELS = re.compile(r"\[(?:[a-z_]+:)?(error|crit|alert|emerg|warn)\]|PHP (Fatal|Warning|Parse)")
MAX_LINES_PER_SOURCE = 500
FIRST_LOOK = timedelta(hours=1)          # a source never read before starts an hour back, not at the beginning of time


@dataclass
class Line:
    source: str
    text: str                     # redacted
    at: datetime


async def _cursor(source: str) -> str | None:
    p = await store.pool()
    async with p.acquire() as con:
        return await con.fetchval("SELECT cursor FROM system_collector_state WHERE source = $1", source)


async def _save_cursor(source: str, cursor: str | None, error: str | None = None) -> None:
    p = await store.pool()
    async with p.acquire() as con:
        await con.execute("""
            INSERT INTO system_collector_state (source, cursor, last_run_at, last_error) VALUES ($1, $2, now(), $3)
            ON CONFLICT (source) DO UPDATE SET cursor = COALESCE(EXCLUDED.cursor, system_collector_state.cursor),
                   last_run_at = now(), last_error = EXCLUDED.last_error""", source, cursor, error)


async def _run(*args: str, timeout: float = 20.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, ""
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def journal() -> list[Line]:
    """Warnings and worse from the platform's units, since the stored journal cursor."""
    source = "journal"
    cursor = await _cursor(source)
    args = ["journalctl", "--no-pager", "-o", "json", "-p", "warning", "--show-cursor", "-n", str(MAX_LINES_PER_SOURCE)]
    for glob in JOURNAL_UNITS_GLOBS:
        args += ["-u", glob]
    args += ["--after-cursor", cursor] if cursor else ["--since", (datetime.now() - FIRST_LOOK).strftime("%Y-%m-%d %H:%M:%S")]
    code, out = await _run(*args)
    lines, new_cursor = [], None
    for raw in out.splitlines():
        if raw.startswith("-- cursor:"):
            new_cursor = raw.split(":", 1)[1].strip()
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        unit = (entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "journal").replace(".service", "")
        message = entry.get("MESSAGE")
        if isinstance(message, list):
            message = bytes(message).decode("utf-8", "replace")
        at = datetime.fromtimestamp(int(entry.get("__REALTIME_TIMESTAMP", "0")) / 1e6, timezone.utc)
        lines.append(Line(f"journal:{unit}", redact(str(message or "")), at))
    await _save_cursor(source, new_cursor, None if code == 0 else f"journalctl exited {code}")
    return lines


async def _tail_file(source: str, path: str, keep: re.Pattern) -> list[Line]:
    """New lines of a file since the stored offset (inode-aware: a rotated file starts again at 0)."""
    try:
        st = os.stat(path)
    except OSError as exc:
        await _save_cursor(source, None, str(exc))
        return []
    saved = await _cursor(source)
    inode, offset = (saved.split(":", 1) if saved and ":" in saved else (None, None))
    if inode != str(st.st_ino) or offset is None:
        offset = max(0, st.st_size - 64_000) if saved is None else 0        # first look: the recent tail only
    offset = int(offset)
    if offset > st.st_size:
        offset = 0
    lines: list[Line] = []
    now = datetime.now(timezone.utc)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(2_000_000)
        end = offset + len(chunk)
    for raw in chunk.decode("utf-8", "replace").splitlines()[-MAX_LINES_PER_SOURCE:]:
        if keep.search(raw):
            lines.append(Line(source, redact(raw), now))
    await _save_cursor(source, f"{st.st_ino}:{end}")
    return lines


async def apache() -> list[Line]:
    lines: list[Line] = []
    for name in sorted(os.listdir(APACHE_ERROR_LOGS)):
        if name.endswith("error.log"):
            lines += await _tail_file(f"apache:{name}", os.path.join(APACHE_ERROR_LOGS, name), APACHE_LEVELS)
    return lines


async def postgresql() -> list[Line]:
    return await _tail_file("postgresql", POSTGRES_LOG, PG_LEVELS)


async def guardrails() -> list[Line]:
    """The kernel's own guardrail events since the last look."""
    source = "guardrails"
    saved = await _cursor(source)
    since = datetime.fromisoformat(saved) if saved else datetime.now(timezone.utc) - FIRST_LOOK
    now = datetime.now(timezone.utc)
    p = await store.pool()
    async with p.acquire() as con:
        rows = await con.fetch("SELECT kind, subject_id, occurred_at, text FROM system_guardrail_events($1)", since)
    await _save_cursor(source, now.isoformat())
    return [Line(f"guardrail:{r['kind']}", redact(r["text"] or ""), r["occurred_at"]) for r in rows]


# ---- health probes (deterministic) -----------------------------------------------------------------------

@dataclass
class Probe:
    probe: str
    status: str                   # ok | warning | failed
    detail: str
    measured: dict


async def probes() -> list[Probe]:
    out: list[Probe] = []
    code, listing = await _run("systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain",
                               *[g + ".service" if not g.endswith("*") else g for g in JOURNAL_UNITS_GLOBS])
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 4 or not parts[0].endswith(".service"):
            continue
        unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        if load != "loaded":
            continue
        if active == "inactive" and sub == "dead" and ("ingest" in unit or "sync" in unit):
            continue                                          # a oneshot driven by a timer rests between runs
        status = "ok" if active == "active" else ("failed" if active == "failed" else "warning")
        out.append(Probe(f"service:{unit.removesuffix('.service')}", status, f"{unit} is {active} ({sub}).", {"active": active, "sub": sub}))
    usage = shutil.disk_usage("/")
    pct = round(100 * usage.used / usage.total, 1)
    out.append(Probe("disk:/", "failed" if pct >= 95 else "warning" if pct >= 85 else "ok",
                     f"The root disk is {pct}% full ({usage.free // 2**30} GB free).", {"used_pct": pct, "free_gb": usage.free // 2**30}))
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0])
    avail = round(100 * mem.get("MemAvailable", 0) / max(1, mem.get("MemTotal", 1)), 1)
    out.append(Probe("memory", "failed" if avail < 5 else "warning" if avail < 12 else "ok",
                     f"{avail}% of memory is available ({mem.get('MemAvailable', 0) // 1024} MB).", {"available_pct": avail}))
    swap_total = mem.get("SwapTotal", 0)
    if swap_total:
        swap_used = round(100 * (swap_total - mem.get("SwapFree", 0)) / swap_total, 1)
        out.append(Probe("swap", "warning" if swap_used >= 60 else "ok", f"{swap_used}% of swap is in use.", {"used_pct": swap_used}))
    p = await store.pool()
    async with p.acquire() as con:
        backups = await con.fetch("SELECT * FROM system_backup_status()")
        apps = await con.fetch("SELECT * FROM system_application_probes()")
    if not backups:
        out.append(Probe("backup", "warning", "No backup has ever been recorded.", {}))
    for b in backups:
        age = (datetime.now(timezone.utc) - b["last_ok"]).days if b["last_ok"] else None
        status = "failed" if age is None else "warning" if age > 2 else "ok"
        out.append(Probe(f"backup:{b['kind']}", status,
                         f"The last good {b['kind']} backup was {age} day(s) ago." if age is not None else f"No {b['kind']} backup has succeeded.",
                         {"age_days": age, "last_status": b["last_status"]}))
    async with httpx.AsyncClient(timeout=5.0) as client:
        for a in apps:
            if a["version"]:
                out.append(Probe(f"version:{a['app_key']}", "ok", f"{a['name']} runs version {a['version']}.", {"version": a["version"]}))
            if not a["health_url"]:
                continue
            try:
                r = await client.get(a["health_url"])
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                ok = r.status_code < 300 and body.get("ok", True) is not False
                out.append(Probe(f"app:{a['app_key']}", "ok" if ok else "failed",
                                 f"{a['name']} answers {r.status_code}{'' if ok else ' — not healthy'}.", {"status": r.status_code}))
            except httpx.HTTPError as exc:
                out.append(Probe(f"app:{a['app_key']}", "failed", f"{a['name']} did not answer: {type(exc).__name__}.", {}))
    return out
