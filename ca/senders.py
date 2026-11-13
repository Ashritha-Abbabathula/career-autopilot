"""Senders: the only code that talks to a messaging channel. Replaceable and fakeable.

A sender raises on failure; the outbox decides what that means. The real WhatsApp
sender is added in step CA-7; until then everything runs against these.
"""
from __future__ import annotations

from typing import List, Protocol, Tuple


class Sender(Protocol):
    def send_text(self, to: str, body: str) -> None: ...
    def send_template(self, to: str, template_name: str, body: str) -> None: ...


class FakeSender:
    """Records what would be sent. Used by tests and the local simulator."""

    def __init__(self, fail: bool = False):
        self.sent: List[Tuple[str, str, str]] = []   # (kind, to, body)
        self.fail = fail

    def send_text(self, to: str, body: str) -> None:
        if self.fail:
            raise RuntimeError("simulated failure")
        self.sent.append(("text", to, body))

    def send_template(self, to: str, template_name: str, body: str) -> None:
        if self.fail:
            raise RuntimeError("simulated failure")
        self.sent.append(("template:" + template_name, to, body))


class ConsoleSender(FakeSender):
    """Prints instead of sending; for the chat simulator."""

    def send_text(self, to: str, body: str) -> None:
        super().send_text(to, body)
        print(body)

    def send_template(self, to: str, template_name: str, body: str) -> None:
        super().send_template(to, template_name, body)
        print(body)
