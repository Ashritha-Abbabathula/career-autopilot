"""A scripted day through the whole assistant with fakes: the v1 definition of done."""
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import approvals, db, outreach, runtime, tracker
from ca.approvals import Executors
from ca.chat import build_app, step
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.llm import FakeModel
from ca.senders import FakeSender
from tests.test_nudges import lc_reply
from tests.test_outreach import DATA as FACTS, SPACE
from tests.test_planner import PLAN, SETTINGS


class ScriptedDay(unittest.TestCase):
    def test_a_day(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calendar").mkdir()
            (root / "calendar" / "plan_data.json").write_text(json.dumps(PLAN), encoding="utf-8")
            (root / "calendar" / "plan_settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
            cfg = load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "LEETCODE_USER": "someone",
                                   "CA_PRIVATE_DIR": str(root)}, env_file=None)
            app = build_app(conn, owner="555")
            app.private_dir = str(root)
            app.executors = Executors(run={"email_draft": outreach.make_executor(root / "drafts", lambda: date(2026, 11, 18))})
            app.model = FakeModel([json.dumps({"decision": "APPLY", "reason": "Open and fits.", "organisation": "Example Academy",
                                               "role": "Fellow", "location": "Bengaluru", "deadline": "2026-11-30"})])
            sender = FakeSender()
            runtime.bootstrap(app, cfg)

            # 07:45 IST on a Wednesday: the morning card goes out once
            clock = FakeClock(datetime(2026, 11, 18, 7, 45, tzinfo=IST).astimezone(timezone.utc))
            self.assertEqual(runtime.tick(app, sender, FakeHttp(), cfg, clock), ["morning_card"])
            self.assertIn("Good morning", sender.sent[-1][2])

            say = lambda text: step(app, sender, clock, text)
            self.assertIn("Today, 18 Nov", say("today"))
            self.assertIn("Moved to Thu 19 Nov", say("push gate to tomorrow"))
            self.assertIn("Undone", say("undo"))
            self.assertIn("Saved to your tracker", say("https://example.org/fellowship"))
            self.assertIn("Example Academy", say("apps"))

            # an email draft waits for her words and her yes, and is saved, never sent
            a = outreach.queue_draft(conn, SPACE, FACTS)
            self.assertIn("Draft email", say("inbox"))
            self.assertIn("placeholder", say(f"yes {a}"))
            self.assertIn("Updated item", say(f"edit {a} Dear Professor Mayank, the finished text."))
            self.assertIn("Saved as", say(f"yes {a}"))
            self.assertEqual(len(list((root / "drafts" / "ready").glob("*.txt"))), 1)

            # pause blocks what the bot starts on its own, but it still answers her
            self.assertIn("Paused", say("pause"))
            clock.set(datetime(2026, 11, 18, 21, 5, tzinfo=IST).astimezone(timezone.utc))
            before = len(sender.sent)
            runtime.tick(app, sender, FakeHttp(), cfg, clock)
            self.assertEqual(len(sender.sent), before)
            self.assertIn("Resumed", say("resume"))

            # Sunday scorecard
            clock.set(datetime(2026, 11, 22, 18, 30, tzinfo=IST).astimezone(timezone.utc))
            runtime.tick(app, sender, FakeHttp().add(200, lc_reply(total=100)), cfg, clock)
            self.assertIn("Scorecard", sender.sent[-1][2])
            self.assertEqual(len(tracker.list_apps(conn)) >= 1, True)


if __name__ == "__main__":
    unittest.main()
