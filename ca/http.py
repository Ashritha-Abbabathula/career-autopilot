"""A tiny HTTP interface so nothing else imports urllib, and tests never touch the network."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Protocol, Tuple


class HttpClient(Protocol):
    def request(self, method: str, url: str, headers: Optional[Dict[str, str]] = None,
                body: Optional[dict] = None, timeout: float = 30) -> Tuple[int, str]: ...


class UrllibHttp:
    """Real client. Returns (status, text) and never raises for HTTP error codes.
    Network failures come back as status 0 with no detail, so a URL holding a token is never echoed."""

    def request(self, method, url, headers=None, body=None, timeout=30):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = {"User-Agent": "career-autopilot"}
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except Exception:
            return 0, ""


class FakeHttp:
    """Answers from a list, in order, and records every call."""

    def __init__(self, replies: Optional[List[Tuple[int, str]]] = None):
        self.replies = list(replies or [])
        self.calls: List[dict] = []

    def add(self, status: int, body) -> "FakeHttp":
        self.replies.append((status, body if isinstance(body, str) else json.dumps(body)))
        return self

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        if not self.replies:
            return 0, ""
        return self.replies.pop(0)
