"""The weekly mentor note: a friendly, honest nudge toward the fields that make a strong candidate.

Built from real numbers only (tasks done in the last 7 days, the scorecard gap, the tracker).
It gives one small next step, never a pile of work, and goes quiet during exam weeks.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from . import scorecard, tracker

EXAMS_END = date(2026, 11, 30)         # last FAT
NEW_FIELD = {                           # the one-new-field-a-month rule (MENTOR_MODE.md)
    (2026, 11): None,
    (2026, 12): ("Cloud and DevOps", "deploy one of your projects with Docker and GitHub Actions; a 2-hour starter is enough this month"),
    (2027, 1): ("Open source", "read the contribution guide of one project you use and pick a tiny issue to plan; no pressure before GATE"),
    (2027, 2): ("System design and SQL", "explain one simple design out loud in 5 minutes, and add one SQL project line"),
}
RESEARCH_STEP = "send your solar flare study to one solar-ML professor for feedback"
NETWORK_STEP = "message one senior or mentor with a specific question; keep it to two sentences"


def done_last_week(conn, today: date) -> dict:
    since = (today - timedelta(days=6)).isoformat()
    rows = conn.execute("SELECT kind, COUNT(*) n FROM tasks WHERE status = 'done' AND planned_date >= ? AND planned_date <= ? GROUP BY kind",
                        (since, today.isoformat())).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def weekly_note(conn, today: date, lc_total: Optional[int], outreach_sent: Optional[int]) -> str:
    if today <= EXAMS_END:
        return ("Exam stretch, so this is short: one LeetCode problem a day is enough, everything else can wait. "
                "You've got this. I'll bring the bigger plan back on 1 Dec.")
    lines = []
    done = done_last_week(conn, today)
    total = sum(done.values())
    if total:
        parts = ", ".join(f"{n} {k}" for k, n in sorted(done.items()))
        lines.append(f"Nice work this week: {total} things done ({parts}).")
    else:
        lines.append("I can't see anything ticked off this week. Tell me 'done <task>' as you go and I'll keep count. A quiet week is fine; let's restart small.")
    gaps = []
    if lc_total is not None:
        gap = scorecard.expected_by(today, 200, 81) - lc_total
        if gap > 0:
            gaps.append(f"LeetCode is about {gap:.0f} problems behind the pace to 200")
    applied = sum(1 for r in tracker.list_apps(conn) if tracker.is_submitted(r)) + (outreach_sent or 0)
    pace = scorecard.expected_by(today, 40, 0)
    if applied < pace:
        gaps.append(f"applications and outreach are at {applied} against a pace of {pace:.0f}")
    if gaps:
        lines.append("Where you're thin: " + "; ".join(gaps) + ".")
    field = NEW_FIELD.get((today.year, today.month))
    steps = []
    if field:
        steps.append(f"this month's new field is {field[0]}: {field[1]}")
    steps.append(RESEARCH_STEP if today.isocalendar()[1] % 2 == 0 else NETWORK_STEP)
    lines.append("One small step each: " + "; and ".join(steps) + ".")
    lines.append("Keep about 20 minutes a month with a real person, like Ms. Suvidha or a senior. I can write the agenda.")
    return "\n".join(lines)
