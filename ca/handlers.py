"""Command handlers that are registered on the App. Each takes (app, command, now) and returns text."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import approvals, calendar_view, db, deadlines, leetcode, planner, replan, tracker
from . import clock as clk
from . import digest as digest_mod
from . import scorecard as scorecard_mod
from . import triage as triage_mod

FOCUS_DAYS = 3


def local_date(app, now: datetime):
    return now.astimezone(clk.tzinfo_for(app.tz_name)).date()


def tracker_csv(app):
    return Path(app.private_dir) / "tracker" / "applications.csv" if app.private_dir else None


def tracker_out(app):
    return Path(app.output_dir) / "tracker" / "applications.csv" if app.output_dir else None


def sync_tracker(app) -> None:
    """Keep the shared CSV (read by the scout, mirrored to your Google Sheet) in step with the bot."""
    path = tracker_csv(app)
    if path is not None:
        try:
            tracker.sync_csv(app.conn, path, tracker_out(app))
        except OSError:
            pass                                          # a locked file must never break a reply


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


def done(app, cmd, now: datetime) -> str:
    """Tick a planned task; if none matches, tick an application's next action instead."""
    try:
        return replan.done(app.conn, cmd.args["task"], local_date(app, now), now)
    except replan.ReplanError as exc:
        words = cmd.args["task"].lower()
        hits = [r for r in tracker.list_apps(app.conn)
                if r["next_action"] and (words in r["next_action"].lower() or words in r["organisation"].lower())]
        if len(hits) == 1:
            r = hits[0]
            tracker.update(app.conn, r["id"], next_action="", next_action_date="")
            sync_tracker(app)
            return f"Done: {r['organisation']}: {r['next_action']}. Cleared from your due list."
        if len(hits) > 1:
            return "More than one next action matches. Say 'done' with more of the words."
        return str(exc)


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


def triage(app, cmd, now: datetime) -> str:
    verdict = triage_mod.triage(app.model, cmd.text, local_date(app, now).isoformat())
    row_id = triage_mod.add_to_tracker(app.conn, verdict, local_date(app, now).isoformat())
    if row_id:
        sync_tracker(app)
    return triage_mod.describe(verdict, row_id)


def applied(app, cmd, now: datetime) -> str:
    """'applied 3' or 'applied to Google': mark a tracker row as applied today."""
    what = cmd.args["what"].strip().rstrip(".")
    rows = tracker.list_apps(app.conn)
    first, _, method = what.partition(" ")
    row = next((r for r in rows if str(r["id"]) == first.lstrip("#")), None)
    if row is not None:
        method = method.strip()
    else:
        hits = [r for r in rows if what.lower() in (r["organisation"] + " " + r["role_or_programme"]).lower()]
        method = ""
        if len(hits) == 1:
            row = hits[0]
        elif len(hits) > 1:
            names = "; ".join(f"{r['id']}. {r['organisation']}: {r['role_or_programme']}" for r in hits[:5])
            return f"More than one match. Say 'applied N' with the number: {names}"
    if row is None:
        return f"I could not find '{what}' in your tracker. Send 'apps' to see the list, or paste the link and I will add it."
    if tracker.is_submitted(row):
        return f"#{row['id']} {row['organisation']} is already marked {row['status']}."
    tracker.mark_applied(app.conn, row["id"], local_date(app, now), method)
    sync_tracker(app)
    count = sum(1 for r in tracker.list_apps(app.conn) if tracker.is_submitted(r))
    return f"Marked applied: {row['organisation']}, {row['role_or_programme']}. That makes {count} applied in total."


def digest(app, cmd, now: datetime) -> str:
    return digest_mod.build_digest(app.conn, app.private_dir, local_date(app, now))


def scorecard(app, cmd, now: datetime) -> str:
    stats = leetcode.fetch_stats(app.http, app.leetcode_user, now) if app.http else None
    sent = scorecard_mod.outreach_sent(Path(app.private_dir)) if app.private_dir else None
    return scorecard_mod.build(app.conn, local_date(app, now), stats.solved_total if stats else None, sent)


def calendar(app, cmd, now: datetime) -> str:
    if not app.private_dir:
        return "I don't know where to save the calendar yet (CA_PRIVATE_DIR is not set)."
    path = calendar_view.write(app.conn, Path(app.output_dir or app.private_dir) / "calendar" / "live_calendar.html", local_date(app, now))
    app.attachments.append(("calendar.html", path.read_bytes(),
                            "Open this file in your browser. Ticks made there stay on your device; tell me 'done <task>' so I know too."))
    head = ("Calendar sent as a file. On the same computer as the bot you can also open http://localhost:8765/ "
            "(ticks there are saved to me).\n\n")
    return head + planner.week_text(app.conn, local_date(app, now))


def focus(app, cmd, now: datetime) -> str:
    """Exam mode: while on, the bot sends only the morning card and the evening check-in."""
    if db.focus_active(app.conn, now):
        db.set_focus(app.conn, None)
        return "Focus mode off. Everything is back to normal."
    db.set_focus(app.conn, now + timedelta(days=FOCUS_DAYS))
    today_ = local_date(app, now)
    tasks = planner.tasks_on(app.conn, today_, include_done=False)
    first = tasks[0]["title"] if tasks else "nothing planned"
    return (f"Focus mode on for {FOCUS_DAYS} days: only the morning card and the evening check-in, nothing else. "
            f"Today's one thing: {first}. Send 'focus' again to turn it off.")


def show(app, cmd, now: datetime) -> str:
    row = approvals.get(app.conn, cmd.number)
    if row is None:
        return f"There is no item {cmd.number}."
    import json
    payload = json.loads(row["payload"])
    if row["kind"] == "email_draft":
        body = payload.get("edited_text") or payload.get("body", "")
        return f"Item {row['id']} ({row['status']}), {payload.get('subject', '')}\n{payload.get('to_note', '')}\n\n{body}"
    return f"Item {row['id']} ({row['status']}): {row['summary']}"


def register_all(app) -> None:
    for kind, fn in (("calendar", calendar), ("scorecard", scorecard), ("digest", digest), ("triage", triage),
                     ("done", done), ("skip_task", skip_task), ("push", push), ("free", free), ("undo", undo),
                     ("apps", apps), ("today", today), ("week", week), ("applied", applied), ("focus", focus),
                     ("show", show)):
        app.register(kind, fn)
