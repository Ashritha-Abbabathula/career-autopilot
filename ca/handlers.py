"""Command handlers that are registered on the App. Each takes (app, command, now) and returns text."""
from __future__ import annotations

from datetime import datetime

from . import clock as clk
from . import approvals, deadlines, planner, replan, tracker


def local_date(app, now: datetime):
    return now.astimezone(clk.tzinfo_for(app.tz_name)).date()


def apps(app, cmd, now: datetime) -> str:
    today = local_date(app, now)
    return tracker.summary_text(app.conn) + "\n\nDue soon:\n" + deadlines.text(app.conn, today)


def today(app, cmd, now: datetime) -> str:
    return planner.day_text(app.conn, local_date(app, now))


def week(app, cmd, now: datetime) -> str:
    return planner.week_text(app.conn, local_date(app, now))


def _guard(fn):
    def wrapped(app, cmd, now):
        try:
            return fn(app, cmd, now)
        except replan.ReplanError as exc:
            return str(exc)
    return wrapped


@_guard
def done(app, cmd, now: datetime) -> str:
    return replan.done(app.conn, cmd.args["task"], local_date(app, now), now)


@_guard
def skip_task(app, cmd, now: datetime) -> str:
    return replan.skip(app.conn, cmd.args["task"], local_date(app, now), now)


@_guard
def push(app, cmd, now: datetime) -> str:
    return replan.push(app.conn, cmd.args["task"], cmd.args["to"], local_date(app, now), now)


@_guard
def free(app, cmd, now: datetime) -> str:
    return replan.free_hours(app.conn, cmd.args["hours"], local_date(app, now), now)


def undo(app, cmd, now: datetime) -> str:
    """Undo whichever happened last: a plan change or an approved item."""
    change = replan.last_change(app.conn)
    approved = approvals.last_approved(app.conn)
    if change is not None and (approved is None or change["ts"] >= (approved["decided_at"] or "")):
        return replan.undo_last(app.conn)
    return app._undo(now)


def register_all(app) -> None:
    app.register("done", done)
    app.register("skip_task", skip_task)
    app.register("push", push)
    app.register("free", free)
    app.register("undo", undo)
    app.register("apps", apps)
    app.register("today", today)
    app.register("week", week)
