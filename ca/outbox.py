"""The outbox: every outgoing message goes through here, so the rules live in one place.

Rules, in order, for a proactive message (one the bot starts):
  paused -> blocked_paused; quiet hours -> stays queued until they end;
  daily proactive cap reached -> blocked_budget;
  more than 24h since her last message -> needs a template, else blocked_window
  (only for channels that have such a window; Telegram does not, so it passes window_required=False).
A direct reply to something she just sent is always allowed, even while paused,
so 'resume' and 'help' still answer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from . import clock as clk
from . import db

WINDOW = timedelta(hours=24)


def enqueue(conn, to: str, body: str, kind: str = "reply", template_name: Optional[str] = None,
            send_after: Optional[datetime] = None, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    cur = conn.execute(
        "INSERT INTO outbox (created_at, to_number, kind, body, template_name, send_after) VALUES (?,?,?,?,?,?)",
        (now.isoformat(timespec="seconds"), to, kind, body, template_name,
         (send_after or now).isoformat(timespec="seconds")))
    conn.commit()
    return cur.lastrowid


def _mark(conn, row_id: int, status: str, now: datetime, error: Optional[str] = None) -> None:
    conn.execute("UPDATE outbox SET status = ?, sent_at = ?, error = ? WHERE id = ?",
                 (status, now.isoformat(timespec="seconds") if status == "sent" else None, error, row_id))
    conn.commit()


def last_inbound(conn) -> Optional[datetime]:
    row = conn.execute("SELECT ts FROM messages WHERE direction = 'in' ORDER BY id DESC LIMIT 1").fetchone()
    return datetime.fromisoformat(row["ts"]) if row else None


def window_open(conn, now: datetime) -> bool:
    last = last_inbound(conn)
    return last is not None and now - last <= WINDOW


def proactive_sent_today(conn, now: datetime, tz_name: str) -> int:
    tz = clk.tzinfo_for(tz_name)
    today = now.astimezone(tz).date()
    rows = conn.execute("SELECT sent_at FROM outbox WHERE status = 'sent' AND kind = 'proactive'").fetchall()
    return sum(1 for r in rows if datetime.fromisoformat(r["sent_at"]).astimezone(tz).date() == today)


def flush(conn, sender, now: datetime, tz_name: str = "Asia/Kolkata", quiet_start: int = 23,
          quiet_end: int = 7, daily_proactive_cap: int = 6, window_required: bool = True) -> List[tuple]:
    """Try to send everything due. Returns [(id, status)] for what changed."""
    results = []
    local = now.astimezone(clk.tzinfo_for(tz_name))
    quiet = clk.is_quiet(local, quiet_start, quiet_end)
    paused = db.is_paused(conn)
    rows = conn.execute("SELECT * FROM outbox WHERE status = 'queued' ORDER BY id").fetchall()
    for row in rows:
        if datetime.fromisoformat(row["send_after"]) > now:
            continue
        use_template = False
        if row["kind"] == "proactive":
            if paused:
                _mark(conn, row["id"], "blocked_paused", now); results.append((row["id"], "blocked_paused")); continue
            if quiet:
                continue
            if proactive_sent_today(conn, now, tz_name) >= daily_proactive_cap:
                _mark(conn, row["id"], "blocked_budget", now); results.append((row["id"], "blocked_budget")); continue
            if window_required and not window_open(conn, now):
                if not row["template_name"]:
                    _mark(conn, row["id"], "blocked_window", now); results.append((row["id"], "blocked_window")); continue
                use_template = True
        try:
            if use_template:
                sender.send_template(row["to_number"], row["template_name"], row["body"])
            else:
                sender.send_text(row["to_number"], row["body"])
        except Exception as exc:  # record the type only, never details that might hold a token
            _mark(conn, row["id"], "failed", now, type(exc).__name__)
            results.append((row["id"], "failed"))
            continue
        _mark(conn, row["id"], "sent", now)
        db.add_message(conn, "out", row["body"], channel="chat", status="sent", now=now)
        results.append((row["id"], "sent"))
    return results
