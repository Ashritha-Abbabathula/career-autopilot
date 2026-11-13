"""The study plan: load it into the database, and say what a day or a week looks like.

The plan itself (problem lists, lectures, exam dates) is the owner's private data and is
read from her private folder. This file only knows the shape:

plan     = {"dsa": [{"id", "title"}], "youtube": [{"title", "links"}],
            "gate_days": [{"minutes", "items": [{"subject", "title", "video_min"}]}]}
settings = {"start", "end", "gate_start", "progress": {"dsa_done", "youtube_done", "gate_done"},
            "dsa_per_day_before_gate", "dsa_per_day_after_gate",
            "exams": {"YYYY-MM-DD": "name"}, "prep": {"YYYY-MM-DD": "what"},
            "items": [{"date", "kind", "title"}]}
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import approvals, db, deadlines

MINUTES = {"dsa": 30, "youtube": 120, "gate": 60}
ORDER = {"college": 0, "dsa": 1, "gate": 2, "youtube": 3, "touch": 4, "ok": 5, "info": 6}
LABEL = {"college": "College", "dsa": "LeetCode", "gate": "GATE", "youtube": "YouTube",
         "touch": "Only you can do", "ok": "Needs your yes", "info": "Good to know"}
EXAM_WORDS = ("fat", "exam", "test")


def _days(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def _add_task(conn, title, kind, day: date, minutes=0, movable=1, source="plan"):
    conn.execute(
        "INSERT INTO tasks (title, kind, planned_date, minutes, movable, source, created_at) VALUES (?,?,?,?,?,?,?)",
        (title, kind, day.isoformat(), minutes, movable, source, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def import_plan(conn, plan: dict, settings: dict, force: bool = False) -> dict:
    """Lay the plan onto dates. Refuses to run twice unless force=True, which rebuilds
    only what is still to do and keeps everything already done."""
    if db.get_setting(conn, "plan_imported") == "1" and not force:
        raise ValueError("the plan is already imported; use force=True to rebuild what is left")
    done = {k: conn.execute("SELECT COUNT(*) FROM tasks WHERE source='plan' AND kind=? AND status='done'", (k,)).fetchone()[0]
            for k in ("dsa", "youtube")}
    gate_days_done = conn.execute(
        "SELECT COUNT(DISTINCT planned_date) FROM tasks WHERE source='plan' AND kind='gate' AND status='done'").fetchone()[0]
    conn.execute("DELETE FROM tasks WHERE source IN ('plan','plan_item') AND status = 'todo'")
    conn.execute("DELETE FROM events WHERE source = 'plan'")

    start, end = date.fromisoformat(settings["start"]), date.fromisoformat(settings["end"])
    gate_start = date.fromisoformat(settings.get("gate_start", settings["start"]))
    progress = settings.get("progress", {})
    counts = {"dsa": 0, "youtube": 0, "gate": 0, "exams": 0, "items": 0}

    for day, name in settings.get("exams", {}).items():
        conn.execute("INSERT INTO events (title, date, fixed, source) VALUES (?,?,1,'plan')", (name, day))
        counts["exams"] += 1
    for day, what in settings.get("prep", {}).items():
        d = date.fromisoformat(day)
        if start <= d <= end:
            _add_task(conn, what, "college", d, movable=0)

    dsa = plan.get("dsa", [])[progress.get("dsa_done", 0) + done["dsa"]:]
    before, after = settings.get("dsa_per_day_before_gate", 1), settings.get("dsa_per_day_after_gate", 3)
    i = 0
    for d in _days(start, end):
        for _ in range(before if d < gate_start else after):
            if i >= len(dsa):
                break
            p = dsa[i]
            i += 1
            _add_task(conn, f"LeetCode {p['id']}: {p['title']}", "dsa", d, MINUTES["dsa"])
            counts["dsa"] += 1

    yts = plan.get("youtube", [])[progress.get("youtube_done", 0) + done["youtube"]:]
    for d, y in zip(_days(max(gate_start, start), end), yts):
        _add_task(conn, y["title"], "youtube", d, MINUTES["youtube"])
        counts["youtube"] += 1

    gdays = plan.get("gate_days", [])[progress.get("gate_done", 0) + gate_days_done:]
    for d, g in zip(_days(max(gate_start, start), end), gdays):
        for it in g.get("items", []):
            _add_task(conn, f"GATE {it['subject']}: {it['title']}", "gate", d, it.get("video_min") or MINUTES["gate"])
            counts["gate"] += 1

    for it in settings.get("items", []):
        d = date.fromisoformat(it["date"])
        if start <= d <= end:
            _add_task(conn, it["title"], it.get("kind", "info"), d, movable=0, source="plan_item")
            counts["items"] += 1

    conn.commit()
    db.set_setting(conn, "plan_imported", "1")
    return counts


def import_from_files(conn, plan_path, settings_path, force: bool = False) -> dict:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    return import_plan(conn, plan, settings, force=force)


# ---- reading the plan ----------------------------------------------------
def tasks_on(conn, day: date, include_done: bool = True) -> List:
    sql = "SELECT * FROM tasks WHERE planned_date = ? AND status != 'moved'"
    if not include_done:
        sql += " AND status = 'todo'"
    rows = conn.execute(sql + " ORDER BY id", (day.isoformat(),)).fetchall()
    return sorted(rows, key=lambda r: (ORDER.get(r["kind"], 9), r["id"]))


def events_on(conn, day: date) -> List:
    return conn.execute("SELECT * FROM events WHERE date = ? ORDER BY start_time, id", (day.isoformat(),)).fetchall()


def is_exam(title: str) -> bool:
    words = title.lower().replace(",", " ").split()
    return any(w in EXAM_WORDS for w in words)


def study_minutes(conn, day: date) -> int:
    return sum(r["minutes"] for r in tasks_on(conn, day) if r["status"] == "todo")


def _fmt_minutes(m: int) -> str:
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _mark(row) -> str:
    return {"done": "[x] ", "skipped": "[-] "}.get(row["status"], "[ ] ")


def day_text(conn, day: date, today: Optional[date] = None) -> str:
    today = today or day
    head = "Today" if day == today else "Tomorrow" if day == today + timedelta(days=1) else day.strftime("%a")
    lines = [f"{head}, {day.strftime('%d %b')}"]
    events = events_on(conn, day)
    for e in events:
        lines.append(f"EXAM: {e['title']}" if is_exam(e["title"]) else f"Fixed: {e['title']}")
    tasks = tasks_on(conn, day)
    if not tasks and not events:
        lines.append("Nothing planned. A free day.")
        return "\n".join(lines)
    kind = None
    for t in tasks:
        if t["kind"] != kind:
            kind = t["kind"]
            lines.append(LABEL.get(kind, kind.title()) + ":")
        lines.append(f"{_mark(t)}{t['title']}")
    minutes = study_minutes(conn, day)
    if minutes:
        lines.append(f"Study time left: {_fmt_minutes(minutes)}")
    return "\n".join(lines)


def morning_card(conn, today: date) -> str:
    lines = ["Good morning."]
    exams = [e for e in events_on(conn, today) if is_exam(e["title"])]
    if exams:
        lines.append(f"Exam day: {exams[0]['title']}. That is the only thing that matters today. All the best.")
    lines.append(day_text(conn, today))
    due = [i for i in deadlines.upcoming(conn, today, days=3)]
    if due:
        lines.append("Due soon:")
        lines += [deadlines.label(i, today) for i in due[:5]]
    waiting = len(approvals.pending(conn))
    if waiting:
        lines.append(f"{waiting} thing{'s' if waiting != 1 else ''} waiting for your yes. Send 'inbox'.")
    return "\n".join(lines)


def week_text(conn, today: date, days: int = 7) -> str:
    lines = []
    for d in _days(today, today + timedelta(days=days - 1)):
        tasks = tasks_on(conn, d)
        events = events_on(conn, d)
        bits = [("EXAM " if is_exam(e["title"]) else "") + e["title"] for e in events]
        per_kind = {}
        for t in tasks:
            if t["status"] == "todo":
                per_kind[t["kind"]] = per_kind.get(t["kind"], 0) + 1
        for k in sorted(per_kind, key=lambda k: ORDER.get(k, 9)):
            if k == "college":
                bits += [t["title"] for t in tasks if t["kind"] == "college" and t["status"] == "todo"]
            else:
                bits.append(f"{per_kind[k]} {LABEL.get(k, k)}")
        minutes = study_minutes(conn, d)
        tail = f" ({_fmt_minutes(minutes)})" if minutes else ""
        lines.append(f"{d.strftime('%a %d %b')}: " + ("; ".join(bits) if bits else "free") + tail)
    return "\n".join(lines)
