"""GitHub public activity, read only. Reminders only: the bot never makes commits to keep a streak."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class GitHubStats:
    pushes_today: int
    commits_today: int


def fetch_stats(http, user: str, now: Optional[datetime] = None) -> Optional[GitHubStats]:
    if not user:
        return None
    status, text = http.request("GET", f"https://api.github.com/users/{user}/events/public?per_page=100",
                                headers={"Accept": "application/vnd.github+json"}, timeout=20)
    if status != 200:
        return None
    try:
        events = json.loads(text)
        today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        pushes = commits = 0
        for e in events:
            if e.get("type") != "PushEvent":
                continue
            if datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")).date() != today:
                continue
            pushes += 1
            commits += len(e.get("payload", {}).get("commits", []))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return GitHubStats(pushes, commits)
