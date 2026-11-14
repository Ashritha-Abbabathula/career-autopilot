"""LeetCode public stats, read only. Used for reminders; the bot never submits anything (decision D10)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

URL = "https://leetcode.com/graphql"
QUERY = ("query($u:String!){matchedUser(username:$u){submitStats{acSubmissionNum{difficulty count}}"
         "userCalendar{streak submissionCalendar}}}")


@dataclass(frozen=True)
class LeetCodeStats:
    solved_total: int
    solved_today: int          # accepted-submission days in the calendar that fall on today's UTC date
    streak: int


def fetch_stats(http, user: str, now: Optional[datetime] = None) -> Optional[LeetCodeStats]:
    """Returns None when the site cannot be read, so callers say 'could not check' rather than guess."""
    if not user:
        return None
    status, text = http.request("POST", URL, headers={"Referer": "https://leetcode.com"},
                                body={"query": QUERY, "variables": {"u": user}}, timeout=20)
    if status != 200:
        return None
    try:
        data = json.loads(text)["data"]["matchedUser"]
        total = next(int(x["count"]) for x in data["submitStats"]["acSubmissionNum"] if x["difficulty"] == "All")
        calendar = json.loads(data["userCalendar"]["submissionCalendar"] or "{}")
        streak = int(data["userCalendar"].get("streak") or 0)
    except (ValueError, KeyError, TypeError, StopIteration):
        return None
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    solved_today = sum(int(n) for ts, n in calendar.items()
                       if datetime.fromtimestamp(int(ts), timezone.utc).date() == today)
    return LeetCodeStats(total, solved_today, streak)


def fetch_history(http, user: str):
    """Days with LeetCode activity: {YYYY-MM-DD: submissions}. The site's own calendar counts submissions,
    not distinct problems, so the page says 'submissions'. Returns None if it cannot be read."""
    if not user:
        return None
    status, text = http.request("POST", URL, headers={"Referer": "https://leetcode.com"},
                                body={"query": QUERY, "variables": {"u": user}}, timeout=20)
    if status != 200:
        return None
    try:
        data = json.loads(text)["data"]["matchedUser"]
        calendar = json.loads(data["userCalendar"]["submissionCalendar"] or "{}")
        days = {}
        for ts, n in calendar.items():
            day = datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
            days[day] = days.get(day, 0) + int(n)
        return days
    except (ValueError, KeyError, TypeError):
        return None
