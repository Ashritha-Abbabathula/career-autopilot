import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from ca import calendar_server, calendar_view, db, deadlines, planner, runtime
from ca.chat import build_app, step
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.senders import FakeSender
from tests.test_planner import PLAN, SETTINGS

TODAY = date(2026, 11, 18)

PLAN_WITH_LINKS = dict(PLAN, youtube=[{"title": f"Video set {n}", "links": [["ML playlist", f"https://example.org/{n}"]]} for n in range(1, 4)])
SETTINGS_WITH_ITEMS = dict(SETTINGS, items=SETTINGS["items"] + [
    {"date": "2026-11-17", "kind": "ok", "title": "Approve the draft", "detail": "Yes, skip or edit."}])


def loaded(path=":memory:"):
    conn = db.connect(path)
    db.init_schema(conn)
    planner.import_plan(conn, PLAN_WITH_LINKS, SETTINGS_WITH_ITEMS)
    return conn


def data_of(html):
    return json.loads(re.search(r"const D=(\{.*?\});\nconst SERVER", html, re.S).group(1))


class CollectTests(unittest.TestCase):
    def test_original_features_are_in_the_data(self):
        conn = loaded()
        d = data_of(calendar_view.render(conn, TODAY, date(2026, 11, 14), date(2026, 11, 20)))
        self.assertEqual(d["base"], {"dsa": 2, "youtube": 1, "gate": 0})                  # what you had already done
        self.assertEqual(d["totals"], {"dsa": 20, "youtube": 3, "gate": 2})
        day = {i["id"]: i for i in d["byDate"]["2026-11-18"]}
        dsa = next(i for i in day.values() if i["stream"] == "dsa")
        self.assertIn("leetcode.com/problemset/?search=", dsa["link"])                  # "Open problem" link
        yt = next(i for i in day.values() if i["stream"] == "yt")
        self.assertEqual(yt["links"][0][0], "ML playlist")                              # video links
        gate = next(i for i in day.values() if i["title"] == "GATE Algebra: Lec 1")
        self.assertEqual(gate["detail"], "100 min of video")
        lec2 = next(i for i in day.values() if i["title"] == "GATE Algebra: Lec 2")
        self.assertEqual(lec2["detail"], "Practice and revision")                      # no video length
        streams16 = {i["stream"] for i in d["byDate"]["2026-11-16"]}
        self.assertTrue({"fat", "touch"} <= streams16)                                  # exam day and "needs you"
        fat = next(i for i in d["byDate"]["2026-11-16"] if i["stream"] == "fat")
        self.assertIn("Exam day", fat["detail"])
        ok = next(i for i in d["byDate"]["2026-11-17"] if i["stream"] == "ok")
        self.assertEqual(ok["detail"], "Yes, skip or edit.")

    def test_done_work_shows_as_done(self):
        conn = loaded()
        conn.execute("UPDATE tasks SET status = 'done' WHERE title = 'LeetCode 7: Problem 7'")
        d = data_of(calendar_view.render(conn, TODAY, date(2026, 11, 18), date(2026, 11, 18)))
        item = next(i for i in d["byDate"]["2026-11-18"] if i["title"] == "LeetCode 7: Problem 7")
        self.assertTrue(item["done"])

    def test_deadlines_appear(self):
        conn = loaded()
        deadlines.add_reminder(conn, date(2026, 11, 19), "Send the form")
        d = data_of(calendar_view.render(conn, TODAY, date(2026, 11, 14), date(2026, 11, 20)))
        self.assertTrue(any(i["stream"] == "due" and "Send the form" in i["title"] for i in d["byDate"]["2026-11-19"]))

    def test_span_follows_the_plan_dates(self):
        conn = loaded()
        self.assertEqual(calendar_view.span(conn, TODAY), (date(2026, 11, 14), date(2026, 11, 20)))


