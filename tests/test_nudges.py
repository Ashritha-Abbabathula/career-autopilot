import json
import unittest
from datetime import date, datetime, timezone

from ca import db, github, leetcode, nudges, planner, scheduler
from ca.github import GitHubStats
from ca.http import FakeHttp
from ca.leetcode import LeetCodeStats
from tests.test_planner import PLAN, SETTINGS

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
D = date(2026, 11, 18)
IST = timezone.utc  # only the clock hour matters for scheduler tests


def at(h, m=0, day=18):
    return datetime(2026, 11, day, h, m)


class SchedulerTests(unittest.TestCase):
    def test_morning_card_window(self):
        self.assertEqual(scheduler.due_jobs(at(7, 29), {}), [])
        self.assertEqual(scheduler.due_jobs(at(7, 30), {}), ["morning_card"])
        self.assertEqual(scheduler.due_jobs(at(11, 29), {}), ["morning_card"])
        self.assertEqual(scheduler.due_jobs(at(11, 30), {}), [])           # too late: laptop woke at lunchtime

    def test_once_per_day(self):
        self.assertEqual(scheduler.due_jobs(at(8), {"morning_card": "2026-11-18"}), [])
        self.assertEqual(scheduler.due_jobs(at(8), {"morning_card": "2026-11-17"}), ["morning_card"])

    def test_evening_jobs_and_sunday_scorecard(self):
        self.assertEqual(scheduler.due_jobs(at(20, 5), {}), ["streak_nudge"])
        self.assertEqual(scheduler.due_jobs(at(21, 0), {"streak_nudge": "2026-11-18"}), ["checkin"])
        self.assertEqual(scheduler.due_jobs(at(22, 10), {"checkin": "2026-11-18"}), ["streak_last_call"])
        self.assertEqual(scheduler.due_jobs(at(18, 30, day=22), {}), ["scorecard"])   # a Sunday
        self.assertEqual(scheduler.due_jobs(at(18, 30, day=18), {}), [])             # a Wednesday

    def test_state_round_trip(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        scheduler.mark_done(conn, db, "checkin", at(21))
        self.assertEqual(scheduler.load_done(conn, db)["checkin"], "2026-11-18")
        self.assertEqual(scheduler.load_done(conn, db)["morning_card"], "")


def lc_reply(total=120, streak=3, today_count=0):
    cal = {str(int(NOW.replace(hour=1).timestamp())): today_count, "86400": 5} if today_count else {"86400": 5}
    return {"data": {"matchedUser": {
        "submitStats": {"acSubmissionNum": [{"difficulty": "All", "count": total}, {"difficulty": "Easy", "count": 50}]},
        "userCalendar": {"streak": streak, "submissionCalendar": json.dumps(cal)}}}}


class StatsTests(unittest.TestCase):
    def test_leetcode(self):
        http = FakeHttp().add(200, lc_reply(today_count=2))
        stats = leetcode.fetch_stats(http, "someone", NOW)
        self.assertEqual(stats, LeetCodeStats(120, 2, 3))
        self.assertEqual(http.calls[0]["body"]["variables"], {"u": "someone"})
        self.assertEqual(leetcode.fetch_stats(FakeHttp().add(200, lc_reply()), "x", NOW).solved_today, 0)

    def test_leetcode_failures_return_none(self):
        self.assertIsNone(leetcode.fetch_stats(FakeHttp().add(500, "x"), "u", NOW))
        self.assertIsNone(leetcode.fetch_stats(FakeHttp().add(200, "not json"), "u", NOW))
        self.assertIsNone(leetcode.fetch_stats(FakeHttp().add(200, {"data": {"matchedUser": None}}), "u", NOW))
        self.assertIsNone(leetcode.fetch_stats(FakeHttp(), "u", NOW))          # network down
        self.assertIsNone(leetcode.fetch_stats(FakeHttp(), "", NOW))

    def test_github(self):
        events = [
            {"type": "PushEvent", "created_at": "2026-11-18T05:00:00Z", "payload": {"commits": [{}, {}]}},
            {"type": "PushEvent", "created_at": "2026-11-17T23:00:00Z", "payload": {"commits": [{}]}},
            {"type": "WatchEvent", "created_at": "2026-11-18T06:00:00Z", "payload": {}},
        ]
        self.assertEqual(github.fetch_stats(FakeHttp().add(200, events), "u", NOW), GitHubStats(1, 2))
        self.assertIsNone(github.fetch_stats(FakeHttp().add(403, "rate limited"), "u", NOW))
        self.assertIsNone(github.fetch_stats(FakeHttp().add(200, "[oops"), "u", NOW))


class NudgeTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_schema(self.conn)
        planner.import_plan(self.conn, PLAN, SETTINGS)

    def test_nothing_to_say_when_a_problem_is_done(self):
        self.assertIsNone(nudges.streak_hint(self.conn, D, LeetCodeStats(100, 1, 4), GitHubStats(0, 0)))

    def test_reminds_with_todays_real_problem(self):
        text = nudges.streak_hint(self.conn, D, LeetCodeStats(100, 0, 4), GitHubStats(0, 0))
        self.assertIn("No LeetCode problem yet today (streak 4)", text)
        self.assertIn("LeetCode 7: Problem 7", text)
        self.assertIn("Push only work that is real", text)

    def test_unreadable_sites_are_admitted(self):
        text = nudges.streak_hint(self.conn, D, None, None)
        self.assertIn("could not check LeetCode", text)
        self.assertNotIn("GitHub", text)

    def test_checkin(self):
        text = nudges.checkin(self.conn, D)
        self.assertIn("6 things not done (6h 10m)", text)
        self.assertIn("- GATE Algebra: Lec 1", text)
        self.conn.execute("UPDATE tasks SET status='done'")
        self.assertIn("everything planned for today is done", nudges.checkin(self.conn, D))


if __name__ == "__main__":
    unittest.main()
