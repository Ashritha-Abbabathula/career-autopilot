"""The running bot: pick up new Telegram messages, run due jobs, send what the outbox allows.

poll_once and tick take everything they need as arguments, so tests drive them with a fake
clock, fake http and fake sender.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import clock as clk
from . import calendar_view, db, digest, facts as facts_mod, replan, github, leetcode, linkedin, mentor, nudges, outreach, outbox, planner, scheduler, scorecard, telegram, tracker
from .chat import step

BUILDERS = {}          # extra jobs (for example the weekly scorecard) register a text builder here
BUILT_IN = ("rollover", "tracker_sync", "digest", "calendar_refresh", "mentor", "linkedin_draft", "outreach_queue",
            "scorecard", "morning_card", "checkin", "streak_nudge", "streak_last_call")
QUIET_JOBS = ("rollover", "tracker_sync", "calendar_refresh")     # never message her
FOCUS_ALLOWED = ("morning_card", "checkin")                      # the only messages that survive focus mode
EXAM_WEEK_CAP = 5


def build_job_text(name, conn, http, cfg, now, today, app=None):
    """Text for a due job, or None when there is nothing worth saying."""
    if name == "rollover":
        replan.rollover(conn, today, now)
        return None
    if name == "tracker_sync":
        if cfg.private_dir:
            out = Path(cfg.output_dir or cfg.private_dir)
            tracker.sync_csv(conn, Path(cfg.private_dir) / "tracker" / "applications.csv", out / "tracker" / "applications.csv")
        return None
    if name == "digest":
        if not digest.is_fresh(cfg.private_dir, today):
            return None                                       # the scout has not written today's yet: send nothing stale
        return digest.build_digest(conn, cfg.private_dir, today)
    if name == "morning_card":
        return planner.morning_card(conn, today)
    if name == "checkin":
        return nudges.checkin(conn, today)
    if name in ("streak_nudge", "streak_last_call"):
        lc = leetcode.fetch_stats(http, cfg.leetcode_user, now)
        gh = github.fetch_stats(http, cfg.github_user, now)
        return nudges.streak_hint(conn, today, lc, gh)
    if name == "scorecard":
        lc = leetcode.fetch_stats(http, cfg.leetcode_user, now)
        return scorecard.build(conn, today, lc.solved_total if lc else None, scorecard.outreach_sent(Path(cfg.private_dir)))
    if name == "calendar_refresh":
        calendar_view.write(conn, Path(cfg.output_dir or cfg.private_dir) / "calendar" / "live_calendar.html", today)
        return None                                       # silent: just keep the page fresh
    if name == "mentor":
        lc = leetcode.fetch_stats(http, cfg.leetcode_user, now)
        return mentor.weekly_note(conn, today, lc.solved_total if lc else None, scorecard.outreach_sent(Path(cfg.private_dir)))
    private = Path(cfg.private_dir)
    if name in ("linkedin_draft", "outreach_queue"):
        try:
            data = facts_mod.load(private / "facts" / "facts.json")
        except facts_mod.FactError:
            return None                                   # no facts file yet: nothing honest to write
        if name == "linkedin_draft":
            return linkedin.job(conn, app.model, data, private / "linkedin" / "schedule.json",
                                Path(cfg.output_dir or cfg.private_dir) / "linkedin" / "drafts", today)
        targets = outreach.select_targets(private / "tracker" / "outreach_targets.csv", 3, outreach.already_drafted(conn))
        queued = 0
        for t in targets:
            try:
                outreach.queue_draft(conn, t, data, now=now)
                queued += 1
            except (outreach.DraftError, facts_mod.FactError):
                continue
        return f"{queued} professor email draft{'s' if queued != 1 else ''} ready for you. Send 'inbox' to read them." if queued else None
    fn = BUILDERS.get(name)
    return fn(conn, http, cfg, now, today) if fn else None


def tick(app, sender, http, cfg, clock) -> list:
    """Queue every due job, then let the outbox send what the rules allow. Returns the job names handled."""
    now = clock.now()
    local = clk.local_now(clock, cfg.timezone)
    handled = []
    focus = db.focus_active(app.conn, now)
    for name in scheduler.due_jobs(local, scheduler.load_done(app.conn, db)):
        if name not in BUILT_IN and name not in BUILDERS:
            continue
        if focus and name not in QUIET_JOBS and name not in FOCUS_ALLOWED:
            scheduler.mark_done(app.conn, db, name, local)        # focus mode: skipped, not queued for later
            continue
        try:
            text = build_job_text(name, app.conn, http, cfg, now, local.date(), app)
        except Exception as exc:                                  # one broken job must not stop the others
            print(f"warning: job {name} failed ({type(exc).__name__})", file=sys.stderr)
            text = None
        if text:
            outbox.enqueue(app.conn, app.owner, text, "proactive", now=now)
        scheduler.mark_done(app.conn, db, name, local)
        handled.append(name)
    cap = cfg.daily_proactive_cap
    if local.date() <= mentor.EXAMS_END:
        cap = min(cap, EXAM_WEEK_CAP)                             # exam mode: about five a day at most
    outbox.flush(app.conn, sender, now, tz_name=cfg.timezone, quiet_start=cfg.quiet_start, quiet_end=cfg.quiet_end,
                 daily_proactive_cap=cap, window_required=False)
    return handled


def send_attachments(app, sender) -> None:
    """Send any files a command produced (the calendar page). A failure is dropped quietly: the text reply already went."""
    files, app.attachments = app.attachments, []
    if not hasattr(sender, "send_document"):
        return
    for filename, content, caption in files:
        try:
            sender.send_document(filename, content, caption)
        except Exception as exc:
            print(f"warning: could not send {filename} ({type(exc).__name__})", file=sys.stderr)


def pull_notes(private_dir, run=None) -> bool:
    """On a server: bring in what the scout and you pushed to the notes repo. Fast-forward only, so it never
    rewrites anything; returns True if git ran cleanly."""
    import subprocess
    run = run or subprocess.run
    root = Path(private_dir)
    while root != root.parent and not (root / ".git").exists():
        root = root.parent                              # the private folder sits inside the notes repo
    if not (root / ".git").exists():
        return False
    try:
        result = run(["git", "-C", str(root), "pull", "--ff-only", "--quiet"], capture_output=True, timeout=90)
        return result.returncode == 0
    except Exception:
        return False


def poll_once(app, sender, http, cfg, clock, wait: int = 25) -> int:
    """Fetch new messages and answer the owner's. Anyone else is ignored and never stored."""
    offset = db.get_setting(app.conn, "tg_offset")
    ok, updates = telegram.get_updates(http, cfg.telegram_bot_token, int(offset) if offset else None, wait)
    if not ok:
        return 0
    answered = 0
    for update_id, chat_id, text in updates:
        db.set_setting(app.conn, "tg_offset", str(update_id + 1))      # advance first: never answer twice
        if chat_id != cfg.telegram_owner_chat_id or not text:
            continue
        step(app, sender, clock, text, channel="telegram", window_required=False,
             tz_name=cfg.timezone, quiet_start=cfg.quiet_start, quiet_end=cfg.quiet_end)
        send_attachments(app, sender)
        answered += 1
    return answered


def bootstrap(app, cfg) -> list:
    """First run: load her plan and tracker from the private folder if they are there and not loaded yet."""
    notes = []
    private = Path(cfg.private_dir)
    plan, settings = private / "calendar" / "plan_data.json", private / "calendar" / "plan_settings.json"
    needs = db.get_setting(app.conn, "plan_imported") != "1"
    outdated = not needs and db.get_setting(app.conn, "plan_schema") != str(db.SCHEMA_VERSION)   # imported before links and progress were stored
    if (needs or outdated) and plan.is_file() and settings.is_file():
        counts = planner.import_from_files(app.conn, plan, settings, force=outdated)
        notes.append(f"plan imported ({counts['dsa']} LeetCode, {counts['gate']} GATE, {counts['youtube']} YouTube items)")
    csv_path = private / "tracker" / "applications.csv"
    if not tracker.list_apps(app.conn) and csv_path.is_file():
        result = tracker.import_csv(app.conn, csv_path)
        notes.append(f"tracker imported ({result['added']} rows)")
    return notes
