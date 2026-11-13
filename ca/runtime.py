"""The running bot: pick up new Telegram messages, run due jobs, send what the outbox allows.

poll_once and tick take everything they need as arguments, so tests drive them with a fake
clock, fake http and fake sender.
"""
from __future__ import annotations

from pathlib import Path

from . import clock as clk
from . import db, facts as facts_mod, github, leetcode, linkedin, mentor, nudges, outreach, outbox, planner, scheduler, scorecard, telegram, tracker
from .chat import step

BUILDERS = {}          # extra jobs (for example the weekly scorecard) register a text builder here
BUILT_IN = ("mentor", "linkedin_draft", "outreach_queue", "scorecard", "morning_card", "checkin", "streak_nudge", "streak_last_call")


def build_job_text(name, conn, http, cfg, now, today, app=None):
    """Text for a due job, or None when there is nothing worth saying."""
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
                                private / "linkedin" / "drafts", today)
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
    for name in scheduler.due_jobs(local, scheduler.load_done(app.conn, db)):
        if name not in BUILT_IN and name not in BUILDERS:
            continue
        text = build_job_text(name, app.conn, http, cfg, now, local.date(), app)
        if text:
            outbox.enqueue(app.conn, app.owner, text, "proactive", now=now)
        scheduler.mark_done(app.conn, db, name, local)
        handled.append(name)
    outbox.flush(app.conn, sender, now, tz_name=cfg.timezone, quiet_start=cfg.quiet_start, quiet_end=cfg.quiet_end,
                 daily_proactive_cap=cfg.daily_proactive_cap, window_required=False)
    return handled


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
        answered += 1
    return answered


def bootstrap(app, cfg) -> list:
    """First run: load her plan and tracker from the private folder if they are there and not loaded yet."""
    notes = []
    private = Path(cfg.private_dir)
    plan, settings = private / "calendar" / "plan_data.json", private / "calendar" / "plan_settings.json"
    if db.get_setting(app.conn, "plan_imported") != "1" and plan.is_file() and settings.is_file():
        counts = planner.import_from_files(app.conn, plan, settings)
        notes.append(f"plan imported ({counts['dsa']} LeetCode, {counts['gate']} GATE, {counts['youtube']} YouTube items)")
    csv_path = private / "tracker" / "applications.csv"
    if not tracker.list_apps(app.conn) and csv_path.is_file():
        result = tracker.import_csv(app.conn, csv_path)
        notes.append(f"tracker imported ({result['added']} rows)")
    return notes
