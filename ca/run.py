"""Start the bot:  python -m ca.run

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_ID in .env (python -m ca.check_env shows what is missing).
No public address, tunnel or webhook is needed: the bot asks Telegram for new messages.
Stop with Ctrl+C.
"""
from __future__ import annotations

import sys
import time

from datetime import date
from pathlib import Path

from . import calendar_server, db, handlers, outreach
from .app import App
from .approvals import Executors
from .clock import SystemClock
from .config import load_config
from .http import UrllibHttp
from .llm import GeminiModel, NoModel
from .runtime import bootstrap, poll_once, pull_notes, tick
from .telegram import TelegramSender


ROOT = Path(__file__).resolve().parent.parent


def _absolute(cfg):
    """Make paths independent of where the bot was started from."""
    from dataclasses import replace
    fix = lambda p: p if Path(p).is_absolute() else str((ROOT / p).resolve())
    return replace(cfg, db_path=fix(cfg.db_path), private_dir=fix(cfg.private_dir),
                   output_dir=fix(cfg.output_dir) if cfg.output_dir else "")


def main() -> int:
    cfg = _absolute(load_config(env_file=str(ROOT / ".env")))
    if not cfg.telegram_ready:
        print("Telegram is not set up. Fill TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_ID in .env, "
              "then run: python -m ca.check_env")
        return 1
    conn = db.connect(cfg.db_path)
    db.init_schema(conn)
    http, clock = UrllibHttp(), SystemClock()
    model = (GeminiModel(cfg.gemini_api_key, cfg.gemini_models, http, conn, cfg.model_daily_call_cap)
             if cfg.gemini_ready else NoModel())
    app = App(conn, cfg.telegram_owner_chat_id, tz_name=cfg.timezone, model=model, private_dir=cfg.private_dir, output_dir=cfg.output_dir, http=http,
              leetcode_user=cfg.leetcode_user, github_user=cfg.github_user,
              executors=Executors(run={"email_draft": outreach.make_executor(Path(cfg.output_dir or cfg.private_dir) / "tracker" / "outreach_drafts", date.today)}))
    handlers.register_all(app)
    sender = TelegramSender(http, cfg.telegram_bot_token, cfg.telegram_owner_chat_id)
    if cfg.calendar_port:
        try:
            calendar_server.start(cfg.db_path, cfg.timezone, cfg.calendar_port, cfg.private_dir)
            print(f"Calendar page: http://localhost:{cfg.calendar_port}/ (this computer only)")
        except OSError:
            print("Calendar page could not start (port busy); the saved file still works.")
    for note in bootstrap(app, cfg):
        print(note)
    mode = "with model" if cfg.gemini_ready else "no model key: fixed commands only"
    print(f"Career Autopilot is running (Telegram, {mode}). Ctrl+C to stop.")
    failures = 0
    last_pull = 0.0
    try:
        while True:
            try:
                if cfg.notes_autopull and time.monotonic() - last_pull > 3600:
                    pull_notes(cfg.private_dir)               # hourly: new scout files, plan and tracker edits
                    last_pull = time.monotonic()
                tick(app, sender, http, cfg, clock)
                started = time.monotonic()
                poll_once(app, sender, http, cfg, clock)
                if time.monotonic() - started < 1.0:
                    time.sleep(3)                  # Telegram unreachable or refused: never spin
                failures = 0
            except Exception as exc:               # keep running; log the type only (no secrets)
                failures += 1
                print(f"warning: {type(exc).__name__} (attempt {failures})", file=sys.stderr)
                time.sleep(min(60, 5 * failures))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
