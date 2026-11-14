"""Telegram Bot API: send messages and read new ones by long polling (no webhook, no public address).

The bot token appears only in the request URL, which this code never logs or puts in an error.
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4000          # Telegram's hard limit is 4096 characters per message


class TelegramError(RuntimeError):
    """Safe to log: carries only the HTTP status, never the URL or token."""


def split_text(text: str, limit: int = LIMIT) -> List[str]:
    text = text or ""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return [p for p in parts if p] or [""]


class TelegramSender:
    def __init__(self, http, token: str, chat_id: str):
        if not token or not chat_id:
            raise ValueError("Telegram token and chat id are both needed")
        self.http, self._token, self.chat_id = http, token, chat_id

    def send_text(self, to: str, body: str) -> None:
        # Only the owner's chat is ever used, whatever "to" says.
        for part in split_text(body):
            status, _ = self.http.request("POST", API.format(token=self._token, method="sendMessage"),
                                          body={"chat_id": self.chat_id, "text": part,
                                                "disable_web_page_preview": True}, timeout=20)
            if status != 200:
                raise TelegramError(f"sendMessage failed with status {status}")

    def send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        status, _ = self.http.post_file(API.format(token=self._token, method="sendDocument"),
                                        {"chat_id": self.chat_id, "caption": caption[:900]}, "document", filename, content)
        if status != 200:
            raise TelegramError(f"sendDocument failed with status {status}")

    def send_template(self, to: str, template_name: str, body: str) -> None:
        self.send_text(to, body)          # Telegram has no templates


def get_updates(http, token: str, offset: Optional[int], wait: int = 25) -> Tuple[bool, list]:
    """Returns (ok, [(update_id, chat_id, text)]). Updates with no text (stickers, photos) are still
    returned with empty text so their ids can be skipped over."""
    body = {"timeout": wait, "allowed_updates": ["message"]}
    if offset is not None:
        body["offset"] = offset
    status, text = http.request("POST", API.format(token=token, method="getUpdates"), body=body, timeout=wait + 10)
    if status != 200:
        return False, []
    try:
        data = json.loads(text)
        if not data.get("ok"):
            return False, []
        out = []
        for u in data["result"]:
            msg = u.get("message") or {}
            out.append((int(u["update_id"]), str((msg.get("chat") or {}).get("id", "")), msg.get("text") or ""))
        return True, out
    except (ValueError, KeyError, TypeError):
        return False, []
