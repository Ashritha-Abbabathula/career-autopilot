"""Model access. The rest of the code sees one method: generate(prompt, purpose) -> text.

GeminiModel calls the Gemini REST API (generateContent, key in the x-goog-api-key header,
never in the URL). It tries each configured model in order, stops at a daily call cap,
and logs every call. FakeModel is used in tests and when there is no key.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Callable, List, Optional, Protocol, Sequence

from . import db

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_NEXT_MODEL = {0, 404, 429, 500, 502, 503, 504}


class ModelError(Exception):
    """The model could not answer. The message is safe to show."""


class CapReached(ModelError):
    pass


class Model(Protocol):
    def generate(self, prompt: str, purpose: str = "general") -> str: ...


class FakeModel:
    """Returns scripted answers. An answer may be a string, an exception, or a function of the prompt."""

    def __init__(self, answers: Optional[Sequence] = None):
        self.answers: List = list(answers or [])
        self.prompts: List[str] = []

    def generate(self, prompt: str, purpose: str = "general") -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise ModelError("The model is not available.")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer(prompt) if callable(answer) else answer


class NoModel:
    """Used when no key is set: every call fails politely, so rules-only features still work."""

    def generate(self, prompt: str, purpose: str = "general") -> str:
        raise ModelError("The model is not set up, so I can only follow fixed commands. Say 'help'.")


class GeminiModel:
    def __init__(self, api_key: str, models: Sequence[str], http, conn, daily_cap: int = 150,
                 now_fn: Optional[Callable[[], datetime]] = None, want_json: bool = True):
        if not api_key:
            raise ValueError("no Gemini key set")
        self._key = api_key
        self.models = list(models)
        self.http = http
        self.conn = conn
        self.daily_cap = daily_cap
        self.now_fn = now_fn
        self.want_json = want_json

    def _now(self) -> Optional[datetime]:
        return self.now_fn() if self.now_fn else None

    def generate(self, prompt: str, purpose: str = "general") -> str:
        if db.model_calls_today(self.conn, now=self._now()) >= self.daily_cap:
            raise CapReached("I have used today's model budget, so I can only follow fixed commands until tomorrow.")
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
        if self.want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        for model in self.models:
            status, text = self.http.request("POST", API.format(model=model),
                                             headers={"x-goog-api-key": self._key}, body=body, timeout=40)
            answer, usage = self._read(status, text)
            db.log_model_call(self.conn, "gemini", model, purpose, usage[0], usage[1], ok=answer is not None, now=self._now())
            if answer is not None:
                return answer
            if status not in RETRY_NEXT_MODEL and status != 200:
                break                                   # e.g. 400 or 403: another model will not help
        raise ModelError("The model did not answer just now. Try again in a minute, or use a fixed command.")

    @staticmethod
    def _read(status: int, text: str):
        if status != 200:
            return None, (0, 0)
        try:
            data = json.loads(text)
            parts = data["candidates"][0]["content"]["parts"]
            answer = "".join(p.get("text", "") for p in parts).strip()
            usage = data.get("usageMetadata", {})
            return (answer or None), (int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0)))
        except (ValueError, KeyError, IndexError, TypeError):
            return None, (0, 0)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str):
    """Parse the model's answer as a JSON object. Tolerates code fences and stray text around it.
    Returns None when there is no valid object, so the caller can ask the user instead of guessing."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text.strip())
    for candidate in (cleaned, cleaned[cleaned.find("{"): cleaned.rfind("}") + 1]):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None
