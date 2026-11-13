import json
import re
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import approvals, calendar_view, db, deadlines, planner, runtime
from ca.chat import build_app, step
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.senders import FakeSender
from tests.test_planner import PLAN, SETTINGS

TODAY = date(2026, 11, 18)


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    planner.import_plan(conn, PLAN, SETTINGS)
    return conn


def data_of(html):
    return json.loads(re.search(r"const D=(\{.*?\});const days", html, re.S).group(1))


class CollectTests(unittest.TestCase):
    def test_days_hold_tasks_exams_and_deadlines(self):
        conn = loaded()
        deadlines.add_reminder(conn, date(2026, 11, 19), "Send the form")
        days = calendar_view.collect(conn, date(2026, 11, 14), date(2026, 11, 20), TODAY)
        kinds16 = {i["kind"] for i in days["2026-11-16"]}
        self.assertIn("exam", kinds16)
        self.assertIn("touch", kinds16)
        self.assertTrue(any(i["kind"] == "due" and "Send the form" in i["title"] for i in days["2026-11-19"]))
        self.assertTrue(any(i["kind"] == "gate" for i in days["2026-11-18"]))

    def test_moved_tasks_leave_the_old_day_and_done_tasks_are_marked(self):
        conn = loaded()
        conn.execute("UPDATE tasks SET status = 'done' WHERE title = 'LeetCode 7: Problem 7'")
        days = calendar_view.collect(conn, date(2026, 11, 18), date(2026, 11, 18), TODAY)
        item = next(i for i in days["2026-11-18"] if i["title"] == "LeetCode 7: Problem 7")
        self.assertEqual(item["status"], "done")


class RenderTests(unittest.TestCase):
    def test_html_is_self_contained_and_script_breaking_text_is_safe(self):
        conn = loaded()
        conn.execute("INSERT INTO tasks (title, kind, planned_date, created_at) VALUES ('</script><b>x</b>','info','2026-11-18','t')")
        html = calendar_view.render(conn, TODAY, date(2026, 11, 1), date(2026, 12, 31))
        self.assertEqual(html.count("</script>"), 1)                       # only the real closing tag
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        d = data_of(html)
        self.assertEqual(d["today"], "2026-11-18")
        self.assertTrue(any("<b>x</b>" in i["title"] for i in d["days"]["2026-11-18"]))

    def test_write_creates_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = calendar_view.write(loaded(), Path(tmp) / "a" / "b" / "cal.html", TODAY)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))


class BotTests(unittest.TestCase):
    def test_calendar_command(self):
        conn = loaded()
        app = build_app(conn)
        with tempfile.TemporaryDirectory() as tmp:
            app.private_dir = tmp
            clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
            reply = step(app, FakeSender(), clock, "calendar")
            self.assertTrue((Path(tmp) / "calendar" / "live_calendar.html").is_file())
        self.assertIn("Calendar rebuilt", reply)
        self.assertIn("Wed 18 Nov", reply)
        app.private_dir = ""
        self.assertIn("CA_PRIVATE_DIR", step(app, FakeSender(), clock, "calendar"))

    def test_morning_refresh_is_silent(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "CA_PRIVATE_DIR": tmp}, env_file=None)
            sender = FakeSender()
            clock = FakeClock(datetime(2026, 11, 18, 6, 15, tzinfo=IST).astimezone(timezone.utc))
            self.assertIn("calendar_refresh", runtime.tick(app, sender, FakeHttp(), cfg, clock))
            self.assertEqual(sender.sent, [])                               # nothing messaged
            self.assertTrue((Path(tmp) / "calendar" / "live_calendar.html").is_file())


if __name__ == "__main__":
    unittest.main()
