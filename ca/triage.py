"""Triage a pasted post or link: APPLY, MAYBE, WATCH or SKIP, with a reason she can check.

Rules run first and can only say SKIP (a fee, a scam pattern). Then the model reads the text
and fills in organisation, role, deadline and a decision, validated before use. If the model
is unavailable the answer is MAYBE with an honest note, never a made-up verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import tracker
from .llm import Model, ModelError, extract_json

URL = re.compile(r"https?://\S+", re.I)

FEE = re.compile(
    r"registration\s+fee|training\s+fee|security\s+deposit|refundable\s+deposit|processing\s+fee|"
    r"pay\s+(?:rs|inr|₹|\$)?\s?\d|(?:rs\.?|inr|₹)\s?\d[\d,]*\s*(?:only|/-)?\s*(?:to\s+(?:join|enrol|register|confirm))|"
    r"fee\s+of\s+(?:rs\.?|inr|₹|\$)\s?\d|paid\s+internship\s+after\s+(?:training|paying)", re.I)
SCAM = re.compile(
    r"guaranteed\s+(?:job|placement|internship)|no\s+interview|earn\s+(?:rs|inr|₹|\$)?\s?\d[\d,]*\s*(?:per|a|/)\s*(?:day|week)|"
    r"whatsapp\s+(?:us|me|this\s+number)\s+to\s+(?:apply|join)|dm\s+to\s+apply\s+on\s+telegram|"
    r"offer\s+letter\s+(?:fee|charges)|limited\s+seats?\s+(?:left|hurry)|lifetime\s+validity", re.I)
VALID = {"APPLY", "MAYBE", "WATCH", "SKIP"}

PROMPT = """You help a third-year B.Tech AI & Robotics student in India choose internships and programmes.
She wants: on-site summer 2027 internship in Bengaluru first, then Hyderabad; ISRO, DRDO, research fellowships, robotics, ML and software roles; international and remote-in-India are acceptable; paid or unpaid is fine, but never anything that asks her for money.
Read the post below and reply with ONE JSON object and nothing else:
{{"decision": "APPLY" or "MAYBE" or "WATCH" or "SKIP", "reason": "one short sentence", "organisation": "", "role": "", "location": "", "deadline": "YYYY-MM-DD or empty"}}
APPLY = clearly fits and is open; WATCH = fits but not open yet; MAYBE = unclear fit or missing details; SKIP = poor fit, wrong year or eligibility, or looks untrustworthy.
Use only what the post says. Do not guess the organisation or deadline.

Post:
{text}"""


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str
    organisation: str = ""
    role: str = ""
    location: str = ""
    deadline: str = ""
    link: str = ""
    by_rule: bool = False


def rule_check(text: str) -> Optional[str]:
    """A reason to SKIP without asking the model, or None."""
    if FEE.search(text):
        return "it asks you to pay a fee or deposit"
    if SCAM.search(text):
        return "it uses wording typical of scams (guarantees, no interview, pay-to-join)"
    return None


def triage(model: Model, text: str) -> Verdict:
    text = (text or "").strip()
    link = (URL.search(text) or [""])[0] if URL.search(text) else ""
    reason = rule_check(text)
    if reason:
        return Verdict("SKIP", f"Skipped by rule: {reason}.", link=link, by_rule=True)
    try:
        answer = model.generate(PROMPT.format(text=text[:3000]), purpose="triage")
    except ModelError as exc:
        return Verdict("MAYBE", f"I could not read it with the model ({exc}) so I did not judge it; check it yourself.", link=link)
    data = extract_json(answer)
    if not data or str(data.get("decision", "")).upper() not in VALID:
        return Verdict("MAYBE", "I could not tell what this is; check it yourself.", link=link)
    deadline = str(data.get("deadline", "")).strip()
    if deadline and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline):
        deadline = ""
    return Verdict(str(data["decision"]).upper(), str(data.get("reason", "")).strip()[:200] or "No reason given.",
                   str(data.get("organisation", "")).strip()[:80], str(data.get("role", "")).strip()[:100],
                   str(data.get("location", "")).strip()[:60], deadline, link)


def add_to_tracker(conn, verdict: Verdict, today_iso: str) -> Optional[int]:
    """Record a verdict as a tracker row unless it names no organisation and role (then nothing is invented)."""
    if not verdict.organisation or not verdict.role:
        return None
    existing = tracker.find(conn, verdict.organisation, verdict.role)
    if existing is not None:
        return existing["id"]
    return tracker.add(conn, verdict.organisation, verdict.role, location=verdict.location,
                       source_link=verdict.link, date_found=today_iso, deadline=verdict.deadline or "unknown",
                       match_note=verdict.reason, decision=verdict.decision)


def describe(v: Verdict, row_id: Optional[int]) -> str:
    head = f"{v.decision}: {v.reason}"
    bits = [b for b in (v.organisation, v.role, v.location) if b]
    if bits:
        head += "\n" + ", ".join(bits)
    if v.deadline:
        head += f"\nDeadline: {v.deadline}"
    head += f"\nSaved to your tracker as #{row_id}." if row_id else "\nNot saved: I could not tell the organisation and role."
    return head
