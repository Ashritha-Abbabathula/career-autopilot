"""The facts file: every claim on a resume has an id, a source the owner can check, and a verified flag.

Format (JSON, kept in the owner's private folder):
{
  "person":   {"name", "headline", "contact": ["...", "..."]},
  "facts":    {"<id>": {"kind", "text", "source", "verified": true/false, "group": "optional label"}},
  "projects": {"<id>": {"title", "meta"}},
  "variants": {"<name>": {"summary": "<fact id>",
                          "skills": ["<fact id>", ...],
                          "education": ["<fact id>", ...],
                          "projects": [{"id": "<project id>", "bullets": ["<fact id>", ...]}],
                          "extras": ["<fact id>", ...]}}
}
Nothing is ever written into a resume that is not a fact in this file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List


class FactError(ValueError):
    """The facts file or a resume request is not acceptable. The message names the id or phrase at fault."""


# Phrases the owner ruled out (see FACTS_CONFIRMED). A fact containing one cannot be rendered.
BANNED = [
    (re.compile(r"nationally\s+shortlisted", re.I), "the shortlisting was inside VIT Chennai, not national"),
    (re.compile(r"smart india hackathon\s*2025|\bSIH\s*2025", re.I), "it is Smart India Hackathon 2026"),
    (re.compile(r"\bpublished\b|\baccepted\b|peer[- ]reviewed", re.I), "the study and patent are unpublished"),
    (re.compile(r"patent application (?:filed|in progress)", re.I), "patent stage is unconfirmed"),
    (re.compile(r"\[verify\]", re.I), "unresolved [verify] marker"),
    (re.compile(r"failbox", re.I), "FailBox stays off resumes"),
]


def lint(text: str) -> List[str]:
    """Reasons a piece of resume text must not be used; empty means fine."""
    return [reason for pattern, reason in BANNED if pattern.search(text or "")]


def load(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise FactError("the facts file is missing or is not valid JSON") from None
    validate(data)
    return data


def validate(data: dict) -> None:
    for key in ("person", "facts", "projects", "variants"):
        if key not in data:
            raise FactError(f"the facts file has no '{key}' section")
    facts = data["facts"]
    for fid, fact in facts.items():
        for field in ("kind", "text", "source"):
            if not str(fact.get(field, "")).strip():
                raise FactError(f"fact {fid} has no {field}")
    for name, variant in data["variants"].items():
        ids = [variant.get("summary", "")] + variant.get("skills", []) + variant.get("education", []) + variant.get("extras", [])
        for proj in variant.get("projects", []):
            if proj["id"] not in data["projects"]:
                raise FactError(f"variant {name} uses unknown project {proj['id']}")
            ids += proj.get("bullets", [])
        for fid in ids:
            if fid not in facts:
                raise FactError(f"variant {name} uses unknown fact {fid}")
