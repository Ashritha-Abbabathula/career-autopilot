import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ca import db, runtime, telegram
from ca.app import App
from ca.config import load_config
from ca.chat import build_app
from ca.clock import FakeClock
from ca.http import FakeHttp
from ca.senders import FakeSender
from ca.telegram import TelegramError, TelegramSender
from tests.test_planner import PLAN, SETTINGS

TOKEN, OWNER = "123:fake-test-token", "555"


def cfg(**extra):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_OWNER_CHAT_ID": OWNER, "TIMEZONE": "Asia/Kolkata"}
    env.update(extra)
    return load_config(env=env, env_file=None)


def updates(*items):
    return {"ok": True, "result": [
        {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}} if text is not None
        else {"update_id": uid, "message": {"chat": {"id": chat}, "sticker": {}}}
        for uid, chat, text in items]}


class SenderTests(unittest.TestCase):
    def test_sends_to_the_owner_chat_only(self):
        http = FakeHttp().add(200, {"ok": True})
        TelegramSender(http, TOKEN, OWNER).send_text("someone-else", "hello")
        call = http.calls[0]
        self.assertTrue(call["url"].endswith("/sendMessage"))
        self.assertEqual(call["body"]["chat_id"], OWNER)

    def test_error_never_contains_the_token(self):
        http = FakeHttp().add(401, "unauthorized")
        with self.assertRaises(TelegramError) as ctx:
            TelegramSender(http, TOKEN, OWNER).send_text("x", "hello")
        self.assertNotIn(TOKEN, str(ctx.exception))
        with self.assertRaises(ValueError):
            TelegramSender(http, "", OWNER)

    def test_long_messages_are_split_on_lines(self):
        text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))      # about 9,500 characters
        parts = telegram.split_text(text)
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(p) <= telegram.LIMIT for p in parts))
        self.assertEqual("\n".join(parts).replace("\n", ""), text.replace("\n", ""))
        self.assertEqual(telegram.split_text("short"), ["short"])


class PollTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_schema(self.conn)
        self.app = build_app(self.conn, owner=OWNER)
        self.clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
        self.sender = FakeSender()

    def poll(self, http):
        return runtime.poll_once(self.app, self.sender, http, cfg(), self.clock)

    def test_owner_is_answered_and_strangers_are_ignored_and_not_stored(self):
        http = FakeHttp().add(200, updates((10, OWNER, "help"), (11, "999", "hi bot"), (12, OWNER, None)))
        self.assertEqual(self.poll(http), 1)
        self.assertEqual(len(self.sender.sent), 1)
        bodies = [r["body"] for r in self.conn.execute("SELECT body FROM messages WHERE direction='in'")]
        self.assertEqual(bodies, ["help"])                                  # the stranger's text was never stored
        self.assertEqual(db.get_setting(self.conn, "tg_offset"), "13")

    def test_offset_is_sent_next_time_so_nothing_repeats(self):
        self.poll(FakeHttp().add(200, updates((10, OWNER, "help"))))
        http = FakeHttp().add(200, updates())
        self.poll(http)
        self.assertEqual(http.calls[0]["body"]["offset"], 11)

    def test_failures_do_nothing(self):
        for reply in ((500, "x"), (200, "not json"), (200, {"ok": False}), (0, "")):
            self.assertEqual(self.poll(FakeHttp().add(*reply)), 0)
        self.assertIsNone(db.get_setting(self.conn, "tg_offset"))

    def test_paused_still_answers_the_owner(self):
        db.set_paused(self.conn, True)
        self.assertEqual(self.poll(FakeHttp().add(200, updates((1, OWNER, "help")))), 1)
        self.assertEqual(len(self.sender.sent), 1)


class TickTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_schema(self.conn)
        self.app = build_app(self.conn, owner=OWNER)
        from ca import planner
        planner.import_plan(self.conn, PLAN, SETTINGS)
        self.sender = FakeSender()

    def clock_at_ist(self, hour, minute=0):
        from ca.clock import IST
        return FakeClock(datetime(2026, 11, 18, hour, minute, tzinfo=IST).astimezone(timezone.utc))

    def test_morning_card_is_sent_once(self):
        clock = self.clock_at_ist(7, 45)
        self.assertIn("morning_card", runtime.tick(self.app, self.sender, FakeHttp(), cfg(), clock))
        self.assertEqual(len(self.sender.sent), 1)
        self.assertIn("Good morning", self.sender.sent[0][2])
        self.assertNotIn("morning_card", runtime.tick(self.app, self.sender, FakeHttp(), cfg(), clock))
        self.assertEqual(len(self.sender.sent), 1)

    def test_paused_blocks_the_morning_card_and_it_is_not_retried(self):
        db.set_paused(self.conn, True)
        runtime.tick(self.app, self.sender, FakeHttp(), cfg(), self.clock_at_ist(7, 45))
        self.assertEqual(self.sender.sent, [])
        status = self.conn.execute("SELECT status FROM outbox").fetchone()["status"]
        self.assertEqual(status, "blocked_paused")

    def test_streak_nudge_only_when_nothing_done_and_site_unreadable_is_admitted(self):
        c = cfg(LEETCODE_USER="someone", GITHUB_USER="someone")
        http = FakeHttp().add(0, "").add(0, "")                              # both sites unreachable
        runtime.tick(self.app, self.sender, http, c, self.clock_at_ist(20, 5))
        self.assertIn("could not check LeetCode", self.sender.sent[0][2])

    def test_outside_a_job_window_nothing_happens(self):
        handled = runtime.tick(self.app, self.sender, FakeHttp(), cfg(), self.clock_at_ist(14, 0))
        self.assertTrue(set(handled) <= {"rollover", "tracker_sync", "calendar_refresh", "digest"})   # only silent jobs, no message
        self.assertEqual(self.sender.sent, [])


class BootstrapTests(unittest.TestCase):
    def test_loads_private_files_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calendar").mkdir()
            (root / "tracker").mkdir()
            (root / "calendar" / "plan_data.json").write_text(json.dumps(PLAN), encoding="utf-8")
            (root / "calendar" / "plan_settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
            (root / "tracker" / "applications.csv").write_text(
                (Path(__file__).parent / "fixtures" / "applications.csv").read_text(encoding="utf-8"), encoding="utf-8")
            conn = db.connect(":memory:")
            db.init_schema(conn)
            app = build_app(conn)
            c = cfg(CA_PRIVATE_DIR=str(root))
            notes = runtime.bootstrap(app, c)
            self.assertEqual(len(notes), 2)
            self.assertEqual(runtime.bootstrap(app, c), [])                 # second start changes nothing

    def test_missing_files_are_fine(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        self.assertEqual(runtime.bootstrap(build_app(conn), cfg(CA_PRIVATE_DIR="does/not/exist")), [])


if __name__ == "__main__":
    unittest.main()
