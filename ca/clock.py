"""Time source and quiet-hour logic.

Time is always passed in (never read from a global) so tests can control it.
India has no daylight saving, so Asia/Kolkata is a fixed UTC+05:30 offset. That also avoids needing
a timezone database, which Windows does not ship by default.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def tzinfo_for(name: str):
    """Return a tzinfo for a name. Supports UTC, Asia/Kolkata (and IST), and fixed 'UTC+HH:MM' offsets."""
    n = (name or "").strip()
    if n.upper() == "UTC":
        return timezone.utc
    if n in ("Asia/Kolkata", "Asia/Calcutta", "IST"):
        return IST
    if n.upper().startswith("UTC") and len(n) > 3:
        sign = 1 if n[3] == "+" else -1 if n[3] == "-" else 0
        if sign:
            try:
                hh, _, mm = n[4:].partition(":")
                return timezone(sign * timedelta(hours=int(hh), minutes=int(mm or 0)))
            except ValueError:
                pass
    try:  # works where a timezone database exists
        from zoneinfo import ZoneInfo
        return ZoneInfo(n)
    except Exception:
        raise ValueError("unknown timezone: use UTC, Asia/Kolkata or UTC+HH:MM") from None


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """A clock tests can move by hand."""

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("FakeClock needs an aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now = self._now + timedelta(**kwargs)

    def set(self, when: datetime) -> None:
        self._now = when


def local_now(clock: Clock, tz_name: str) -> datetime:
    return clock.now().astimezone(tzinfo_for(tz_name))


def is_quiet(local_dt: datetime, start_hour: int, end_hour: int) -> bool:
    """True from start_hour (inclusive) to end_hour (exclusive). Handles ranges that cross midnight."""
    h = local_dt.hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= h < end_hour
    return h >= start_hour or h < end_hour


def next_quiet_end(local_dt: datetime, start_hour: int, end_hour: int) -> datetime:
    """The next moment quiet hours end, at or after local_dt (returns local_dt if not quiet)."""
    if not is_quiet(local_dt, start_hour, end_hour):
        return local_dt
    end = local_dt.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end <= local_dt:
        end += timedelta(days=1)
    return end
