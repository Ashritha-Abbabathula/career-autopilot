import unittest
from datetime import date, datetime, timezone

from ca import approvals, db, deadlines, planner
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.senders import FakeSender

PLAN = {
    "dsa": [{"id": n, "title": f"Problem {n}"} for n in range(1, 21)],
    "youtube": [{"title": f"Video set {n}", "links": []} for n in range(1, 4)],
    "gate_days": [
        {"minutes": 240, "items": [{"subject": "Algebra", "title": "Lec 1", "video_min": 100},
                                   {"subject": "Algebra", "title": "Lec 2", "video_min": 0}]},
        {"minutes": 240, "items": [{"subject": "Algebra", "title": "Lec 3", "video_min": 90}]},
    ],
}
SETTINGS = {
    "start": "2026-11-14", "end": "2026-11-20", "gate_start": "2026-11-18",
    "progress": {"dsa_done": 2, "youtube_done": 1, "gate_done": 0},
    "dsa_per_day_before_gate": 1, "dsa_per_day_after_gate": 3,
    "exams": {"2026-11-16": "Maths FAT"},
    "prep": {"2026-11-15": "Maths preparation", "2027-01-01": "outside the range"},
    "items": [{"date": "2026-11-16", "kind": "touch", "title": "Request the certificate"}],
}
D = date.fromisoformat


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    counts = planner.import_plan(conn, PLAN, SETTINGS)
    return conn, counts


class ImportTests(unittest.TestCase):
    def test_counts_and_placement(self):
        conn, counts = loaded()
        # 4 days at 1 a day, then 3 days at 3 a day = 13 problems, starting after the 2 already done
        self.assertEqual(counts, {"dsa": 13, "youtube": 2, "gate": 3, "exams": 1, "items": 1})
        first = planner.tasks_on(conn, D("2026-11-14"))
        self.assertEqual([t["title"] for t in first], ["LeetCode 3: Problem 3"])
        gate_day = planner.tasks_on(conn, D("2026-11-18"))
        self.assertEqual([t["kind"] for t in gate_day], ["dsa", "dsa", "dsa", "gate", "gate", "youtube"])
        self.assertEqual(gate_day[4]["minutes"], 60)                      # no video length falls back to an hour
        self.assertEqual(planner.tasks_on(conn, D("2026-11-15"))[0]["movable"], 0)   # college work never moves

    def test_second_import_refused_and_force_keeps_done_work(self):
        conn, _ = loaded()
        with self.assertRaises(ValueError):
            planner.import_plan(conn, PLAN, SETTINGS)
        conn.execute("UPDATE tasks SET status = 'done' WHERE title = 'LeetCode 3: Problem 3'")
        counts = planner.import_plan(conn, PLAN, SETTINGS, force=True)
        titles = [r["title"] for r in conn.execute("SELECT title FROM tasks WHERE kind='dsa' ORDER BY id")]
        self.assertEqual(titles.count("LeetCode 3: Problem 3"), 1)        # done work is kept, not planned again
        self.assertEqual(titles[1], "LeetCode 4: Problem 4")
        self.assertEqual(counts["exams"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)


class TextTests(unittest.TestCase):
    def test_day_text(self):
        conn, _ = loaded()
        text = planner.day_text(conn, D("2026-11-18"))
        self.assertTrue(text.startswith("Today, 18 Nov"))
        self.assertIn("LeetCode:\n[ ] LeetCode 7: Problem 7", text)
        self.assertIn("Study time left: 6h 10m", text)                    # 3x30 + 100 + 60 + 120
        self.assertIn("Nothing planned. A free day.", planner.day_text(conn, D("2026-12-25")))
        self.assertTrue(planner.day_text(conn, D("2026-11-15"), today=D("2026-11-14")).startswith("Tomorrow"))

    def test_morning_card_on_exam_day(self):
        conn, _ = loaded()
        deadlines.add_reminder(conn, D("2026-11-17"), "Send the form")
        approvals.create(conn, "email", "Email Prof X")
        card = planner.morning_card(conn, D("2026-11-16"))
        self.assertIn("Exam day: Maths FAT", card)
        self.assertIn("EXAM: Maths FAT", card)
        self.assertIn("Only you can do:\n[ ] Request the certificate", card)
        self.assertIn("Send the form - tomorrow", card)
        self.assertIn("1 thing waiting for your yes", card)

    def test_morning_card_on_plain_and_empty_days(self):
        conn, _ = loaded()
        card = planner.morning_card(conn, D("2026-11-14"))
        self.assertNotIn("Exam day", card)
        self.assertNotIn("waiting", card)
        self.assertIn("A free day", planner.morning_card(conn, D("2027-01-10")))

    def test_week_text(self):
        conn, _ = loaded()
        lines = planner.week_text(conn, D("2026-11-14")).splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[0], "Sat 14 Nov: 1 LeetCode (30m)")
        self.assertEqual(lines[1], "Sun 15 Nov: Maths preparation; 1 LeetCode (30m)")
        self.assertIn("EXAM Maths FAT", lines[2])
        self.assertEqual(planner.week_text(conn, D("2027-03-01"), days=1), "Mon 01 Mar: free")

    def test_exam_word_matching(self):
        self.assertTrue(planner.is_exam("DAA FAT"))
        self.assertFalse(planner.is_exam("Fatigue workshop"))


class HandlerTests(unittest.TestCase):
    def test_today_and_week_commands_use_local_date(self):
        conn, _ = loaded()
        app = build_app(conn)
        # 20:00 UTC on the 14th is already the 15th in India
        clock = FakeClock(datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc))
        s = FakeSender()
        self.assertIn("Today, 15 Nov", step(app, s, clock, "today"))
        self.assertTrue(step(app, s, clock, "week").startswith("Sun 15 Nov"))


if __name__ == "__main__":
    unittest.main()
