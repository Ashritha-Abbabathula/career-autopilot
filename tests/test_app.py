import unittest
from datetime import datetime, timezone

from ca import approvals, db
from ca.app import App
from ca.approvals import Executors
from ca.chat import step
from ca.clock import FakeClock
from ca.senders import FakeSender


def make():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    log = []
    ex = Executors(run={"email": lambda p: log.append("sent") or "Email sent."},
                   undo={"email": lambda p: "Email recalled."})
    app = App(conn, "owner", ex)
    clock = FakeClock(datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc))
    return conn, app, FakeSender(), clock, log


class TranscriptTests(unittest.TestCase):
    def test_full_conversation(self):
        conn, app, s, clock, log = make()
        self.assertIn("help", step(app, s, clock, "hello there"))
        self.assertEqual(step(app, s, clock, "inbox"), "Nothing is waiting for you.")
        a = approvals.create(conn, "email", "Email Prof X")
        self.assertIn(f"{a}. Email Prof X", step(app, s, clock, "inbox"))
        self.assertEqual(step(app, s, clock, "yes"), "Email sent.")        # only one pending: number optional
        self.assertEqual(log, ["sent"])
        self.assertEqual(step(app, s, clock, "undo"), "Email recalled.")
        self.assertEqual(step(app, s, clock, "undo"), "There is nothing to undo.")
        self.assertEqual(len(s.sent), 6)                                    # every reply went through the outbox

    def test_number_needed_when_several_waiting(self):
        conn, app, s, clock, log = make()
        a = approvals.create(conn, "email", "one")
        b = approvals.create(conn, "email", "two")
        self.assertIn("Say which", step(app, s, clock, "yes"))
        self.assertEqual(log, [])
        self.assertEqual(step(app, s, clock, f"skip {a}"), f"Skipped item {a}.")
        self.assertEqual(step(app, s, clock, f"later {b}"), f"Okay, item {b} stays in your inbox.")
        self.assertIn("new text", step(app, s, clock, f"edit {b}"))
        self.assertIn("Updated", step(app, s, clock, f"edit {b} shorter"))

    def test_pause_blocks_approval_but_still_answers(self):
        conn, app, s, clock, log = make()
        a = approvals.create(conn, "email", "one")
        self.assertIn("Paused", step(app, s, clock, "pause"))
        self.assertIn("paused", step(app, s, clock, f"yes {a}").lower())
        self.assertEqual(log, [])
        self.assertEqual(step(app, s, clock, "resume"), "Resumed.")
        self.assertEqual(step(app, s, clock, f"yes {a}"), "Email sent.")
        self.assertEqual(len(s.sent), 4)                                    # replies went out even while paused

    def test_unregistered_and_registered_commands(self):
        conn, app, s, clock, _ = make()
        self.assertIn("not set up yet", step(app, s, clock, "scorecard"))
        app.register("scorecard", lambda a, c, n: "Plan: study.")
        self.assertEqual(step(app, s, clock, "scorecard"), "Plan: study.")
        self.assertIn("did not understand", step(app, s, clock, "blah blah"))
        self.assertIn("help", step(app, s, clock, ""))

    def test_messages_are_logged_both_ways(self):
        conn, app, s, clock, _ = make()
        step(app, s, clock, "help")
        dirs = [r["direction"] for r in conn.execute("SELECT direction FROM messages ORDER BY id")]
        self.assertEqual(dirs, ["in", "out"])


if __name__ == "__main__":
    unittest.main()
