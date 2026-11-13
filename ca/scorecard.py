"""The Sunday scorecard: where she stands against her own targets for 13 Feb 2027.

Every number has a source she can check (LeetCode public profile, the tracker, the outreach
sheet). A number that cannot be read is shown as unknown, never estimated.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from . import tracker

START, END = date(2026, 11, 14), date(2027, 2, 13)
# (floor, target, stretch) from CANDIDATE_SPEC section 3
TARGETS = {
    "LeetCode solved": (170, 200, 230),
    "Applications and outreach sent": (25, 40, 60),
}
PACE_MESSAGE = {
    "LeetCode solved": "solve {n} more problems this week",
    "Applications and outreach sent": "send {n} more applications or outreach emails this week (after your yes)",
}


def expected_by(today: date, target: float, start_value: float = 0) -> float:
    """Straight-line pace from start_value on START to target on END."""
    total = (END - START).days
    done = min(max((today - START).days, 0), total)
    return start_value + (target - start_value) * done / total


def outreach_sent(private: Path) -> Optional[int]:
    path = private / "tracker" / "outreach_targets.csv"
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return sum(1 for r in csv.DictReader(fh) if (r.get("status") or "").lower() in ("sent", "emailed", "messaged"))


def _line(name: str, value: Optional[float], today: date, start_value: float = 0) -> tuple:
    floor, target, stretch = TARGETS[name]
    if value is None:
        return f"{name}: unknown (could not read it)", None
    pace = expected_by(today, target, start_value)
    gap = pace - value
    status = "on pace" if gap <= 0 else f"{gap:.0f} behind the pace to the target"
    return (f"{name}: {value:.0f} (floor {floor}, target {target}, stretch {stretch}); {status}", gap)


def build(conn, today: date, lc_total: Optional[int], outreach: Optional[int], lc_start: int = 81) -> str:
    applied = sum(1 for r in tracker.list_apps(conn) if tracker.is_submitted(r))
    sent = applied + (outreach or 0) if outreach is not None or applied else None
    lines = [f"Scorecard, {today.strftime('%d %b')} (targets are for 13 Feb 2027)"]
    moves = []
    for name, value, start in (("LeetCode solved", lc_total, lc_start), ("Applications and outreach sent", sent, 0)):
        text, gap = _line(name, value, today, start)
        lines.append(text)
        if gap is not None and gap > 0:
            per_week = max(1, round(gap / 2))
            moves.append(PACE_MESSAGE[name].format(n=per_week))
    waiting = conn.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]
    if waiting:
        moves.append(f"answer the {waiting} item{'s' if waiting != 1 else ''} in your inbox")
    if moves:
        lines.append("Next week: " + "; ".join(moves[:3]) + ".")
    else:
        lines.append("Next week: keep going. Nothing is behind.")
    lines.append("Not counted: replies, interviews, offers. They are outcomes, not your targets.")
    return "\n".join(lines)
