"""The daily digest, built from files the scout writes into the owner's private folder.

Reads, all optional (a missing file just means that section is left out):
  tracker/opportunities.csv     new and open opportunities, with deadlines
  tracker/DAILY_DIGEST.md       the scout's own written summary (first lines only)
  tracker/inbox_summary.json    mail the scout summarised: [{"date","from","subject","kind","summary"}]
The bot never reads her mailbox itself; it only reads what those files say.
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List

from . import deadlines

MAIL_KINDS_FIRST = ("interview", "reply", "deadline", "action")


def _opportunities(private: Path) -> List[dict]:
    path = private / "tracker" / "opportunities.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def open_opportunities(private: Path, today: date, days: int = 30, limit: int = 5) -> List[dict]:
    """APPLY and WATCH opportunities whose deadline is unknown or within `days`, soonest first."""
    rows = []
    for r in _opportunities(private):
        if (r.get("decision") or "").upper() not in ("APPLY", "WATCH"):
            continue
        if (r.get("status") or "").lower() in ("applied", "closed", "rejected", "skipped"):
            continue
        raw_deadline = (r.get("deadline") or "").lower()
        if "closed" in raw_deadline or "expired" in raw_deadline:
            continue
        d = deadlines.parse_date(r.get("deadline", ""))
        if d is not None and not (today <= d <= today + timedelta(days=days)):
            continue
        rows.append((d or date.max, r))
    rows.sort(key=lambda x: x[0])
    return [r for _, r in rows][:limit]


def mail_items(private: Path, today: date, days: int = 3, limit: int = 5) -> List[dict]:
    path = private / "tracker" / "inbox_summary.json"
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            return []
    except (OSError, ValueError):
        return []
    recent = []
    for it in items:
        if not isinstance(it, dict):
            continue
        d = deadlines.parse_date(it.get("date", ""))
        if d is not None and today - timedelta(days=days) <= d <= today:
            recent.append(it)
    recent.sort(key=lambda it: (it.get("kind") not in MAIL_KINDS_FIRST, str(it.get("date", ""))), reverse=False)
    return recent[:limit]


def scout_note(private: Path, lines: int = 6) -> str:
    path = private / "tracker" / "DAILY_DIGEST.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = [ln.strip() for ln in text if ln.strip() and not ln.startswith("#")][:lines]
    return "\n".join(kept)


def is_fresh(private_dir, today: date) -> bool:
    """True when the scout wrote its digest today, so a stale one is never sent as if it were new."""
    from datetime import datetime
    path = Path(private_dir) / "tracker" / "DAILY_DIGEST.md"
    return path.is_file() and datetime.fromtimestamp(path.stat().st_mtime).date() == today


def build_digest(conn, private_dir, today: date) -> str:
    private = Path(private_dir)
    parts = [f"Digest for {today.strftime('%a %d %b')}"]
    due = deadlines.upcoming(conn, today, days=7)
    if due:
        parts.append("Due this week:\n" + "\n".join("- " + deadlines.label(i, today) for i in due[:6]))
    opps = open_opportunities(private, today)
    if opps:
        lines = []
        for r in opps:
            dl = r.get("deadline") or "deadline unknown"
            lines.append(f"- {r.get('name', '?')} ({r.get('decision', '')}, {dl})")
        parts.append("Worth a look:\n" + "\n".join(lines))
    mail = mail_items(private, today)
    if mail:
        parts.append("Mail:\n" + "\n".join(f"- {m.get('kind', 'mail')}: {m.get('subject', '')} ({m.get('summary', '')})".strip() for m in mail))
    note = scout_note(private)
    if note:
        parts.append("Scout notes:\n" + note)
    if len(parts) == 1:
        parts.append("Nothing new. The scout has not written anything yet.")
    return "\n\n".join(parts)
