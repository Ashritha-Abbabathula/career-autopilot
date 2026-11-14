"""Changing the plan by rule: done, skip, push to another day, and "I only have N hours".

Every change is written to plan_changes with the before and after state, so 'undo'
can put things back exactly. Fixed items (exam preparation) never move.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from . import planner, uistate

KIND_WORDS = {
    "leetcode": "dsa", "lc": "dsa", "dsa": "dsa", "problem": "dsa", "problems": "dsa",
    "gate": "gate", "youtube": "youtube", "yt": "youtube", "video": "youtube", "videos": "youtube",
    "college": "college",
}
STUDY_KINDS = ("dsa", "gate", "youtube")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_IN_DAYS = re.compile(r"^in\s+(\d+)\s+days?$")


class ReplanError(Exception):
    """A refused change. The message is safe to show to the owner."""


def parse_day(text: str, today: date) -> Optional[date]:
    t = (text or "").strip().lower().rstrip(".")
    if t in ("today", "tonight"):
        return today
    if t in ("tomorrow", "tmrw", "tmr"):
        return today + timedelta(days=1)
    if t == "day after tomorrow":
        return today + timedelta(days=2)
    if t in ("weekend", "the weekend"):
        t = "saturday"
    m = _IN_DAYS.match(t)
    if m:
        return today + timedelta(days=int(m.group(1)))
    if t.startswith("next "):
        t = t[5:]
    for i, name in enumerate(WEEKDAYS):
        if t == name or (len(t) >= 3 and name.startswith(t)):
            ahead = (i - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def find_tasks(conn, query: str, day: date) -> List:
    """Tasks still to do on `day` that the words point at: a kind word, 'all', a number, or part of a title."""
    q = (query or "").strip().lower()
    todo = planner.tasks_on(conn, day, include_done=False)
    if q in ("all", "everything", "all of it"):
        return todo
    if q in KIND_WORDS:
        return [t for t in todo if t["kind"] == KIND_WORDS[q]]
    words = q.split()
    if len(words) == 2 and words[0] in KIND_WORDS and words[1].isdigit():      # "leetcode 49"
        q = words[1]
    if q.isdigit():
        hits = [t for t in todo if re.search(rf"\b{q}\b", t["title"])]
        if hits:
            return hits
    return [t for t in todo if q and q in t["title"].lower()]


def _snapshot(conn, ids) -> list:
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT id, planned_date, status FROM tasks WHERE id IN ({marks}) ORDER BY id", list(ids)).fetchall()
    return [dict(r) for r in rows]


def _apply(conn, kind: str, ids, now: Optional[datetime], **change) -> int:
    before = _snapshot(conn, ids)
    sets = ", ".join(f"{k} = ?" for k in change)
    for i in ids:
        conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", list(change.values()) + [i])
    after = _snapshot(conn, ids)
    ts = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    cur = conn.execute("INSERT INTO plan_changes (ts, kind, before_json, after_json) VALUES (?,?,?,?)",
                       (ts, kind, json.dumps(before), json.dumps(after)))
    conn.commit()
    return cur.lastrowid


def _need(conn, query: str, day: date) -> List:
    rows = find_tasks(conn, query, day)
    if not rows:
        raise ReplanError(f"I could not find '{query}' in what is left for {day.strftime('%d %b')}. Send 'today' to see the list.")
    return rows


def _names(rows, limit: int = 4) -> str:
    names = [r["title"] for r in rows[:limit]]
    if len(rows) > limit:
        names.append(f"and {len(rows) - limit} more")
    return "; ".join(names)


def done(conn, query: str, today: date, now: Optional[datetime] = None) -> str:
    rows = _need(conn, query, today)
    _apply(conn, "done", [r["id"] for r in rows], now, status="done")
    uistate.mirror_tasks_to_state(conn, [r["id"] for r in rows])      # the calendar page shows it ticked too
    left = planner.study_minutes(conn, today)
    tail = f" Study time left today: {planner._fmt_minutes(left)}." if left else " That is everything for today."
    return f"Marked done: {_names(rows)}." + tail


def skip(conn, query: str, today: date, now: Optional[datetime] = None) -> str:
    rows = _need(conn, query, today)
    _apply(conn, "skip", [r["id"] for r in rows], now, status="skipped")
    return f"Skipped: {_names(rows)}. Say 'undo' to bring it back."


def push(conn, query: str, to_text: str, today: date, now: Optional[datetime] = None) -> str:
    target = parse_day(to_text, today)
    if target is None:
        raise ReplanError(f"I did not understand the day '{to_text}'. Try 'tomorrow', 'saturday' or a date like 2026-12-01.")
    if target <= today:
        raise ReplanError("I can only push things to a later day.")
    rows = _need(conn, query, today)
    fixed = [r for r in rows if not r["movable"]]
    movable = [r for r in rows if r["movable"]]
    if not movable:
        raise ReplanError(f"{_names(fixed)} is fixed and cannot move.")
    _apply(conn, "push", [r["id"] for r in movable], now, planned_date=target.isoformat())
    load = planner.study_minutes(conn, target)
    msg = f"Moved to {target.strftime('%a %d %b')}: {_names(movable)}. That day now has {planner._fmt_minutes(load)} of study."
    if fixed:
        msg += f" Left in place (fixed): {_names(fixed)}."
    return msg + " Say 'undo' to put it back."


def free_hours(conn, hours: float, today: date, now: Optional[datetime] = None) -> str:
    """Keep what fits in the hours she has, in priority order, and move the rest to tomorrow."""
    budget = int(hours * 60)
    todo = [t for t in planner.tasks_on(conn, today, include_done=False) if t["kind"] in STUDY_KINDS and t["movable"]]
    if not todo:
        return "There is no study left to fit in today."
    keep, move, used = [], [], 0
    for t in todo:
        if used + t["minutes"] <= budget:
            keep.append(t)
            used += t["minutes"]
        else:
            move.append(t)
    if not move:
        return f"Everything left fits: {planner._fmt_minutes(used)} of study for your {hours:g} hours."
    tomorrow = today + timedelta(days=1)
    _apply(conn, "free_hours", [t["id"] for t in move], now, planned_date=tomorrow.isoformat())
    lines = [f"For {hours:g} hours I kept {planner._fmt_minutes(used)}:" if keep else f"Nothing fits in {hours:g} hours, so today is clear."]
    lines += [f"- {t['title']}" for t in keep]
    lines.append(f"Moved to tomorrow: {_names(move)}.")
    lines.append(f"Tomorrow now has {planner._fmt_minutes(planner.study_minutes(conn, tomorrow))} of study. Say 'undo' to put it back.")
    return "\n".join(lines)


ROLLOVER_CAP_MINUTES = 360


def rollover(conn, today: date, now: Optional[datetime] = None) -> Optional[str]:
    """Move yesterday's unfinished study into today, up to a daily cap, never onto an exam day.
    Anything that does not fit stays on yesterday as missed. Logged, so 'undo' reverses it."""
    if any(planner.is_exam(e["title"]) for e in planner.events_on(conn, today)):
        return None
    yesterday = today - timedelta(days=1)
    left = [t for t in planner.tasks_on(conn, yesterday, include_done=False) if t["kind"] in STUDY_KINDS and t["movable"]]
    if not left:
        return None
    room = ROLLOVER_CAP_MINUTES - planner.study_minutes(conn, today)
    move = []
    for t in left:
        if t["minutes"] <= room:
            move.append(t)
            room -= t["minutes"]
    if not move:
        return None
    _apply(conn, "rollover", [t["id"] for t in move], now, planned_date=today.isoformat())
    return f"Moved {len(move)} unfinished item{'s' if len(move) != 1 else ''} from yesterday into today."


def last_change(conn):
    return conn.execute("SELECT * FROM plan_changes WHERE undone = 0 ORDER BY id DESC LIMIT 1").fetchone()


def undo_last(conn) -> Optional[str]:
    row = last_change(conn)
    if row is None:
        return None
    before = json.loads(row["before_json"])
    for item in before:
        conn.execute("UPDATE tasks SET planned_date = ?, status = ? WHERE id = ?",
                     (item["planned_date"], item["status"], item["id"]))
    conn.execute("UPDATE plan_changes SET undone = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    uistate.mirror_tasks_to_state(conn, [item["id"] for item in before])
    n = len(before)
    return f"Undone: put {n} item{'s' if n != 1 else ''} back as before."
