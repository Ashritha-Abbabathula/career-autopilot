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

    def post_file(self, url, fields, file_field, filename, content, timeout=60):
        ctype, data = _multipart(fields, file_field, filename, content)
        req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, "User-Agent": "career-autopilot"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except Exception:
            return 0, ""


def _multipart(fields: dict, file_field: str, filename: str, content: bytes):
    """Build a multipart/form-data body (the standard library has no helper for it)."""
    import uuid
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}".encode() + crlf
                     + f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
                     + str(value).encode("utf-8") + crlf)
    parts.append(f"--{boundary}".encode() + crlf
                 + f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode() + crlf
                 + b"Content-Type: application/octet-stream" + crlf + crlf + content + crlf)
    parts.append(f"--{boundary}--".encode() + crlf)
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)



class FakeHttp:
    """Answers from a list, in order, and records every call."""

    def __init__(self, replies: Optional[List[Tuple[int, str]]] = None):
        self.replies = list(replies or [])
        self.calls: List[dict] = []

    def add(self, status: int, body) -> "FakeHttp":
        self.replies.append((status, body if isinstance(body, str) else json.dumps(body)))
        return self

    def post_file(self, url, fields, file_field, filename, content, timeout=60):
        self.calls.append({"method": "POST-FILE", "url": url, "fields": fields, "filename": filename, "size": len(content)})
        return self.replies.pop(0) if self.replies else (0, "")

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        if not self.replies:
            return 0, ""
        return self.replies.pop(0)
