"""Drafts of emails to professors. The bot never sends them.

A draft is built from a template and verified facts only: the person, the paper and the project
are quoted from the target row and the facts file, never invented. The one personal sentence is
left as a visible marker for the owner to write. Approving a draft saves it as a ready-to-send
text file; she copies it into her own mail.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from . import approvals
from .facts import FactError, lint

MARKER = "[YOUR OWN LINE: one sentence on why this specific paper or project interests you]"
SPACE_WORDS = ("solar", "space", "flare", "satellite", "astro", "heliophys")


class DraftError(ValueError):
    """The draft cannot be made honestly. The message says what is missing."""


def _surname(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return parts[-1] if parts else ""


def _fact(data: dict, fid: str) -> str:
    fact = data["facts"].get(fid)
    if fact is None:
        raise DraftError(f"the facts file has no '{fid}'")
    if not fact.get("verified", False):
        raise DraftError(f"fact '{fid}' is not verified yet")
    problems = lint(fact["text"])
    if problems:
        raise FactError(f"{fid}: " + "; ".join(problems))
    return fact["text"]


def draft_professor_email(target: dict, data: dict) -> dict:
    """target: a row of outreach_targets.csv. Returns {"to_note", "subject", "body", "target_id"}."""
    name = (target.get("name") or "").strip()
    topic = (target.get("topic_match") or "").strip()
    evidence = (target.get("evidence") or "").strip()
    if not name or not topic:
        raise DraftError("the target row needs a name and a topic match")
    space = any(w in (topic + " " + evidence).lower() for w in SPACE_WORDS)
    project = _fact(data, "hel1" if space else "bs1")
    education = _fact(data, "edu_vit")
    to_note = f"Find the address on the official page ({target.get('official_email_source') or 'institution website'}); never guess it."
    title = re.sub(r"^\d{4}:\s*", "", evidence.split(" (doi")[0]).strip()
    paper = f' I read your work, "{title}", and found it closely related to what I have been doing.' if evidence else ""
    body = (
        f"Dear Professor {_surname(name)},\n\n"
        f"I am a third-year B.Tech student in AI & Robotics at VIT Chennai, writing to ask whether you take summer research interns for 2027.{paper}\n\n"
        f"{MARKER}\n\n"
        f"A project of mine that is relevant: {project[0].lower() + project[1:] if project else ''}\n\n"
        f"I would be grateful for any chance to contribute, even on a small part of your work, on site or remotely. "
        f"My CV and code are linked below, and I can share anything else you would like to see.\n\n"
        f"Thank you for your time.\n\nAshritha Abbabathula\n{education.split(':')[0]}\n"
        f"GitHub: github.com/Ashritha-Abbabathula\n[ADD YOUR EMAIL AND CV LINK]"
    )
    return {"target_id": target.get("id", ""), "to_note": to_note,
            "subject": f"Summer 2027 research internship enquiry: {topic}"[:120], "body": body}


def has_marker(text: str) -> bool:
    return "[YOUR OWN LINE" in text or "[ADD YOUR" in text


def queue_draft(conn, target: dict, data: dict, now=None) -> int:
    draft = draft_professor_email(target, data)
    summary = f"Draft email to {target['name']} ({target.get('institution', '')}): {draft['subject']}"
    return approvals.create(conn, "email_draft", summary, draft, now=now)


def make_executor(folder, today_fn: Callable[[], date]) -> Callable[[dict], str]:
    """On yes, save the draft as a text file for the owner to send herself. Refuses while markers remain."""
    def save(payload: dict) -> str:
        text = payload.get("edited_text") or payload["body"]
        if has_marker(text):
            raise approvals.ApprovalError(
                "That draft still has a placeholder (your own line, or your email and CV link). "
                "Send me the finished text with 'edit N <text>', then 'yes N'.")
        out = Path(folder) / "ready"
        out.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", payload["subject"].lower()).strip("-")[:50]
        path = out / f"{today_fn().isoformat()}-{payload.get('target_id', 'x')}-{slug}.txt"
        path.write_text(f"{payload['to_note']}\nSubject: {payload['subject']}\n\n{text}\n", encoding="utf-8")
        return f"Saved as {path.name}. Copy it into your own mail and send it yourself; I never send."
    return save


def select_targets(csv_path, limit: int = 5) -> list:
    """Rows the owner has marked 'verified' (faculty and openings checked) and that have no draft yet."""
    import csv
    path = Path(csv_path)
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("status") or "").strip().lower() == "verified"]
    return rows[:limit]
