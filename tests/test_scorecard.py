import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import db, runtime, scorecard, tracker
from ca.chat import build_app
from ca.clock import FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.senders import FakeSender
from tests.test_nudges import lc_reply


def fresh():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


class PaceTests(unittest.TestCase):
    def test_straight_line_pace(self):
        self.assertEqual(scorecard.expected_by(scorecard.START, 200, 81), 81)
        self.assertEqual(scorecard.expected_by(scorecard.END, 200, 81), 200)
        mid = scorecard.expected_by(date(2026, 12, 29), 200, 81)
        self.assertAlmostEqual(mid, 140.5, delta=1.5)
        self.assertEqual(scorecard.expected_by(date(2030, 1, 1), 200, 81), 200)       # capped at the end date


class BuildTests(unittest.TestCase):
    def test_behind_and_ahead(self):
        conn = fresh()
        text = scorecard.build(conn, date(2026, 12, 29), lc_total=100, outreach=0)
        self.assertIn("LeetCode solved: 100 (floor 170, target 200, stretch 230)", text)
        self.assertIn("behind the pace", text)
        self.assertIn("Next week: solve", text)
        ahead = scorecard.build(conn, date(2026, 12, 29), lc_total=180, outreach=0)
        self.assertIn("on pace", ahead)

    def test_unreadable_numbers_are_unknown_not_guessed(self):
        text = scorecard.build(fresh(), date(2026, 12, 29), lc_total=None, outreach=None)
        self.assertIn("LeetCode solved: unknown", text)
        self.assertIn("Applications and outreach sent: unknown", text)
        self.assertNotIn("Next week: solve", text)

    def test_applications_count_submitted_rows_and_outreach(self):
        conn = fresh()
        tracker.add(conn, "A", "x", status="applied")
        tracker.add(conn, "B", "y", status="not started")
        text = scorecard.build(conn, date(2026, 12, 29), lc_total=200, outreach=3)
        self.assertIn("Applications and outreach sent: 4", text)

    def test_waiting_items_are_a_move(self):
        from ca import approvals
        conn = fresh()
        approvals.create(conn, "email", "x")
        self.assertIn("answer the 1 item in your inbox", scorecard.build(conn, date(2026, 12, 29), 300, 0))

    def test_outreach_sheet_counts_only_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tracker").mkdir()
            (Path(tmp) / "tracker" / "outreach_targets.csv").write_text(
                "id,name,status\n1,A,sent\n2,B,candidate\n3,C,Emailed\n", encoding="utf-8")
            self.assertEqual(scorecard.outreach_sent(Path(tmp)), 2)
            self.assertIsNone(scorecard.outreach_sent(Path(tmp) / "nowhere"))


class SundayJobTests(unittest.TestCase):
    def test_runtime_sends_it_once_on_sunday(self):
        from ca.clock import IST
        conn = fresh()
        app = build_app(conn, owner="555")
        sender = FakeSender()
        cfg = load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "LEETCODE_USER": "someone",
                               "CA_PRIVATE_DIR": "does/not/exist"}, env_file=None)
        clock = FakeClock(datetime(2026, 11, 22, 18, 30, tzinfo=IST).astimezone(timezone.utc))      # a Sunday
        handled = runtime.tick(app, sender, FakeHttp().add(200, lc_reply(total=120)), cfg, clock)
        self.assertEqual(handled, ["scorecard"])
        self.assertIn("LeetCode solved: 120", sender.sent[0][2])
        self.assertEqual(runtime.tick(app, sender, FakeHttp(), cfg, clock), [])


if __name__ == "__main__":
    unittest.main()
