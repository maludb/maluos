"""What every business_*.py tool module shares: the read-only annotation, the strict input base,
and the two date helpers. Lived in business_contacts.py until the kernel cut of 2026-09-22 took
Contacts away; nothing here is about any one module."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

RO = {"readOnlyHint": True, "openWorldHint": False}


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# Period handling: the same vocabulary every business tool accepts. (The kernel cut, 55d2163, moved
# _period_bounds() here and left this table behind in the deleted Contacts module — every tool given a
# `period` raised NameError until 2026-09-27.)
_PERIODS = {
    "today": ("current_date", "current_date + 1"),
    "this_week": ("date_trunc('week', current_date)", "date_trunc('week', current_date) + interval '1 week'"),
    "last_week": ("date_trunc('week', current_date) - interval '1 week'", "date_trunc('week', current_date)"),
    "this_month": ("date_trunc('month', current_date)", "date_trunc('month', current_date) + interval '1 month'"),
    "last_month": ("date_trunc('month', current_date) - interval '1 month'", "date_trunc('month', current_date)"),
    "this_quarter": ("date_trunc('quarter', current_date)", "date_trunc('quarter', current_date) + interval '3 months'"),
    "last_quarter": ("date_trunc('quarter', current_date) - interval '3 months'", "date_trunc('quarter', current_date)"),
    "ytd": ("date_trunc('year', current_date)", "current_date + 1"),
    "last_12_months": ("current_date - interval '12 months'", "current_date + 1"),
}


def _period_bounds(period: str | None, date_from: str | None, date_to: str | None) -> tuple[str, str] | None:
    """SQL expressions for a period name, or explicit dates. None means "no date filter"."""
    if date_from or date_to:
        lo = f"'{date_from}'::date" if date_from else "'-infinity'::timestamptz"
        hi = f"('{date_to}'::date + 1)" if date_to else "'infinity'::timestamptz"
        return lo, hi
    if period:
        return _PERIODS.get(period) or _PERIODS["this_month"]
    return None


def _iso_date(value: str | None) -> str | None:
    """Accept only YYYY-MM-DD, so a date can never carry SQL into an interpolated bound."""
    if value is None:
        return None
    value = value.strip()
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("Dates are ISO (YYYY-MM-DD).")
    if not (value[:4] + value[5:7] + value[8:]).isdigit():
        raise ValueError("Dates are ISO (YYYY-MM-DD).")
    return value
