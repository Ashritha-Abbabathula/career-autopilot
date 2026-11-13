"""What is due soon: application deadlines, next actions and manual reminders, in one sorted list."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from . import tracker


@dataclass(frozen=True)
class Due:
    due: date
    text: str
    source: str            # application, next_action, reminder
    ref_id: int

    def days_left(self, today: date) -> int:
        return (self.due - today).days


def parse_date(value) -> Optional[date]:
    """Dates are YYYY-MM-DD. Anything else ('unknown', 'rolling', empty) is not a date."""
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def add_reminder(conn, due: date, text: str, source: str = "manual") -> int:
    cur = conn.execute("INSERT INTO reminders (due_date, text, source) VALUES (?,?,?)",
                       (due.isoformat(), text.strip(), source))
    conn.commit()
    return cur.lastrowid


def complete_reminder(conn, reminder_id: int) -> None:
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()


def upcoming(conn, today: date, days: int = 14) -> List[Due]:
    """Everything due up to `days` ahead, including overdue items, soonest first."""
    horizon = today + timedelta(days=days)
    items: List[Due] = []
    for r in tracker.list_apps(conn):
        if tracker.is_submitted(r) or r["decision"] == "SKIP":
            continue
        d = parse_date(r["deadline"])
        if d and d <= horizon and r["decision"] in ("APPLY", "APPLY LATER", "MAYBE"):
            items.append(Due(d, f"Deadline: {r['organisation']}, {r['role_or_programme']}", "application", r["id"]))
        n = parse_date(r["next_action_date"])
        if n and n <= horizon and r["next_action"]:
            items.append(Due(n, f"{r['organisation']}: {r['next_action']}", "next_action", r["id"]))
    for r in conn.execute("SELECT * FROM reminders WHERE done = 0").fetchall():
        d = parse_date(r["due_date"])
        if d and d <= horizon:
            items.append(Due(d, r["text"], "reminder", r["id"]))
    return sorted(items, key=lambda i: (i.due, i.source, i.ref_id))


def label(item: Due, today: date) -> str:
    n = item.days_left(today)
    if n < 0:
        when = f"OVERDUE by {-n} day{'s' if n != -1 else ''}"
    elif n == 0:
        when = "today"
    elif n == 1:
        when = "tomorrow"
    else:
        when = f"in {n} days ({item.due.strftime('%d %b')})"
    return f"{item.text} - {when}"


def text(conn, today: date, days: int = 14, limit: int = 8) -> str:
    items = upcoming(conn, today, days)
    if not items:
        return f"Nothing due in the next {days} days."
    lines = [label(i, today) for i in items[:limit]]
    if len(items) > limit:
        lines.append(f"...and {len(items) - limit} more")
    return "\n".join(lines)
