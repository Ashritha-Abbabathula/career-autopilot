"""The approval queue: anything that leaves the owner's account waits here for her yes.

Rules:
- Nothing runs while paused (the kill switch).
- An approval runs its executor at most once; a failed executor leaves it pending.
- Undo only works on approved items, and runs the matching undo function if there is one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

from . import db


class ApprovalError(Exception):
    """A refused or failed approval action. The message is safe to show to the owner."""


@dataclass
class Executors:
    run: Dict[str, Callable[[dict], str]] = field(default_factory=dict)
    undo: Dict[str, Callable[[dict], str]] = field(default_factory=dict)


def create(conn, kind: str, summary: str, payload: Optional[dict] = None, now: Optional[datetime] = None) -> int:
    return db.add_approval(conn, kind, summary, payload or {}, now=now)


def get(conn, approval_id: int):
    return conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()


def pending(conn) -> list:
    return db.pending_approvals(conn)


def _require(conn, approval_id: int, status: str):
    row = get(conn, approval_id)
    if row is None:
        raise ApprovalError(f"There is no item {approval_id}.")
    if row["status"] != status:
        raise ApprovalError(f"Item {approval_id} is {row['status']}, not {status}.")
    return row


def approve(conn, approval_id: int, executors: Executors, now: Optional[datetime] = None) -> str:
    if db.is_paused(conn):
        raise ApprovalError("Everything is paused. Say 'resume' first.")
    row = _require(conn, approval_id, "pending")
    fn = executors.run.get(row["kind"])
    if fn is None:
        raise ApprovalError(f"I do not know how to do '{row['kind']}' yet, so I left item {approval_id} waiting.")
    try:
        result = fn(json.loads(row["payload"]))
    except ApprovalError:
        raise
    except Exception as exc:  # leave it pending; never show internals
        raise ApprovalError(f"Item {approval_id} did not go through ({type(exc).__name__}). It is still waiting.") from None
    db.decide_approval(conn, approval_id, "approved", now=now)
    return result


def reject(conn, approval_id: int, now: Optional[datetime] = None) -> None:
    _require(conn, approval_id, "pending")
    db.decide_approval(conn, approval_id, "rejected", now=now)


def later(conn, approval_id: int) -> None:
    """Snooze: nothing changes, it simply stays pending. Validates that it exists and is pending."""
    _require(conn, approval_id, "pending")


def edit(conn, approval_id: int, new_text: str) -> None:
    row = _require(conn, approval_id, "pending")
    payload = json.loads(row["payload"])
    payload["edited_text"] = new_text
    conn.execute("UPDATE approvals SET payload = ?, summary = ? WHERE id = ?",
                 (json.dumps(payload, sort_keys=True), row["summary"].split(" (edited)")[0] + " (edited)", approval_id))
    conn.commit()


def undo(conn, approval_id: int, executors: Executors, now: Optional[datetime] = None) -> str:
    row = _require(conn, approval_id, "approved")
    fn = executors.undo.get(row["kind"])
    message = "Marked as undone."
    if fn is not None:
        try:
            message = fn(json.loads(row["payload"]))
        except Exception as exc:
            raise ApprovalError(f"I could not undo item {approval_id} ({type(exc).__name__}).") from None
    db.decide_approval(conn, approval_id, "undone", now=now)
    return message


def last_approved(conn):
    return conn.execute("SELECT * FROM approvals WHERE status = 'approved' ORDER BY decided_at DESC, id DESC LIMIT 1").fetchone()
