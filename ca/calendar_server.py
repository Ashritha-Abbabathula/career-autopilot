"""A tiny web page for the calendar, served only to this computer (127.0.0.1).

GET /            the live calendar, built fresh from the database on every visit
POST /api/tick   {"id": "t12", "done": true}           tick or untick a planned task
POST /api/decide {"id": "t40", "action": "approve"}    approve, skip or later on an assistant item
Nothing is reachable from outside this machine, and posts without the page's own header are refused.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import calendar_view, db
from . import clock as clk

LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def make_handler(db_path: str, tz_name: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                       # keep the console quiet and free of request details
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0] if not (self.headers.get("Host") or "").startswith("[") \
                else (self.headers.get("Host") or "").split("]")[0] + "]"
            return host in LOCAL_HOSTS                      # blocks DNS-rebinding tricks from other sites

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
                body = json.loads(self.rfile.read(min(length, 4096)) or b"{}")
                item_id = str(body.get("id", ""))
            except (ValueError, TypeError):
                return self._send(400, b"bad request", "text/plain")
            conn = db.connect(db_path)
            try:
                if self.path == "/api/tick":
                    ok = calendar_view.apply_tick(conn, item_id, bool(body.get("done")))
                elif self.path == "/api/decide":
                    ok = calendar_view.apply_decision(conn, item_id, str(body.get("action", "")))
                else:
                    return self._send(404, b"not found", "text/plain")
            finally:
                conn.close()
            self._send(200 if ok else 400, b'{"ok": true}' if ok else b'{"ok": false}', "application/json")

    return Handler


def start(db_path: str, tz_name: str, port: int = 8765) -> ThreadingHTTPServer:
    """Start serving on 127.0.0.1 in a background thread and return the server (call .shutdown() to stop)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path, tz_name))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
