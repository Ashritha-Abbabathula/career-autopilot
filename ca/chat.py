"""Local chat simulator: talk to the assistant in a terminal, no WhatsApp needed.

    python -m ca.chat

Uses the same App and outbox as the real channel, with a console sender.
"""
from __future__ import annotations

from . import db, handlers, outbox
from .app import App
from .clock import SystemClock
from .config import load_config
from .senders import ConsoleSender


def build_app(conn, owner: str = "simulator", tz_name: str = "Asia/Kolkata") -> App:
    app = App(conn, owner, tz_name=tz_name)
    handlers.register_all(app)
    return app


def step(app: App, sender, clock, text: str, channel: str = "simulator", **flush_rules) -> str:
    """One round: message in, reply out through the outbox. Returns the reply text."""
    now = clock.now()
    reply = app.handle(text, now, channel=channel)
    outbox.flush(app.conn, sender, now, **flush_rules)
    return reply


def main() -> None:
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    db.init_schema(conn)
    app = build_app(conn)
    sender, clock = ConsoleSender(), SystemClock()
    print("Career Autopilot simulator. Type 'help'. Ctrl+C to quit.")
    try:
        while True:
            step(app, sender, clock, input("you> "))
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
