"""WhatsApp Cloud API webhook (standard library only).

What it does, and nothing more yet:
- GET  /webhook : Meta's handshake. Echoes the challenge only if the verify token matches.
- POST /webhook : incoming messages. Every request must carry a valid X-Hub-Signature-256
  (HMAC of the body with the app secret). With no app secret configured, EVERY request is
  rejected (fail closed). Only messages from the owner's number are stored; messages from
  anyone else are dropped without being stored.
It never sends a message. Sending comes in a later slice, behind the approval queue.

Run:  python -m ca.webhook            (reads .env in the current folder)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import db
from .config import Config, load_config


def verify_challenge(params: dict, verify_token: str) -> Optional[str]:
    """Return the challenge to echo back, or None if the request is not a valid handshake."""
    if not verify_token:
        return None
    mode = (params.get("hub.mode") or [""])[0]
    token = (params.get("hub.verify_token") or [""])[0]
    challenge = (params.get("hub.challenge") or [""])[0]
    if mode == "subscribe" and challenge and hmac.compare_digest(token, verify_token):
        return challenge
    return None


def valid_signature(app_secret: str, body: bytes, header: str) -> bool:
    """Fail closed: no secret, no header, or a wrong signature all mean False."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def extract_text_messages(payload: dict) -> list:
    """Pull (sender, id, text) out of Meta's nested payload. Non-text messages are kept with empty text."""
    out = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            for msg in (change.get("value", {}) or {}).get("messages", []) or []:
                text = ""
                if msg.get("type") == "text":
                    text = (msg.get("text") or {}).get("body", "")
                out.append({"from": str(msg.get("from", "")), "id": msg.get("id", ""),
                            "type": msg.get("type", ""), "text": text})
    return out


def handle_post(conn, cfg: Config, body: bytes, signature_header: str) -> tuple:
    """Return (status_code, stored_count). Stores only the owner's messages."""
    if not valid_signature(cfg.whatsapp_app_secret, body, signature_header):
        return 403, 0
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return 400, 0
    stored = 0
    for msg in extract_text_messages(payload):
        if not cfg.owner_whatsapp or msg["from"] != cfg.owner_whatsapp:
            continue  # not the owner: dropped, not stored
        shown = msg["text"] if msg["type"] == "text" else f"[{msg['type']} message]"
        db.add_message(conn, "in", shown, channel="whatsapp")
        stored += 1
    return 200, stored


def make_handler(cfg: Config, conn):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, text: str = "") -> None:
            data = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/webhook":
                challenge = verify_challenge(parse_qs(url.query), cfg.whatsapp_verify_token)
                if challenge is None:
                    return self._reply(403, "forbidden")
                return self._reply(200, challenge)
            if url.path in ("/", "/health"):
                return self._reply(200, "career autopilot webhook: ok")
            return self._reply(404, "not found")

        def do_POST(self):
            if urlparse(self.path).path != "/webhook":
                return self._reply(404, "not found")
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(min(length, 1_000_000))
            code, _ = handle_post(conn, cfg, body, self.headers.get("X-Hub-Signature-256", ""))
            self._reply(code, "ok" if code == 200 else "rejected")

        def log_message(self, fmt, *args):  # never log request bodies or tokens
            sys.stderr.write("webhook %s %s\n" % (self.command, urlparse(self.path).path))

    return Handler


def main() -> None:
    cfg = load_config()
    missing = [n for n, v in (("WHATSAPP_VERIFY_TOKEN", cfg.whatsapp_verify_token),
                              ("WHATSAPP_APP_SECRET", cfg.whatsapp_app_secret),
                              ("OWNER_WHATSAPP", cfg.owner_whatsapp)) if not v]
    if missing:
        print("Not starting: still missing in .env: " + ", ".join(missing))
        sys.exit(1)
    conn = db.connect(cfg.db_path)
    db.init_schema(conn)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"webhook listening on http://localhost:{port}/webhook (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", port), make_handler(cfg, conn)).serve_forever()


if __name__ == "__main__":
    main()
