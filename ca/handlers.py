"""Command handlers that are registered on the App. Each takes (app, command, now) and returns text."""
from __future__ import annotations

from datetime import datetime

from . import clock as clk
from . import deadlines, tracker


def local_date(app, now: datetime):
    return now.astimezone(clk.tzinfo_for(app.tz_name)).date()


def apps(app, cmd, now: datetime) -> str:
    today = local_date(app, now)
    return tracker.summary_text(app.conn) + "\n\nDue soon:\n" + deadlines.text(app.conn, today)


def register_all(app) -> None:
    app.register("apps", apps)
