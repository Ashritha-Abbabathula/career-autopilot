import unittest
from datetime import datetime, timedelta, timezone

from ca import db, outbox
from ca.senders import FakeSender

# 06:30 UTC = 12:00 IST, a normal daytime moment
NOON = datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc)


def fresh():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


def status(conn, i):
    return conn.execute("SELECT status FROM outbox WHERE id = ?", (i,)).fetchone()["status"]


class ReplyTests(unittest.TestCase):
    def test_reply_sends_even_when_paused_and_quiet(self):
        conn = fresh()
        db.set_paused(conn, True)
        night = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)   # 01:30 IST, quiet
        i = outbox.enqueue(conn, "+910000000000", "paused. say resume.", "reply", now=night)
        s = FakeSender()
        outbox.flush(conn, s, night)
        self.assertEqual(status(conn, i), "sent")
        self.assertEqual(len(s.sent), 1)


class ProactiveTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh()
        db.add_message(self.conn, "in", "hi", now=NOON - timedelta(hours=1))   # window open

    def test_paused_blocks_proactive(self):
        db.set_paused(self.conn, True)
        i = outbox.enqueue(self.conn, "n", "digest", "proactive", now=NOON)
        s = FakeSender()
        outbox.flush(self.conn, s, NOON)
        self.assertEqual(status(self.conn, i), "blocked_paused")
        self.assertEqual(s.sent, [])

    def test_quiet_hours_defer_then_send(self):
        late = datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)      # 00:00 IST
        db.add_message(self.conn, "in", "hi again", now=late - timedelta(minutes=5))
        i = outbox.enqueue(self.conn, "n", "digest", "proactive", now=late)
        s = FakeSender()
        outbox.flush(self.conn, s, late)
        self.assertEqual(status(self.conn, i), "queued")
        morning = datetime(2026, 11, 15, 1, 45, tzinfo=timezone.utc)    # 07:15 IST
        db.add_message(self.conn, "in", "gm", now=morning - timedelta(minutes=5))
        outbox.flush(self.conn, s, morning)
        self.assertEqual(status(self.conn, i), "sent")

    def test_send_after_is_respected(self):
        i = outbox.enqueue(self.conn, "n", "later", "proactive", send_after=NOON + timedelta(hours=1), now=NOON)
        s = FakeSender()
        outbox.flush(self.conn, s, NOON)
        self.assertEqual(status(self.conn, i), "queued")

    def test_daily_cap(self):
        ids = [outbox.enqueue(self.conn, "n", f"m{k}", "proactive", now=NOON) for k in range(3)]
        s = FakeSender()
        outbox.flush(self.conn, s, NOON, daily_proactive_cap=2)
        self.assertEqual([status(self.conn, i) for i in ids], ["sent", "sent", "blocked_budget"])

    def test_closed_window_needs_template(self):
        conn = fresh()
        db.add_message(conn, "in", "old", now=NOON - timedelta(hours=30))
        a = outbox.enqueue(conn, "n", "no template", "proactive", now=NOON)
        b = outbox.enqueue(conn, "n", "with template", "proactive", template_name="daily_digest", now=NOON)
        s = FakeSender()
        outbox.flush(conn, s, NOON)
        self.assertEqual(status(conn, a), "blocked_window")
        self.assertEqual(status(conn, b), "sent")
        self.assertEqual(s.sent[0][0], "template:daily_digest")

    def test_never_heard_from_her_means_window_closed(self):
        conn = fresh()
        i = outbox.enqueue(conn, "n", "x", "proactive", now=NOON)
        outbox.flush(conn, FakeSender(), NOON)
        self.assertEqual(status(conn, i), "blocked_window")


class FailureTests(unittest.TestCase):
    def test_failure_is_recorded_without_details(self):
        conn = fresh()
        i = outbox.enqueue(conn, "n", "x", "reply", now=NOON)
        outbox.flush(conn, FakeSender(fail=True), NOON)
        row = conn.execute("SELECT status, error FROM outbox WHERE id = ?", (i,)).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "RuntimeError")

    def test_sent_messages_are_logged_and_not_resent(self):
        conn = fresh()
        outbox.enqueue(conn, "n", "hello", "reply", now=NOON)
        s = FakeSender()
        outbox.flush(conn, s, NOON)
        outbox.flush(conn, s, NOON)
        self.assertEqual(len(s.sent), 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE direction='out'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
