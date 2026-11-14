import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import calendar_view, db, github, leetcode, planner, runtime
from ca.chat import build_app, step
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.senders import FakeSender
from tests.test_calendar_view import PLAN_WITH_LINKS, SETTINGS_WITH_ITEMS, data_of


def ts(y, m, d, h=1):
    return str(int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp()))


def lc_calendar(days: dict):
    return {"data": {"matchedUser": {"userCalendar": {"streak": 2, "submissionCalendar": json.dumps(days)},
                                     "submitStats": {"acSubmissionNum": [{"difficulty": "All", "count": 81}]}}}}


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    planner.import_plan(conn, PLAN_WITH_LINKS, SETTINGS_WITH_ITEMS)
    return conn


class FetchTests(unittest.TestCase):
    def test_leetcode_history_groups_by_day(self):
        http = FakeHttp().add(200, lc_calendar({ts(2026, 10, 5, 1): 2, ts(2026, 10, 5, 20): 1, ts(2026, 10, 6): 4}))
        self.assertEqual(leetcode.fetch_history(http, "someone"), {"2026-10-05": 3, "2026-10-06": 4})

    def test_leetcode_history_failures(self):
        self.assertIsNone(leetcode.fetch_history(FakeHttp().add(500, "x"), "u"))
        self.assertIsNone(leetcode.fetch_history(FakeHttp().add(200, "nope"), "u"))
        self.assertIsNone(leetcode.fetch_history(FakeHttp(), ""))

    def test_github_history_counts_commits_on_push_days(self):
        events = [{"type": "PushEvent", "created_at": "2026-10-20T05:00:00Z", "payload": {"commits": [{}, {}]}},
                  {"type": "PushEvent", "created_at": "2026-10-20T09:00:00Z", "payload": {"commits": [{}]}},
                  {"type": "WatchEvent", "created_at": "2026-10-21T09:00:00Z", "payload": {}}]
        self.assertEqual(github.fetch_history(FakeHttp().add(200, events), "u"), {"2026-10-20": 3})
        self.assertIsNone(github.fetch_history(FakeHttp().add(403, "limit"), "u"))


class CalendarTests(unittest.TestCase):
    def test_earlier_months_and_past_days_are_shown(self):
        conn = loaded()
        calendar_view.save_history(conn, {"2026-09-12": 3, "2026-11-10": 1}, {"2026-11-09": 5})
        today = date(2026, 11, 18)
        start, end = calendar_view.span(conn, today)
        self.assertEqual(start, date(2026, 9, 1))                              # starts at the first day of recorded activity's month
        d = data_of(calendar_view.render(conn, today, start, end))
        titles = {i["title"] for i in d["byDate"]["2026-09-12"]}
        self.assertEqual(titles, {"LeetCode: 3 submissions"})
        self.assertEqual(d["byDate"]["2026-11-10"][0]["title"], "LeetCode: 1 submission")
        self.assertEqual(d["byDate"]["2026-11-09"][0]["title"], "GitHub: 5 commits")
        self.assertTrue(all(i["done"] and i["stream"] == "hist" for i in d["byDate"]["2026-11-09"]))

    def test_no_history_keeps_the_original_range(self):
        conn = loaded()
        self.assertEqual(calendar_view.span(conn, date(2026, 11, 18))[0], date(2026, 11, 14))

    def test_failed_reads_keep_what_was_saved(self):
        conn = loaded()
        calendar_view.save_history(conn, {"2026-10-01": 2}, None)
        calendar_view.save_history(conn, None, None)
        calendar_view.save_history(conn, {"2026-10-02": 1}, {})
        self.assertEqual(calendar_view.load_history(conn), {"leetcode": {"2026-10-01": 2, "2026-10-02": 1}})

    def test_future_days_never_get_history(self):
        conn = loaded()
        calendar_view.save_history(conn, {"2026-12-25": 9}, None)
        d = data_of(calendar_view.render(conn, date(2026, 11, 18), date(2026, 11, 14), date(2027, 1, 1)))
        self.assertNotIn("2026-12-25", d["byDate"])

    def test_history_does_not_change_the_progress_bars(self):
        conn = loaded()
        calendar_view.save_history(conn, {"2026-10-01": 50}, None)
        d = data_of(calendar_view.render(conn, date(2026, 11, 18), date(2026, 10, 1), date(2026, 11, 20)))
        self.assertEqual(d["base"]["dsa"], 2)                                  # only the plan's own base counts, never raw submissions


class JobTests(unittest.TestCase):
    def test_daily_history_job_is_silent_and_saved(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        cfg = load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "LEETCODE_USER": "u",
                              "GITHUB_USER": "g", "CA_PRIVATE_DIR": "does/not/exist"}, env_file=None)
        http = FakeHttp().add(200, lc_calendar({ts(2026, 10, 5): 2})).add(200, [])
        sender = FakeSender()
        clock = FakeClock(datetime(2026, 11, 18, 5, 45, tzinfo=IST).astimezone(timezone.utc))
        self.assertIn("history_sync", runtime.tick(app, sender, http, cfg, clock))
        self.assertEqual(sender.sent, [])
        self.assertEqual(calendar_view.load_history(conn)["leetcode"], {"2026-10-05": 2})

    def test_calendar_command_refreshes_history_first(self):
        conn = loaded()
        app = build_app(conn)
        app.http = FakeHttp().add(200, lc_calendar({ts(2026, 10, 5): 2})).add(200, [])
        app.leetcode_user, app.github_user = "u", "g"
        with tempfile.TemporaryDirectory() as tmp:
            app.private_dir = app.output_dir = tmp
            step(app, FakeSender(), FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc)), "calendar")
            html = (Path(tmp) / "calendar" / "live_calendar.html").read_text(encoding="utf-8")
        self.assertIn("LeetCode: 2 submissions", html)


if __name__ == "__main__":
    unittest.main()
