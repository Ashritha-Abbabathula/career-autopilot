"""The calendar is the owner's original page; the bot follows the same schedule and the same ticks."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from ca import calendar_server, db, original_page, planner, replan, runtime, uistate
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.config import load_config
from ca.senders import FakeSender

D = date.fromisoformat

SCHED = {
    "START": "2026-10-03T18:30:00.000Z", "END": "2027-02-04T18:30:00.000Z",
    "GS": [["LA", "Linear Algebra"], ["ML", "Machine Learning"]],
    "COL": [["DAA", "Design and Analysis of Algorithms", ""], ["AI", "Artificial Intelligence", "X"]],
    "ORD": [1, 0], "EV": {"2026-10-06": ["Quiz"], "2026-11-16": ["DAA FAT"]},
    "DAYS": [[0, [[66, "Plus One"], [49, "Group Anagrams"]]], [1, [[238, "Product of Array Except Self"]]]],
    "dp": {"2026-10-06": 0, "2026-10-07": 1},
    "YT": [{"t": "ML playlist: videos 1-4", "l": [["ML playlist", "https://example.org/yt"]]}],
    "plan": {"2026-10-06": 0},
    "GD": [{"c": 240, "it": [[0, "M1 Lec 1 � Why linear algebra", 112], [1, "Practice set", 0]]}],
    "mp": {"2026-12-01": 0},
    "cm": {"2026-10-06": [0, 1]},
}
ITEMS = [{"date": "2026-10-06", "kind": "touch", "title": "Call the lab", "detail": "Ask about the project"},
         {"date": "2026-10-07", "kind": "ok", "title": "Approve the draft", "detail": ""}]

PAGE = ('<!DOCTYPE html><html><head><title>t</title></head><body><div class="top"></div><div id="cal"></div>\n<script>\n'
        'const ls={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v);return true}catch(e){return false}},del(k){try{localStorage.removeItem(k)}catch(e){}}};\n'
        'function cell(d){return \'<button class="cell" data-k="x">1</button>\'}\n'
        'function open(k){box.innerHTML="orig"}\nconst box={};\nrender();disp();rn();\n</script></body></html>')


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    planner.import_original(conn, SCHED, ITEMS)
    return conn


class ImportTests(unittest.TestCase):
    def test_schedule_matches_the_original_pages_own_data(self):
        conn = loaded()
        self.assertEqual(db.get_setting(conn, "plan_origin"), "original")
        info = json.loads(db.get_setting(conn, "plan_info"))
        self.assertEqual((info["start"], info["end"]), ("2026-10-04", "2027-02-05"))
        self.assertEqual(info["totals"], {"dsa": 3, "youtube": 1, "gate": 1})
        day = {t["title"] for t in planner.tasks_on(conn, D("2026-10-06"))}
        self.assertIn("LeetCode 66: Plus One", day)
        self.assertIn("ML playlist: videos 1-4", day)
        self.assertIn("College: Artificial Intelligence, module 1", day)          # ORD maps module 0 to the second course
        self.assertIn("College: Artificial Intelligence, module 2", day)
        gate = {t["title"] for t in planner.tasks_on(conn, D("2026-12-01"))}
        self.assertIn("GATE Linear Algebra: M1 Lec 1 - Why linear algebra", gate)  # the broken dash in the page is repaired
        self.assertEqual([e["title"] for e in planner.events_on(conn, D("2026-11-16"))], ["DAA FAT"])
        self.assertTrue(planner.is_exam("DAA FAT"))
        self.assertEqual(len([t for t in planner.tasks_on(conn, D("2026-10-06")) if t["kind"] == "touch"]), 1)

    def test_reimport_does_not_duplicate(self):
        conn = loaded()
        before = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        planner.import_original(conn, SCHED, ITEMS)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], before)


class TickSyncTests(unittest.TestCase):
    def test_page_ticks_reach_the_bot_and_back(self):
        conn = loaded()
        uistate.put(conn, "dsa-done", json.dumps({"66": 1, "y0": 1, "c0": 1}))      # ticks made on the page
        self.assertEqual(uistate.sync_tasks_from_state(conn), 3)
        text = planner.day_text(conn, D("2026-10-06"))
        self.assertIn("[x] LeetCode 66: Plus One", text)
        self.assertIn("[x] ML playlist: videos 1-4", text)
        self.assertIn("[ ] LeetCode 49: Group Anagrams", text)
        self.assertEqual(uistate.sync_tasks_from_state(conn), 0)                      # stable
        uistate.put(conn, "dsa-done", json.dumps({}))                                  # unticked on the page
        uistate.sync_tasks_from_state(conn)
        self.assertIn("[ ] LeetCode 66: Plus One", planner.day_text(conn, D("2026-10-06")))

    def test_bot_done_is_ticked_on_the_page_and_undo_unticks_it(self):
        conn = loaded()
        replan.done(conn, "leetcode", D("2026-10-06"))
        self.assertEqual(set(uistate.done_map(conn)), {"66", "49"})
        replan.undo_last(conn)
        self.assertEqual(uistate.done_map(conn), {})

    def test_skipped_and_moved_tasks_are_left_alone(self):
        conn = loaded()
        replan.skip(conn, "leetcode 66", D("2026-10-06"))
        uistate.put(conn, "dsa-done", json.dumps({"66": 1}))
        uistate.sync_tasks_from_state(conn)
        self.assertEqual(conn.execute("SELECT status FROM tasks WHERE title LIKE '%Plus One'").fetchone()["status"], "skipped")

    def test_bot_sees_page_ticks_on_the_next_message(self):
        conn = loaded()
        app = build_app(conn)
        uistate.put(conn, "dsa-done", json.dumps({"66": 1, "49": 1}))
        clock = FakeClock(datetime(2026, 10, 6, 6, 30, tzinfo=timezone.utc))
        self.assertIn("[x] LeetCode 66: Plus One", step(app, FakeSender(), clock, "today"))

    def test_state_keys_and_sizes_are_validated(self):
        conn = loaded()
        self.assertTrue(uistate.put(conn, "pomo-log", "{}"))
        self.assertFalse(uistate.put(conn, "bad key!", "x"))
        self.assertFalse(uistate.put(conn, "k", "x" * (uistate.MAX_VALUE + 1)))
        self.assertEqual(uistate.import_dump(conn, {"notes": "[]", "dsa-done": "{}", "bad key": "x", "n": 5}), 2)


class PageTests(unittest.TestCase):
    def test_wrap_swaps_storage_and_adds_the_overlay_without_touching_the_rest(self):
        html = original_page.wrap(PAGE, {"dsa-done": "{}"}, {"2026-10-06": [{"id": "t1", "stream": "touch", "title": "Call", "done": False}]})
        self.assertIn("window.__STATE__", html)
        self.assertIn('"/api/state"', html)
        self.assertIn("From your assistant", html)
        self.assertNotIn("const ls={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set", html.split("window.__STATE__")[1].split("</script>")[1])
        self.assertIn("function cell(d)", html)                                         # her own code is still there
        self.assertIn("render();disp();rn();", html)
        self.assertEqual(html.count("</script>"), 3)

    def test_a_changed_page_is_noticed(self):
        with self.assertRaises(ValueError):
            original_page.wrap("<html><script>nothing</script></body></html>", {}, {})

    def test_page_text_cannot_break_out_of_the_script(self):
        html = original_page.wrap(PAGE, {"notes": "</script><b>x</b>"}, {})
        self.assertEqual(html.count("</script>"), 3)

    def test_extras_hold_assistant_items_deadlines_and_history_but_not_study(self):
        from ca import calendar_view, deadlines
        conn = loaded()
        deadlines.add_reminder(conn, D("2026-10-10"), "Send the form")
        calendar_view.save_history(conn, {"2026-10-02": 4}, {"2026-10-03": 2})
        ex = original_page.extras(conn, D("2026-10-04"), D("2027-02-05"), D("2026-10-08"))
        self.assertEqual([i["stream"] for i in ex["2026-10-06"]], ["touch"])
        self.assertEqual(ex["2026-10-07"][0]["stream"], "ok")
        self.assertTrue(any(i["stream"] == "due" for i in ex["2026-10-10"]))
        self.assertIn("LeetCode: 4 submissions", ex["2026-10-02"][0]["title"])
        self.assertIn("GitHub: 2 commits", ex["2026-10-03"][0]["title"])
        self.assertFalse(any("LeetCode 66" in i["title"] for items in ex.values() for i in items))

    def test_render_needs_the_private_file(self):
        conn = loaded()
        self.assertIsNone(original_page.render(conn, "does/not/exist", D("2026-10-08")))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calendar").mkdir()
            (Path(tmp) / "calendar" / "original_plan.html").write_text(PAGE, encoding="utf-8")
            self.assertTrue(original_page.available(tmp))
            self.assertIn("From your assistant", original_page.render(conn, tmp, D("2026-10-08")))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "private" / "calendar").mkdir(parents=True)
        (root / "private" / "calendar" / "original_plan.html").write_text(PAGE, encoding="utf-8")
        self.path = str(root / "ca.sqlite")
        conn = db.connect(self.path)
        db.init_schema(conn)
        planner.import_original(conn, SCHED, ITEMS)
        conn.close()
        self.server = calendar_server.start(self.path, "Asia/Kolkata", 0, str(root / "private"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, path, body, header=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Calendar": "1"} if header else {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_original_page_is_served_and_state_is_saved_to_the_database(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            self.assertIn("From your assistant", r.read().decode())
        self.assertEqual(self.post("/api/state", {"k": "notes", "v": '[{"t":"hello"}]'}), 200)
        self.assertEqual(self.post("/api/state", {"k": "dsa-done", "v": json.dumps({"66": 1})}), 200)
        conn = db.connect(self.path)
        self.assertEqual(uistate.get(conn, "notes"), '[{"t":"hello"}]')
        self.assertIn("[x] LeetCode 66: Plus One", planner.day_text(conn, D("2026-10-06")))     # the bot sees the tick at once
        conn.close()
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:                              # and a reload shows it
            self.assertIn("hello", r.read().decode())
        self.assertEqual(self.post("/api/state", {"k": "notes", "v": None}), 200)

    def test_refusals(self):
        self.assertEqual(self.post("/api/state", {"k": "notes", "v": "x"}, header=False), 403)
        self.assertEqual(self.post("/api/state", {"k": "bad key!", "v": "x"}), 400)
        self.assertEqual(self.post("/api/state", {"k": "notes", "v": 5}), 400)


class BootstrapTests(unittest.TestCase):
    def test_original_schedule_in_the_private_folder_replaces_the_older_plan(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calendar").mkdir()
            (Path(tmp) / "calendar" / "original_schedule.json").write_text(json.dumps(SCHED), encoding="utf-8")
            (Path(tmp) / "calendar" / "plan_settings.json").write_text(json.dumps({"items": ITEMS}), encoding="utf-8")
            app = build_app(conn)
            cfg = load_config(env={"CA_PRIVATE_DIR": tmp, "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "1"}, env_file=None)
            notes = runtime.bootstrap(app, cfg)
            self.assertTrue(any("original 90-day plan imported" in n for n in notes))
            self.assertEqual(runtime.bootstrap(app, cfg), [])                              # once only


if __name__ == "__main__":
    unittest.main()
