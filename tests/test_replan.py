import unittest
from datetime import date, datetime, timezone

from ca import approvals, db, planner, replan
from ca.approvals import Executors
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.replan import ReplanError
from ca.senders import FakeSender
from tests.test_planner import PLAN, SETTINGS

D = date.fromisoformat
GATE_DAY = D("2026-11-18")     # 3 LeetCode (30m each), 2 GATE (100m, 60m), 1 YouTube (120m)


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    planner.import_plan(conn, PLAN, SETTINGS)
    return conn


class ParseDayTests(unittest.TestCase):
    def test_words(self):
        sat = D("2026-11-14")
        self.assertEqual(replan.parse_day("Tomorrow", sat), D("2026-11-15"))
        self.assertEqual(replan.parse_day("monday", sat), D("2026-11-16"))
        self.assertEqual(replan.parse_day("sat", sat), D("2026-11-21"))          # never "today" for a weekday name
        self.assertEqual(replan.parse_day("next wed", sat), D("2026-11-18"))
        self.assertEqual(replan.parse_day("in 3 days", sat), D("2026-11-17"))
        self.assertEqual(replan.parse_day("2026-12-01", sat), D("2026-12-01"))
        self.assertIsNone(replan.parse_day("someday", sat))
        self.assertIsNone(replan.parse_day("", sat))


class FindTests(unittest.TestCase):
    def test_kind_word_number_and_title(self):
        conn = loaded()
        self.assertEqual(len(replan.find_tasks(conn, "leetcode", GATE_DAY)), 3)
        self.assertEqual(len(replan.find_tasks(conn, "all", GATE_DAY)), 6)
        self.assertEqual([t["title"] for t in replan.find_tasks(conn, "leetcode 8", GATE_DAY)], ["LeetCode 8: Problem 8"])
        self.assertEqual([t["title"] for t in replan.find_tasks(conn, "lec 1", GATE_DAY)], ["GATE Algebra: Lec 1"])
        self.assertEqual(replan.find_tasks(conn, "nothing like this", GATE_DAY), [])


class ChangeTests(unittest.TestCase):
    def test_done_then_undo(self):
        conn = loaded()
        msg = replan.done(conn, "leetcode", GATE_DAY)
        self.assertIn("Marked done", msg)
        self.assertIn("4h 40m", msg)
        self.assertEqual(planner.study_minutes(conn, GATE_DAY), 280)
        self.assertIn("put 3 items back", replan.undo_last(conn))
        self.assertEqual(planner.study_minutes(conn, GATE_DAY), 370)
        self.assertIsNone(replan.undo_last(conn))                                # nothing left to undo

    def test_done_everything(self):
        conn = loaded()
        self.assertIn("everything for today", replan.done(conn, "all", GATE_DAY))

    def test_push_moves_and_reports_load(self):
        conn = loaded()
        msg = replan.push(conn, "gate", "tomorrow", GATE_DAY)
        self.assertIn("Moved to Thu 19 Nov", msg)
        self.assertEqual(len([t for t in planner.tasks_on(conn, GATE_DAY) if t["kind"] == "gate"]), 0)
        self.assertEqual(len([t for t in planner.tasks_on(conn, D("2026-11-19")) if t["kind"] == "gate"]), 3)
        replan.undo_last(conn)
        self.assertEqual(len([t for t in planner.tasks_on(conn, GATE_DAY) if t["kind"] == "gate"]), 2)

    def test_push_refusals(self):
        conn = loaded()
        with self.assertRaises(ReplanError):
            replan.push(conn, "gate", "someday", GATE_DAY)
        with self.assertRaises(ReplanError):
            replan.push(conn, "gate", "today", GATE_DAY)
        with self.assertRaises(ReplanError):
            replan.push(conn, "unicorn", "tomorrow", GATE_DAY)
        with self.assertRaises(ReplanError) as ctx:                              # exam preparation is fixed
            replan.push(conn, "maths preparation", "tomorrow", D("2026-11-15"))
        self.assertIn("fixed", str(ctx.exception))

    def test_free_hours_keeps_priority_and_moves_rest(self):
        conn = loaded()
        msg = replan.free_hours(conn, 3, GATE_DAY)                               # 180 minutes
        kept = [t["title"] for t in planner.tasks_on(conn, GATE_DAY)]
        self.assertEqual(kept, ["LeetCode 7: Problem 7", "LeetCode 8: Problem 8", "LeetCode 9: Problem 9", "GATE Algebra: Lec 2"])
        self.assertIn("Moved to tomorrow", msg)
        self.assertIn("I kept 2h 30m", msg)
        replan.undo_last(conn)
        self.assertEqual(len(planner.tasks_on(conn, GATE_DAY)), 6)

    def test_free_hours_edges(self):
        conn = loaded()
        self.assertIn("Everything left fits", replan.free_hours(conn, 10, GATE_DAY))
        self.assertIn("no study left", replan.free_hours(conn, 2, D("2027-01-01")))
        self.assertIn("today is clear", replan.free_hours(conn, 0.25, GATE_DAY))

    def test_skip(self):
        conn = loaded()
        replan.skip(conn, "youtube", GATE_DAY)
        self.assertIn("[-] Video set 2", planner.day_text(conn, GATE_DAY))


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.conn = loaded()
        self.log = []
        self.app = build_app(self.conn)
        self.app.executors = Executors(run={"email": lambda p: self.log.append("sent") or "Email sent."},
                                       undo={"email": lambda p: "Email recalled."})
        self.clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
        self.s = FakeSender()

    def say(self, text):
        return step(self.app, self.s, self.clock, text)

    def test_conversation(self):
        self.assertIn("Marked done: LeetCode 7", self.say("done leetcode 7"))
        self.assertIn("Moved to Thu 19 Nov", self.say("push youtube to tomorrow"))
        self.assertIn("Skipped", self.say("skip lec 2"))
        self.assertIn("could not find", self.say("done unicorn"))
        self.assertIn("did not understand the day", self.say("push gate to someday"))
        self.assertIn("I kept", self.say("i only have 2 hours"))
        self.assertIn("Undone", self.say("undo"))

    def test_undo_takes_whichever_was_last(self):
        a = approvals.create(self.conn, "email", "Email Prof X")
        self.say("done leetcode")
        self.clock.advance(minutes=5)
        self.assertEqual(self.say(f"yes {a}"), "Email sent.")
        self.assertEqual(self.say("undo"), "Email recalled.")                    # the approval was later
        self.assertIn("put 3 items back", self.say("undo"))                      # then the plan change
        self.assertEqual(self.say("undo"), "There is nothing to undo.")


if __name__ == "__main__":
    unittest.main()
