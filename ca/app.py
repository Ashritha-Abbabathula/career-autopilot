"""The conversation core: one message in, one reply queued. No network, no model here.

Later steps register handlers for more commands (today, week, apps, done, push...).
Unregistered commands get an honest "not set up yet" instead of a guess.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, Optional

from . import approvals, db, outbox
from .approvals import ApprovalError, Executors
from .router import Command, parse

HELP = (
    "I can do these:\n"
    "today / week - your plan\n"
    "apps - what you have applied to\n"
    "inbox - things waiting for your yes\n"
    "yes N / skip N / later N / edit N <text> - answer an item\n"
    "undo - take back the last approved item\n"
    "pause / resume - stop or restart everything I do on my own\n"
    "help - this list"
)

Handler = Callable[["App", Command, datetime], str]


class App:
    def __init__(self, conn, owner: str, executors: Optional[Executors] = None):
        self.conn = conn
        self.owner = owner
        self.executors = executors or Executors()
        self.handlers: Dict[str, Handler] = {}

    def register(self, kind: str, fn: Handler) -> None:
        self.handlers[kind] = fn

    # ---- entry point -------------------------------------------------
    def handle(self, raw: str, now: datetime, channel: str = "whatsapp") -> str:
        """Log the message, work out the reply, queue it, and return its text."""
        db.add_message(self.conn, "in", raw or "", channel=channel, now=now)
        reply = self._reply(parse(raw), now)
        outbox.enqueue(self.conn, self.owner, reply, "reply", now=now)
        return reply

    def _reply(self, cmd: Command, now: datetime) -> str:
        try:
            if cmd.kind == "empty":
                return "Say 'help' to see what I can do."
            if cmd.kind == "help":
                return HELP
            if cmd.kind == "pause":
                db.set_paused(self.conn, True)
                return "Paused. I will not message you on my own or approve anything until you say 'resume'."
            if cmd.kind == "resume":
                db.set_paused(self.conn, False)
                return "Resumed."
            if cmd.kind == "inbox":
                return self._inbox()
            if cmd.kind in ("yes", "skip", "later", "edit"):
                return self._answer(cmd, now)
            if cmd.kind == "undo":
                return self._undo(now)
            fn = self.handlers.get(cmd.kind)
            if fn is not None:
                return fn(self, cmd, now)
            if cmd.kind == "free_text":
                return "I did not understand that. Say 'help' to see what I can do."
            return f"'{cmd.kind}' is not set up yet."
        except ApprovalError as exc:
            return str(exc)

    # ---- approvals ---------------------------------------------------
    def _inbox(self) -> str:
        rows = approvals.pending(self.conn)
        if not rows:
            return "Nothing is waiting for you."
        lines = [f"{len(rows)} waiting:"] + [f"{r['id']}. {r['summary']}" for r in rows]
        lines.append("Reply 'yes N', 'skip N', 'later N' or 'edit N <text>'.")
        return "\n".join(lines)

    def _target(self, cmd: Command) -> int:
        if cmd.number is not None:
            return cmd.number
        rows = approvals.pending(self.conn)
        if len(rows) == 1:
            return rows[0]["id"]
        if not rows:
            raise ApprovalError("Nothing is waiting for you.")
        raise ApprovalError("More than one item is waiting. Say which, like 'yes 3'. Send 'inbox' to see them.")

    def _answer(self, cmd: Command, now: datetime) -> str:
        n = self._target(cmd)
        if cmd.kind == "yes":
            return approvals.approve(self.conn, n, self.executors, now=now) or f"Done: item {n}."
        if cmd.kind == "skip":
            approvals.reject(self.conn, n, now=now)
            return f"Skipped item {n}."
        if cmd.kind == "later":
            approvals.later(self.conn, n)
            return f"Okay, item {n} stays in your inbox."
        if not cmd.text:
            raise ApprovalError("Tell me the new text, like 'edit 3 shorter version'.")
        approvals.edit(self.conn, n, cmd.text)
        return f"Updated item {n}. Reply 'yes {n}' to approve it."

    def _undo(self, now: datetime) -> str:
        row = approvals.last_approved(self.conn)
        if row is None:
            return "There is nothing to undo."
        return approvals.undo(self.conn, row["id"], self.executors, now=now)
