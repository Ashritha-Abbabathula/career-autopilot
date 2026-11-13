import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import db, deadlines, digest
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.senders import FakeSender

TODAY = date(2026, 11, 14)
HEADER = "id,date_found,name,type,organiser,location,mode,deadline,link,eligible,legit,fit,value,effort,decision,reasoning,status,source\n"


def row(i, name, deadline, decision, status="preparing"):
    return f'{i},2026-11-13,{name},fellowship,Org,Bengaluru,on-site,{deadline},http://x,yes,yes,high,high,low,{decision},reason,{status},web\n'


def folder(tmp):
    root = Path(tmp)
    (root / "tracker").mkdir()
    (root / "tracker" / "opportunities.csv").write_text(
        HEADER + row(1, "Late Fellowship", "2026-12-01", "APPLY") + row(2, "Soon Fellowship", "2026-11-20", "APPLY")
        + row(3, "Skipped Thing", "2026-11-18", "SKIP") + row(4, "Old Thing", "2026-10-01", "APPLY")
        + row(5, "Watch Thing", "unknown", "WATCH") + row(6, "Done Thing", "2026-11-19", "APPLY", "applied"), encoding="utf-8")
    (root / "tracker" / "inbox_summary.json").write_text(json.dumps([
        {"date": "2026-11-13", "from": "a", "subject": "Newsletter", "kind": "newsletter", "summary": "ignore"},
        {"date": "2026-11-13", "from": "b", "subject": "Interview slot", "kind": "interview", "summary": "pick a time"},
        {"date": "2026-10-01", "from": "c", "subject": "Too old", "kind": "reply", "summary": "x"},
        "not a dict"]), encoding="utf-8")
    (root / "tracker" / "DAILY_DIGEST.md").write_text("# Title\n\nFirst note\nSecond note\n", encoding="utf-8")
    return root


class DigestTests(unittest.TestCase):
    def test_opportunities_filtered_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = [r["name"] for r in digest.open_opportunities(folder(tmp), TODAY)]
        self.assertEqual(names, ["Soon Fellowship", "Late Fellowship", "Watch Thing"])

    def test_mail_recent_and_important_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            subjects = [m["subject"] for m in digest.mail_items(folder(tmp), TODAY)]
        self.assertEqual(subjects, ["Interview slot", "Newsletter"])

    def test_full_digest(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        deadlines.add_reminder(conn, date(2026, 11, 16), "Request the bonafide")
        with tempfile.TemporaryDirectory() as tmp:
            text = digest.build_digest(conn, folder(tmp), TODAY)
        for piece in ("Due this week:", "Request the bonafide - in 2 days", "Worth a look:", "Soon Fellowship (APPLY, 2026-11-20)",
                      "Mail:", "interview: Interview slot (pick a time)", "Scout notes:\nFirst note\nSecond note"):
            self.assertIn(piece, text)
        self.assertNotIn("Title", text)

    def test_missing_or_broken_files_are_fine(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        self.assertIn("Nothing new", digest.build_digest(conn, "does/not/exist", TODAY))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tracker").mkdir()
            (Path(tmp) / "tracker" / "inbox_summary.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(digest.mail_items(Path(tmp), TODAY), [])

    def test_digest_command(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        app = build_app(conn)
        with tempfile.TemporaryDirectory() as tmp:
            app.private_dir = str(folder(tmp))
            clock = FakeClock(datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc))
            reply = step(app, FakeSender(), clock, "digest")
        self.assertIn("Digest for Sat 14 Nov", reply)
        self.assertIn("Soon Fellowship", reply)


if __name__ == "__main__":
    unittest.main()
