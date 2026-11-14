"""A tiny web page for the calendar, served only to this computer (127.0.0.1).

GET /            your original 90-day page (or the built-in calendar if the original is not in the private folder),
                 built fresh from the database on every visit
POST /api/state  {"k": "dsa-done", "v": "..."}          save what the page remembers (null deletes)
POST /api/tick   {"id": "t12", "done": true}            tick one of the assistant's own items
POST /api/decide {"id": "t40", "action": "approve"}     approve, skip or later on an assistant item
Nothing is reachable from outside this machine, and posts without the page's own header are refused.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import calendar_view, db, original_page, uistate
from . import clock as clk

LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
MAX_BODY = 4_000_000


def _host_name(header: str) -> str:
    header = header or ""
    return header.split("]")[0] + "]" if header.startswith("[") else header.rsplit(":", 1)[0] if ":" in header else header


def make_handler(db_path: str, tz_name: str, private_dir: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                       # keep the console quiet and free of request details
            pass

        def _host_ok(self) -> bool:
            return _host_name(self.headers.get("Host") or "") in LOCAL_HOSTS      # blocks DNS-rebinding tricks

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            if self.path.split("?")[0] not in ("/", "/index.html"):
                return self._send(404, b"not found", "text/plain")
            conn = db.connect(db_path)
            try:
                today = datetime.now(clk.tzinfo_for(tz_name)).date()
                html = original_page.render(conn, private_dir, today) if private_dir else None
                if html is None:
                    start, end = calendar_view.span(conn, today)
                    html = calendar_view.render(conn, today, start, end)
            finally:
                conn.close()
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Calendar") != "1":
                return self._send(403, b"forbidden", "text/plain")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, b"too large", "text/plain")
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, TypeError):
                return self._send(400, b"bad request", "text/plain")
            conn = db.connect(db_path)
            try:
                if self.path == "/api/state":
                    key, value = str(body.get("k", "")), body.get("v")
                    ok = uistate.delete(conn, key) if value is None else uistate.put(conn, key, value)
                    if ok and key == "dsa-done":
                        uistate.sync_tasks_from_state(conn)            # the bot sees page ticks at once
                elif self.path == "/api/tick":
                    ok = calendar_view.apply_tick(conn, str(body.get("id", "")), bool(body.get("done")))
                elif self.path == "/api/decide":
                    ok = calendar_view.apply_decision(conn, str(body.get("id", "")), str(body.get("action", "")))
                else:
                    return self._send(404, b"not found", "text/plain")
            finally:
                conn.close()
            self._send(200 if ok else 400, b'{"ok": true}' if ok else b'{"ok": false}', "application/json")

    return Handler


def start(db_path: str, tz_name: str, port: int = 8765, private_dir: str = "") -> ThreadingHTTPServer:
    """Start serving on 127.0.0.1 in a background thread and return the server (call .shutdown() to stop)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path, tz_name, private_dir))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
