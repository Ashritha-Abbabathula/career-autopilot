import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import db, deadlines, tracker
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.senders import FakeSender

FIXTURE = Path(__file__).parent / "fixtures" / "applications.csv"
TODAY = date(2026, 11, 14)


def fresh():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


class TrackerTests(unittest.TestCase):
    def test_add_update_list(self):
        conn = fresh()
        a = tracker.add(conn, "Org A", "Intern", decision="apply", deadline="2026-12-01")
        b = tracker.add(conn, "Org B", "Fellow", decision="nonsense")
        self.assertEqual(tracker.get(conn, a)["decision"], "APPLY")
        self.assertEqual(tracker.get(conn, b)["decision"], "MAYBE")          # unknown decisions become MAYBE
        tracker.mark_applied(conn, a, TODAY, method="portal")
        row = tracker.get(conn, a)
        self.assertEqual((row["status"], row["date_applied"], row["method"]), ("applied", "2026-11-14", "portal"))
        self.assertEqual([r["id"] for r in tracker.list_apps(conn, status="APPLIED")], [a])
        self.assertEqual([r["id"] for r in tracker.list_apps(conn, decision="maybe")], [b])

    def test_bad_input(self):
        conn = fresh()
        with self.assertRaises(ValueError):
            tracker.add(conn, "", "Intern")
        with self.assertRaises(ValueError):
            tracker.add(conn, "Org", "Intern", salary="1")
        with self.assertRaises(KeyError):
            tracker.update(conn, 99, status="applied")

    def test_import_is_repeatable_and_export_round_trips(self):
        conn = fresh()
        self.assertEqual(tracker.import_csv(conn, FIXTURE), {"added": 3, "updated": 0, "skipped": 1})
        self.assertEqual(tracker.import_csv(conn, FIXTURE), {"added": 0, "updated": 3, "skipped": 1})
        self.assertEqual(len(tracker.list_apps(conn)), 3)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "out.csv"
            self.assertEqual(tracker.export_csv(conn, out), 3)
            other = fresh()
            self.assertEqual(tracker.import_csv(other, out)["added"], 3)
            self.assertEqual(tracker.get(other, 1)["match_note"], "fits research goal, needs a letter")

    def test_summary(self):
        conn = fresh()
        self.assertEqual(tracker.summary_text(conn), "Your tracker is empty.")
        tracker.import_csv(conn, FIXTURE)
        text = tracker.summary_text(conn)
        self.assertIn("Applied: 1 | To apply: 1 | Watching: 1", text)
        self.assertIn("Example Labs: ML Intern (applied, 2026-10-10)", text)
        self.assertIn("(deadline 2026-11-30)", text)


class DeadlineTests(unittest.TestCase):
    def test_upcoming_sorted_with_overdue_and_reminders(self):
        conn = fresh()
        tracker.import_csv(conn, FIXTURE)
        deadlines.add_reminder(conn, date(2026, 11, 10), "Collect the bonafide")
        far = deadlines.add_reminder(conn, date(2027, 3, 1), "Far away")
        items = deadlines.upcoming(conn, TODAY, days=14)
        self.assertEqual([i.due.isoformat() for i in items], ["2026-11-10", "2026-11-14", "2026-11-15"])
        self.assertEqual(items[0].source, "reminder")
        self.assertNotIn(far, [i.ref_id for i in items if i.source == "reminder"])
        wide = deadlines.upcoming(conn, TODAY, days=30)
        self.assertIn("application", [i.source for i in wide])              # the 30 Nov deadline
        # the applied row's old deadline never shows
        self.assertFalse(any("Example Labs" in i.text for i in wide))

    def test_labels_and_done(self):
        conn = fresh()
        r = deadlines.add_reminder(conn, date(2026, 11, 13), "A")
        deadlines.add_reminder(conn, TODAY, "B")
        deadlines.add_reminder(conn, date(2026, 11, 15), "C")
        deadlines.add_reminder(conn, date(2026, 11, 20), "D")
        self.assertEqual(deadlines.text(conn, TODAY).splitlines(),
                         ["A - OVERDUE by 1 day", "B - today", "C - tomorrow", "D - in 6 days (20 Nov)"])
        deadlines.complete_reminder(conn, r)
        self.assertNotIn("A -", deadlines.text(conn, TODAY))
        self.assertEqual(deadlines.text(fresh(), TODAY), "Nothing due in the next 14 days.")
        self.assertIsNone(deadlines.parse_date("unknown"))


class AppsHandlerTests(unittest.TestCase):
    def test_apps_command(self):
        conn = fresh()
        tracker.import_csv(conn, FIXTURE)
        app = build_app(conn)
        clock = FakeClock(datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc))
        reply = step(app, FakeSender(), clock, "apps")
        self.assertIn("Applied: 1", reply)
        self.assertIn("Due soon:", reply)
        self.assertIn("ask a teacher for a letter - tomorrow", reply)


if __name__ == "__main__":
    unittest.main()
