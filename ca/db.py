"""SQLite storage for Career Autopilot (standard library only).

One file, a handful of tables. Everything the bot sends or decides is recorded
(messages, approvals, model calls) so it can be audited and undone.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'study',          -- dsa, gate, ml, college, misc, application
  planned_date TEXT,                            -- YYYY-MM-DD
  minutes INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','done','skipped','moved')),
  movable INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  date TEXT NOT NULL,                           -- YYYY-MM-DD
  start_time TEXT,
  end_time TEXT,
  fixed INTEGER NOT NULL DEFAULT 1,             -- fixed events never move (exams, labs)
  source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organisation TEXT NOT NULL,
  role_or_programme TEXT NOT NULL,
  location TEXT DEFAULT '',
  source_link TEXT DEFAULT '',
  date_found TEXT DEFAULT '',
  deadline TEXT DEFAULT '',
  match_note TEXT DEFAULT '',
  decision TEXT DEFAULT 'MAYBE' CHECK (decision IN ('APPLY','MAYBE','SKIP','WATCH','APPLY LATER')),
  resume_version TEXT DEFAULT '',
  date_applied TEXT DEFAULT '',
  method TEXT DEFAULT '',
  contact TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'not started',
  next_action TEXT DEFAULT '',
  next_action_date TEXT DEFAULT '',
  notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY,                          -- stable fact id used by the resume renderer
  kind TEXT NOT NULL,                           -- project, skill, award, education, experience
  text TEXT NOT NULL,
  source TEXT NOT NULL,                         -- where the owner can verify it
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,                           -- email, application, whatsapp, plan_change, ...
  summary TEXT NOT NULL,                        -- exact text the owner sees
  payload TEXT NOT NULL DEFAULT '{}',           -- JSON
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','expired','undone')),
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  channel TEXT NOT NULL DEFAULT 'simulator',
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'logged'         -- logged, sent, blocked_paused, blocked_quiet, failed
);

CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  purpose TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 1
);

-- added in schema version 2
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  to_number TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'reply' CHECK (kind IN ('reply','proactive')),
  body TEXT NOT NULL,
  template_name TEXT,
  send_after TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','sent','blocked_paused','blocked_budget','blocked_window','failed')),
  sent_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS plan_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  due_date TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  done INTEGER NOT NULL DEFAULT 0
);
"""

# Allowed approval moves. 'undone' is only reachable from 'approved'.
_TRANSITIONS = {
    "pending": {"approved", "rejected", "expired"},
    "approved": {"undone"},
}


def _now(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    """Open the database (creating the folder). ':memory:' is allowed for tests."""
    if path != ":memory:":
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables. Safe to run many times."""
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    else:  # an older database: the new tables were just created above, so record the new version
        conn.execute("UPDATE schema_version SET version = ? WHERE version < ?", (SCHEMA_VERSION, SCHEMA_VERSION))
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def is_paused(conn: sqlite3.Connection) -> bool:
    """The kill switch. While true, nothing may be sent."""
    return get_setting(conn, "paused", "0") == "1"


def set_paused(conn: sqlite3.Connection, paused: bool) -> None:
    set_setting(conn, "paused", "1" if paused else "0")


def add_message(conn: sqlite3.Connection, direction: str, body: str, channel: str = "simulator",
                status: str = "logged", now: Optional[datetime] = None) -> int:
    cur = conn.execute(
        "INSERT INTO messages (ts, direction, channel, body, status) VALUES (?,?,?,?,?)",
        (_now(now), direction, channel, body, status))
    conn.commit()
    return cur.lastrowid


def add_approval(conn: sqlite3.Connection, kind: str, summary: str, payload: Optional[dict] = None,
                 now: Optional[datetime] = None) -> int:
    cur = conn.execute(
        "INSERT INTO approvals (created_at, kind, summary, payload) VALUES (?,?,?,?)",
        (_now(now), kind, summary, json.dumps(payload or {}, sort_keys=True)))
    conn.commit()
    return cur.lastrowid


def decide_approval(conn: sqlite3.Connection, approval_id: int, new_status: str,
                    now: Optional[datetime] = None) -> None:
    row = conn.execute("SELECT status FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise KeyError(f"no approval {approval_id}")
    if new_status not in _TRANSITIONS.get(row["status"], set()):
        raise ValueError(f"cannot move an approval from {row['status']} to {new_status}")
    conn.execute("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?",
                 (new_status, _now(now), approval_id))
    conn.commit()


def pending_approvals(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY id").fetchall()


def log_model_call(conn: sqlite3.Connection, provider: str, model: str, purpose: str,
                   prompt_tokens: int = 0, output_tokens: int = 0, ok: bool = True,
                   now: Optional[datetime] = None) -> None:
    conn.execute(
        "INSERT INTO model_calls (ts, provider, model, purpose, prompt_tokens, output_tokens, ok) "
        "VALUES (?,?,?,?,?,?,?)",
        (_now(now), provider, model, purpose, prompt_tokens, output_tokens, 1 if ok else 0))
    conn.commit()


def model_calls_today(conn: sqlite3.Connection, now: Optional[datetime] = None) -> int:
    """Calls made since 00:00 UTC today; used for the daily cap."""
    day = (now or datetime.now(timezone.utc)).date().isoformat()
    return conn.execute("SELECT COUNT(*) FROM model_calls WHERE ts >= ?", (day,)).fetchone()[0]
