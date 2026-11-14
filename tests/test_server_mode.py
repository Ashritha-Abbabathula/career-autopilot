"""The pieces that let the bot run on an always-on server instead of the laptop."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ca import config, db, runtime, tracker
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.http import FakeHttp, _multipart
from ca.senders import FakeSender
from ca.telegram import TelegramError, TelegramSender
from tests.test_calendar_view import loaded


class DocumentTests(unittest.TestCase):
    def test_multipart_body_is_well_formed(self):
        ctype, body = _multipart({"chat_id": "5", "caption": "hi"}, "document", "a.html", b"<p>x</p>")
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()))
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))
        self.assertIn(b'name="document"; filename="a.html"', body)
        self.assertIn(b"\r\n\r\n<p>x</p>\r\n", body)

    def test_send_document_uses_the_owner_chat_and_hides_the_token_on_error(self):
        http = FakeHttp().add(200, {"ok": True}).add(500, "x")
        sender = TelegramSender(http, "123:tok", "555")
        sender.send_document("c.html", b"abc", "caption")
        call = http.calls[0]
        self.assertTrue(call["url"].endswith("/sendDocument"))
        self.assertEqual((call["fields"]["chat_id"], call["filename"], call["size"]), ("555", "c.html", 3))
        with self.assertRaises(TelegramError) as ctx:
            sender.send_document("c.html", b"abc")
        self.assertNotIn("123:tok", str(ctx.exception))

    def test_calendar_command_sends_the_file_after_the_reply(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        with tempfile.TemporaryDirectory() as out:
            app.private_dir = out
            app.output_dir = out
            clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
            reply = step(app, FakeSender(), clock, "calendar")
        self.assertIn("Calendar sent as a file", reply)
        self.assertEqual(len(app.attachments), 1)
        sent = []
        sender = SimpleNamespace(send_document=lambda *a: sent.append(a))
        runtime.send_attachments(app, sender)
        self.assertEqual(sent[0][0], "calendar.html")
        self.assertIn(b"Career calendar", sent[0][1])
        self.assertEqual(app.attachments, [])                                   # sent once, not again
        app.attachments.append(("x.html", b"x", ""))
        runtime.send_attachments(app, FakeSender())                              # a sender with no file support: dropped quietly
        self.assertEqual(app.attachments, [])

    def test_a_failed_file_send_does_not_break_the_loop(self):
        app = build_app(loaded())
        app.attachments.append(("x.html", b"x", ""))
        def boom(*a):
            raise RuntimeError("down")
        runtime.send_attachments(app, SimpleNamespace(send_document=boom))      # must not raise


class SeparateFoldersTests(unittest.TestCase):
    def test_bot_reads_the_scouts_csv_and_writes_its_own_copy(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        with tempfile.TemporaryDirectory() as tmp:
            notes, out = Path(tmp) / "notes", Path(tmp) / "out"
            (notes / "tracker").mkdir(parents=True)
            read = notes / "tracker" / "applications.csv"
            read.write_text("id,organisation,role_or_programme,status\n1,Org A,Intern,not started\n", encoding="utf-8")
            result = tracker.sync_csv(conn, read, out / "tracker" / "applications.csv")
            self.assertEqual(result["added"], 1)
            self.assertTrue((out / "tracker" / "applications.csv").is_file())
            self.assertNotIn("applied", read.read_text(encoding="utf-8"))        # the notes repo file was not touched
            tracker.mark_applied(conn, 1, datetime(2026, 11, 18).date())
            tracker.sync_csv(conn, read, out / "tracker" / "applications.csv")
            self.assertIn("applied", (out / "tracker" / "applications.csv").read_text(encoding="utf-8"))
            self.assertNotIn("applied", read.read_text(encoding="utf-8"))

    def test_config_reads_the_server_settings(self):
        cfg = config.load_config(env={"CA_OUTPUT_DIR": "/srv/out", "NOTES_AUTOPULL": "1"}, env_file=None)
        self.assertEqual((cfg.output_dir, cfg.notes_autopull), ("/srv/out", True))
        cfg = config.load_config(env={}, env_file=None)
        self.assertEqual((cfg.output_dir, cfg.notes_autopull), ("", False))


class PullNotesTests(unittest.TestCase):
    def test_pulls_with_fast_forward_only_from_inside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "notes"
            (repo / ".git").mkdir(parents=True)
            private = repo / "notebooks" / "09-career-autopilot"
            private.mkdir(parents=True)
            seen = []
            def fake_run(cmd, **kw):
                seen.append(cmd)
                return SimpleNamespace(returncode=0)
            self.assertTrue(runtime.pull_notes(private, run=fake_run))
            self.assertEqual(seen[0][:2], ["git", "-C"])
            self.assertEqual(Path(seen[0][2]), repo)
            self.assertIn("--ff-only", seen[0])

    def test_failures_and_non_repos_are_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(runtime.pull_notes(tmp, run=lambda *a, **k: self.fail("git must not run outside a repo")))
            (Path(tmp) / ".git").mkdir()
            self.assertFalse(runtime.pull_notes(tmp, run=lambda *a, **k: SimpleNamespace(returncode=1)))
            def boom(*a, **k):
                raise OSError("no git")
            self.assertFalse(runtime.pull_notes(tmp, run=boom))


if __name__ == "__main__":
    unittest.main()
