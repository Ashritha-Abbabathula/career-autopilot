"""Understand a WhatsApp message: a small fixed grammar, no model involved.

Anything that is not in the grammar comes back as kind 'free_text' and is handled later by the
intent layer (the model), with the user asked on any doubt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MENU_WORDS = {"today", "week", "apps", "inbox", "pause", "resume", "undo", "help", "focus", "digest", "scorecard"}
_REPLY = re.compile(r"^(yes|y|ok|approve|skip|no|later|edit)\b\s*#?(\d+)?\s*(.*)$", re.I)
_PUSH = re.compile(r"^push\s+(.+?)\s+(?:to|until|till)\s+(.+)$", re.I)
_FREE = re.compile(r"^(?:i\s+(?:only\s+)?have\s+|only\s+|free\s+)?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b(?:\s+(?:free|left|today))*$", re.I)
_DONE = re.compile(r"^done\s+(.+)$", re.I)
_SKIPTASK = re.compile(r"^skip\s+(?!#?\d+\b)(.+)$", re.I)


@dataclass(frozen=True)
class Command:
    kind: str                       # a menu word, yes, skip, later, edit, push, free, done, skip_task, free_text, empty
    number: int | None = None       # approval number for yes/skip/later/edit
    text: str = ""                  # remaining text (edit text, task name, original free text)
    args: dict = field(default_factory=dict)


def parse(raw: str) -> Command:
    text = (raw or "").strip()
    if not text:
        return Command("empty")
    word = text.lower().strip(" .!?")
    if word in MENU_WORDS:
        return Command(word)
    m = _PUSH.match(text)
    if m:
        return Command("push", args={"task": m.group(1).strip(), "to": m.group(2).strip().lower()}, text=text)
    m = _DONE.match(text)
    if m:
        return Command("done", args={"task": m.group(1).strip()}, text=text)
    m = _SKIPTASK.match(text)
    if m:
        return Command("skip_task", args={"task": m.group(1).strip()}, text=text)
    m = _FREE.match(text)
    if m:
        return Command("free", args={"hours": float(m.group(1))}, text=text)
    m = _REPLY.match(text)
    if m:
        verb = m.group(1).lower()
        kind = {"y": "yes", "ok": "yes", "approve": "yes", "no": "skip"}.get(verb, verb)
        number = int(m.group(2)) if m.group(2) else None
        rest = m.group(3).strip()
        if kind == "edit" and number is None:
            return Command("free_text", text=text)
        return Command(kind, number=number, text=rest)
    return Command("free_text", text=text)
