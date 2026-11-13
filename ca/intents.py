"""Free text to a structured request. The model only interprets; it never acts.

Its answer must be a JSON object naming one allowed action with the right arguments.
Anything else (bad JSON, unknown action, missing argument, low confidence) becomes a
clarifying question to the owner, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .llm import Model, ModelError, extract_json
from .router import Command

CONFIDENCE_MIN = 0.7

# action -> (router command kind, required argument names)
ACTIONS = {
    "done": ("done", ("task",)),
    "skip": ("skip_task", ("task",)),
    "push": ("push", ("task", "to")),
    "free_hours": ("free", ("hours",)),
    "show_today": ("today", ()),
    "show_week": ("week", ()),
    "show_apps": ("apps", ()),
    "show_inbox": ("inbox", ()),
    "none": ("free_text", ()),
}

PROMPT = """You turn one message from a student into a request for her study assistant.
Reply with ONE JSON object and nothing else:
{{"action": one of {actions}, "args": {{...}}, "confidence": number 0 to 1, "question": "a short question if unsure, else empty"}}
Arguments: done and skip need "task" (words from the task title, or leetcode, gate, youtube, all);
push needs "task" and "to" (tomorrow, a weekday name, or YYYY-MM-DD); free_hours needs "hours" (a number).
Use "none" when the message is not a request for one of these. Never invent tasks.
Today is {today}. Today's tasks still to do:
{tasks}

Message: {text}"""


@dataclass(frozen=True)
class Intent:
    command: Optional[Command] = None
    ask: str = ""
    failed: bool = False                      # the model itself was unavailable
    raw_action: str = ""


def _ask(question: str = "") -> Intent:
    return Intent(ask=question or "I am not sure what you mean. Say 'help' to see what I can do.")


def parse_answer(answer: str, original: str) -> Intent:
    data = extract_json(answer)
    if data is None:
        return _ask()
    action = str(data.get("action", "")).strip()
    if action not in ACTIONS:
        return _ask()
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    kind, required = ACTIONS[action]
    if action == "none":
        return Intent(command=Command("free_text", text=original), raw_action=action)
    question = str(data.get("question", "")).strip()[:200]
    if confidence < CONFIDENCE_MIN:
        return _ask(question or "Did you mean one of these? Say 'help' to see the commands.")
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    clean = {}
    for name in required:
        value = args.get(name)
        if value is None or str(value).strip() == "":
            return _ask(question or f"I need a bit more: what is the {name}?")
        clean[name] = str(value).strip()
    if "hours" in clean:
        try:
            hours = float(clean["hours"])
        except ValueError:
            return _ask("How many hours do you have?")
        if not 0 < hours <= 16:
            return _ask("How many hours do you have today?")
        clean["hours"] = hours
    return Intent(command=Command(kind, args=clean, text=original), raw_action=action)


def interpret(model: Model, text: str, today: date, task_titles: list) -> Intent:
    tasks = "\n".join(f"- {t}" for t in task_titles[:25]) or "(none)"
    prompt = PROMPT.format(actions=", ".join(ACTIONS), today=today.isoformat(), tasks=tasks, text=text.strip()[:500])
    try:
        answer = model.generate(prompt, purpose="intent")
    except ModelError as exc:
        return Intent(ask=str(exc), failed=True)
    return parse_answer(answer, text)
