"""Monthly LinkedIn post draft. The bot drafts; the owner posts with LinkedIn's own schedule button.

A schedule file in the private folder lists each post:
  [{"post_date": "2026-12-08", "project": "Buried Survivor Detector", "facts": ["bs_hw1", ...], "link": "github.com/..."}]
The draft is written only from those verified facts. It is checked for banned claims and saved as a file.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from .facts import lint
from .llm import Model, ModelError, extract_json

LEAD_DAYS = 7

PROMPT = """Write a LinkedIn post for a third-year B.Tech student about one of her projects.
Return ONE JSON object: {{"post": "the full post text"}}.
Rules: 120 to 180 words; short plain sentences, no buzzwords, no hashtags spam (at most 3); first line is one concrete hook;
say what she built and why; include one measured result and one thing that went wrong or surprised her, but ONLY if the facts below state them;
if they do not, write the placeholder [ADD ONE REAL NUMBER OR MOMENT FROM YOUR OWN WORK] instead of inventing anything;
end with the link and one question asking for feedback (not for a job). Never say published, accepted or national unless a fact says so.
Project: {project}
Link: {link}
Facts (the only things you may state):
{facts}"""


def load_schedule(path) -> List[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("post_date") and d.get("project")]
    except (OSError, ValueError):
        return []


def due_entry(schedule: List[dict], today: date) -> Optional[dict]:
    """The post whose draft should be written today: its date minus LEAD_DAYS, not earlier than that day."""
    for entry in schedule:
        try:
            post = date.fromisoformat(entry["post_date"])
        except ValueError:
            continue
        if post - timedelta(days=LEAD_DAYS) <= today <= post:
            return entry
    return None


def draft_path(folder, entry: dict) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", entry["project"].lower()).strip("-")[:40]
    return Path(folder) / f"{entry['post_date']}-{slug}.txt"


def make_draft(model: Model, entry: dict, data: dict) -> str:
    """Returns the draft text. Raises ValueError with a safe message if it cannot be made honestly."""
    texts = []
    for fid in entry.get("facts", []):
        fact = data["facts"].get(fid)
        if fact and fact.get("verified"):
            texts.append(f"- {fact['text']}")
    if not texts:
        raise ValueError("no verified facts are listed for this project")
    try:
        answer = model.generate(PROMPT.format(project=entry["project"], link=entry.get("link", "[ADD THE REPO LINK]"),
                                              facts="\n".join(texts)), purpose="linkedin")
    except ModelError as exc:
        raise ValueError(str(exc)) from None
    parsed = extract_json(answer)
    post = str((parsed or {}).get("post", "")).strip()
    if len(post) < 200:
        raise ValueError("the model's draft was missing or too short")
    problems = lint(post)
    if problems:
        raise ValueError("the draft made a claim you ruled out (" + "; ".join(problems) + "), so I did not keep it")
    return post


def job(conn_unused, model: Model, data: dict, schedule_path, drafts_folder, today: date) -> Optional[str]:
    """Text to send, or None when no draft is due or one already exists."""
    entry = due_entry(load_schedule(schedule_path), today)
    if entry is None:
        return None
    path = draft_path(drafts_folder, entry)
    if path.exists():
        return None
    try:
        post = make_draft(model, entry, data)
    except ValueError as exc:
        return f"I couldn't write the LinkedIn draft for {entry['project']} ({exc}). I'll try again tomorrow."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(post + "\n", encoding="utf-8")
    return (f"LinkedIn draft for {entry['project']} (post date {entry['post_date']}):\n\n{post}\n\n"
            f"Change a line or two into your own voice, then schedule it with LinkedIn's own button. Saved as {path.name}.")
