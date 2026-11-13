import sqlite3
import unittest
from datetime import datetime, timezone

from ca import db

EXPECTED_TABLES = {"schema_version", "settings", "tasks", "events", "applications",
                   "facts", "approvals", "messages", "model_calls"}


def fresh():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


class SchemaTests(unittest.TestCase):
    def test_all_tables_exist(self):
        conn = fresh()
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(EXPECTED_TABLES <= names)

    def test_init_is_safe_to_repeat(self):
        conn = fresh()
        db.set_setting(conn, "k", "v")
        db.init_schema(conn)
        self.assertEqual(db.get_setting(conn, "k"), "v")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0], 1)

    def test_bad_status_is_rejected_by_the_database(self):
        conn = fresh()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (title, status, created_at) VALUES ('x','weird','t')")


class KillSwitchTests(unittest.TestCase):
    def test_not_paused_by_default_and_toggles(self):
        conn = fresh()
        self.assertFalse(db.is_paused(conn))
        db.set_paused(conn, True)
        self.assertTrue(db.is_paused(conn))
        db.set_paused(conn, False)
        self.assertFalse(db.is_paused(conn))


class ApprovalTests(unittest.TestCase):
    def test_lifecycle_and_undo(self):
        conn = fresh()
        a = db.add_approval(conn, "email", "Send intro to Prof X", {"to": "x@example.org"})
        self.assertEqual([r["id"] for r in db.pending_approvals(conn)], [a])
        db.decide_approval(conn, a, "approved")
        self.assertEqual(db.pending_approvals(conn), [])
        db.decide_approval(conn, a, "undone")

    def test_illegal_moves_are_refused(self):
        conn = fresh()
        a = db.add_approval(conn, "email", "s")
        with self.assertRaises(ValueError):
            db.decide_approval(conn, a, "undone")       # cannot undo what was never approved
        db.decide_approval(conn, a, "rejected")
        with self.assertRaises(ValueError):
            db.decide_approval(conn, a, "approved")     # a rejected request stays rejected
        with self.assertRaises(KeyError):
            db.decide_approval(conn, 999, "approved")


class LogTests(unittest.TestCase):
    def test_messages_are_recorded(self):
        conn = fresh()
        db.add_message(conn, "in", "hello")
        db.add_message(conn, "out", "hi", status="blocked_paused")
        rows = conn.execute("SELECT direction, status FROM messages ORDER BY id").fetchall()
        self.assertEqual([(r["direction"], r["status"]) for r in rows], [("in", "logged"), ("out", "blocked_paused")])

    def test_daily_model_cap_counts_only_today(self):
        conn = fresh()
        today = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
        yesterday = datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc)
        db.log_model_call(conn, "gemini", "m", "triage", now=yesterday)
        db.log_model_call(conn, "gemini", "m", "triage", now=today)
        db.log_model_call(conn, "gemini", "m", "draft", ok=False, now=today)
        self.assertEqual(db.model_calls_today(conn, now=today), 2)


if __name__ == "__main__":
    unittest.main()
