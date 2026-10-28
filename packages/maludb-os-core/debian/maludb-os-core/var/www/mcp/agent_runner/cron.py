"""A small five-field cron evaluator: minute hour day-of-month month day-of-week, in a timezone.

Supports `*`, lists (1,15), ranges (1-5), steps (*/15, 10-50/10), month and weekday names, 7 for
Sunday, and cron's rule that when BOTH day fields are restricted a time matches if EITHER does.
Enough for agent_duties.schedule_cron, and no dependency to install on every office VM.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
DAYS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
FIELDS = ((0, 59, {}), (0, 23, {}), (1, 31, {}), (1, 12, MONTHS), (0, 7, DAYS))


class CronError(ValueError):
    pass


def _field(text: str, low: int, high: int, names: dict) -> tuple[set[int], bool]:
    """(the values, whether the field is unrestricted)"""
    values: set[int] = set()
    for part in text.lower().split(","):
        body, _, step_text = part.partition("/")
        step = int(step_text) if step_text.isdigit() and int(step_text) > 0 else (1 if not step_text else None)
        if step is None:
            raise CronError(f"bad step in {part!r}")
        if body == "*":
            start, end = low, high
        else:
            a, _, b = body.partition("-")
            try:
                start = names.get(a, None) if a in names else int(a)
                end = (names.get(b) if b in names else int(b)) if b else (high if step_text else start)
            except ValueError as exc:
                raise CronError(f"bad value in {part!r}") from exc
        if start is None or end is None or not (low <= start <= high and low <= end <= high and start <= end):
            raise CronError(f"{part!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return values, text.strip() == "*"


def parse(line: str):
    parts = line.split()
    if len(parts) != 5:
        raise CronError("a schedule has five fields: minute hour day-of-month month day-of-week")
    parsed = [_field(p, *spec) for p, spec in zip(parts, FIELDS)]
    weekdays = {0 if d == 7 else d for d in parsed[4][0]}
    return parsed[0][0], parsed[1][0], parsed[2][0], parsed[3][0], weekdays, parsed[2][1], parsed[4][1]


def next_after(line: str, after: datetime, timezone: str = "UTC") -> datetime:
    """The first matching minute strictly after `after` (aware), returned in UTC."""
    minutes, hours, doms, months, dows, any_dom, any_dow = parse(line)
    try:
        zone = ZoneInfo(timezone or "UTC")
    except Exception as exc:
        raise CronError(f"unknown timezone {timezone!r}") from exc
    t = after.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        cron_dow = (t.weekday() + 1) % 7                       # python: Mon=0; cron: Sun=0
        if any_dom and any_dow:
            day_ok = True
        elif any_dom:
            day_ok = cron_dow in dows
        elif any_dow:
            day_ok = t.day in doms
        else:
            day_ok = t.day in doms or cron_dow in dows         # both restricted: either matches
        if t.month in months and day_ok and t.hour in hours and t.minute in minutes:
            return t.astimezone(ZoneInfo("UTC"))
        if t.month not in months or not day_ok:
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
        elif t.hour not in hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
        else:
            t += timedelta(minutes=1)
    raise CronError("that schedule never fires")
