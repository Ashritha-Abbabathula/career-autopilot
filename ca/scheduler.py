"""What is due right now. Pure: give it the local time and what already ran today, get job names back.

A job fires once a day at or after its time, but only within a grace window, so a laptop that
wakes at 4 pm does not send the 7:30 morning card. Whether a job really runs is decided by the
runner (paused, quiet hours and the daily cap are enforced by the outbox, not here).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Job:
    name: str
    hour: int
    minute: int
    grace_minutes: int
    weekday: Optional[int] = None        # 0 = Monday; None = every day


JOBS = [
    Job("rollover", 5, 0, 600),          # runs before the morning card, and silently
    Job("history_sync", 5, 30, 600),     # reads your public LeetCode and GitHub history for the calendar
    Job("tracker_sync", 6, 30, 600),     # silently keeps the tracker CSV and the database in step
    Job("morning_card", 7, 30, 240),
    Job("digest", 9, 0, 180),
    Job("streak_nudge", 20, 0, 90),
    Job("checkin", 21, 0, 90),
    Job("streak_last_call", 22, 0, 45),
    Job("scorecard", 18, 0, 180, weekday=6),
    Job("mentor", 19, 0, 120, weekday=6),
    Job("calendar_refresh", 6, 0, 480),
    Job("linkedin_draft", 9, 0, 300),
    Job("outreach_queue", 10, 30, 300, weekday=1),
]


def due_jobs(local_now: datetime, done_dates: Dict[str, str], jobs: Optional[List[Job]] = None) -> List[str]:
    """Names of jobs due now. done_dates maps job name to the YYYY-MM-DD it last ran."""
    today = local_now.date().isoformat()
    minutes_now = local_now.hour * 60 + local_now.minute
    due = []
    for job in jobs or JOBS:
        if job.weekday is not None and local_now.weekday() != job.weekday:
            continue
        start = job.hour * 60 + job.minute
        if start <= minutes_now < start + job.grace_minutes and done_dates.get(job.name) != today:
            due.append(job.name)
    return due


def load_done(conn, db_module) -> Dict[str, str]:
    return {j.name: db_module.get_setting(conn, f"last_{j.name}_date", "") or "" for j in JOBS}


def mark_done(conn, db_module, name: str, local_now: datetime) -> None:
    db_module.set_setting(conn, f"last_{name}_date", local_now.date().isoformat())