class RenderTests(unittest.TestCase):
    def test_html_is_self_contained_and_script_breaking_text_is_safe(self):
        conn = loaded()
        conn.execute("INSERT INTO tasks (title, kind, planned_date, created_at) VALUES ('</script><b>x</b>','info','2026-11-18','t')")
        html = calendar_view.render(conn, TODAY, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(html.count("</script>"), 1)
        self.assertNotIn("http://", html.replace("http://localhost", "").replace("http://www.w3.org", ""))
        self.assertTrue(any("<b>x</b>" in i["title"] for i in data_of(html)["byDate"]["2026-11-18"]))

    def test_page_keeps_the_original_controls(self):
        html = calendar_view.render(loaded(), TODAY, date(2026, 11, 14), date(2026, 11, 20))
        for piece in ("Export my decisions", "my-decisions.csv", "FAT prep", "Open problem", "data-a=", "approve", "skip", "later",
                      '["Sun","Mon"', "localStorage", "cc-state-v1"):
            self.assertIn(piece, html)

    def test_write_creates_folders_and_uses_the_plan_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = calendar_view.write(loaded(), Path(tmp) / "a" / "b" / "cal.html", TODAY)
            d = data_of(out.read_text(encoding="utf-8"))
        self.assertEqual((d["start"], d["end"]), ("2026-11-14", "2026-11-20"))


class ChangeTests(unittest.TestCase):
    def test_tick_and_untick(self):
        conn = loaded()
        tid = conn.execute("SELECT id FROM tasks WHERE title = 'LeetCode 7: Problem 7'").fetchone()["id"]
        self.assertTrue(calendar_view.apply_tick(conn, f"t{tid}", True))
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()["status"], "done")
        self.assertTrue(calendar_view.apply_tick(conn, f"t{tid}", False))
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()["status"], "todo")
        for bad in ("e1", "d1", "t99999", "x", "t"):
            self.assertFalse(calendar_view.apply_tick(conn, bad, True))

    def test_decisions_only_apply_to_assistant_items(self):
        conn = loaded()
        ok = conn.execute("SELECT id FROM tasks WHERE kind = 'ok'").fetchone()["id"]
        study = conn.execute("SELECT id FROM tasks WHERE kind = 'dsa'").fetchone()["id"]
        self.assertTrue(calendar_view.apply_decision(conn, f"t{ok}", "approve"))
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id = ?", (ok,)).fetchone()["status"], "done")
        self.assertTrue(calendar_view.apply_decision(conn, f"t{ok}", "skip"))
        self.assertTrue(calendar_view.apply_decision(conn, f"t{ok}", "later"))
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id = ?", (ok,)).fetchone()["status"], "todo")
        self.assertFalse(calendar_view.apply_decision(conn, f"t{study}", "approve"))
        self.assertFalse(calendar_view.apply_decision(conn, f"t{ok}", "delete"))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "ca.sqlite")
        conn = loaded(self.path)
        self.tid = conn.execute("SELECT id FROM tasks WHERE title = 'LeetCode 7: Problem 7'").fetchone()["id"]
        conn.close()
        self.server = calendar_server.start(self.path, "Asia/Kolkata", 0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, path, body, header=True, host=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Calendar": "1"} if header else {}),
                                              **({"Host": host} if host else {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_page_is_served_and_ticks_reach_the_database(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            self.assertIn("Career calendar", r.read().decode())
        self.assertEqual(self.post("/api/tick", {"id": f"t{self.tid}", "done": True}), 200)
        conn = db.connect(self.path)
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE id = ?", (self.tid,)).fetchone()["status"], "done")
        # and the bot's own view agrees
        self.assertIn("[x] LeetCode 7: Problem 7", planner.day_text(conn, TODAY))
        conn.close()

    def test_refusals(self):
        self.assertEqual(self.post("/api/tick", {"id": f"t{self.tid}", "done": True}, header=False), 403)    # no page header
        self.assertEqual(self.post("/api/tick", {"id": f"t{self.tid}", "done": True}, host="evil.example"), 403)
        self.assertEqual(self.post("/api/tick", {"id": "e1", "done": True}), 400)
        self.assertEqual(self.post("/api/nope", {"id": "t1"}), 404)
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + "/", headers={"Host": "evil.example"}), timeout=5)
            self.fail("a foreign host name must be refused")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)
        try:
            urllib.request.urlopen(self.base + "/secrets", timeout=5)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


class BotTests(unittest.TestCase):
    def test_calendar_command(self):
        conn = loaded()
        app = build_app(conn)
        with tempfile.TemporaryDirectory() as tmp:
            app.private_dir = tmp
            clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
            reply = step(app, FakeSender(), clock, "calendar")
            self.assertTrue((Path(tmp) / "calendar" / "live_calendar.html").is_file())
        self.assertIn("http://localhost:8765/", reply)
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
            self.assertFalse(any("Calendar" in m[2] for m in sender.sent))
            self.assertTrue((Path(tmp) / "calendar" / "live_calendar.html").is_file())


class UpgradeTests(unittest.TestCase):
    def test_old_database_gets_the_meta_column_and_a_one_time_reimport(self):
        conn = db.connect(":memory:")
        conn.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL);")
        db.init_schema(conn)                       # fresh schema has meta
        conn.execute("ALTER TABLE tasks RENAME TO tasks_old")
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'study', "
                     "planned_date TEXT, minutes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'todo', "
                     "movable INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL)")
        conn.execute("DROP TABLE tasks_old")
        db.init_schema(conn)
        self.assertIn("meta", {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")})

    def test_bootstrap_reimports_an_older_plan_once_and_keeps_done_work(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        planner.import_plan(conn, PLAN_WITH_LINKS, SETTINGS_WITH_ITEMS)
        conn.execute("UPDATE tasks SET status = 'done' WHERE title = 'LeetCode 3: Problem 3'")
        db.set_setting(conn, "plan_schema", "2")                         # as if imported by the earlier version
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calendar").mkdir()
            (Path(tmp) / "calendar" / "plan_data.json").write_text(json.dumps(PLAN_WITH_LINKS), encoding="utf-8")
            (Path(tmp) / "calendar" / "plan_settings.json").write_text(json.dumps(SETTINGS_WITH_ITEMS), encoding="utf-8")
            app = build_app(conn)
            cfg = load_config(env={"CA_PRIVATE_DIR": tmp, "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "1"}, env_file=None)
            self.assertEqual(len(runtime.bootstrap(app, cfg)), 1)
            self.assertEqual(runtime.bootstrap(app, cfg), [])            # only once
        titles = [r["title"] for r in conn.execute("SELECT title FROM tasks WHERE title LIKE 'LeetCode 3%'")]
        self.assertEqual(titles, ["LeetCode 3: Problem 3"])               # the ticked one is kept, not planned again


if __name__ == "__main__":
    unittest.main()
