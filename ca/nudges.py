"""Reminder texts for the daily jobs. Honest by design: it reports what it could read and what it could not."""
from __future__ import annotations

from datetime import date
from typing import Optional

from . import planner


def streak_hint(conn, today: date, lc, gh) -> Optional[str]:
    """A reminder when no LeetCode problem is done yet today, naming real work; None when all is well.
    It never suggests faking activity: the suggestion is today's planned problem."""
    if lc is not None and lc.solved_today > 0:
        return None
    plan = [t for t in planner.tasks_on(conn, today, include_done=False) if t["kind"] == "dsa"]
    if lc is None:
        parts = ["I could not check LeetCode just now, so check it yourself."]
    else:
        parts = [f"No LeetCode problem yet today (streak {lc.streak})."]
    parts.append(f"Today's one: {plan[0]['title']}." if plan else "Pick any problem you have been meaning to redo.")
    if gh is not None and gh.commits_today == 0:
        parts.append("Nothing pushed to GitHub today either. Push only work that is real.")
    return " ".join(parts)


def checkin(conn, today: date) -> str:
    todo = planner.tasks_on(conn, today, include_done=False)
    if not todo:
        return "Evening check-in: everything planned for today is done. Rest well."
    left = planner.study_minutes(conn, today)
    lines = [f"Evening check-in: {len(todo)} thing{'s' if len(todo) != 1 else ''} not done ({planner._fmt_minutes(left)})."]
    lines += [f"- {t['title']}" for t in todo[:6]]
    lines.append("Reply 'done <task>', 'push <task> to tomorrow', or 'skip <task>'.")
    return "\n".join(lines)
