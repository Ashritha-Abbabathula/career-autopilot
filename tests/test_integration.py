"""Things that only go wrong when the pieces are used together."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ca import approvals, db, digest, outreach, planner, replan, router, runtime, tracker
from ca.approvals import Executors
from ca.chat import build_app, step
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.llm import FakeModel
from ca.senders import FakeSender
from tests.test_outreach import DATA as FACTS, SPACE
from tests.test_planner import PLAN, SETTINGS

D = date.fromisoformat


def cfg(root=""):
    return load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "CA_PRIVATE_DIR": str(root)}, env_file=None)


def at(day, hour, minute=0):
    return FakeClock(datetime(2026, 11, day, hour, minute, tzinfo=IST).astimezone(timezone.utc))


def loaded():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    planner.import_plan(conn, PLAN, SETTINGS)
    return conn


class TrackerSyncTests(unittest.TestCase):
    def test_new_csv_rows_come_in_and_bot_changes_go_out_without_losing_either(self):
        conn = loaded()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tracker").mkdir()
            csv_path = root / "tracker" / "applications.csv"
            tracker.add(conn, "Org A", "Intern")
            tracker.export_csv(conn, csv_path)
            # the scout appends a row while the bot is running
            with csv_path.open("a", encoding="utf-8", newline="") as fh:
                fh.write("9,Org B,Fellow,Bengaluru,http://b,2026-11-14,2026-12-01,note,APPLY,,,,,not started,,,\n")
            app = build_app(conn, owner="555")
            app.private_dir = str(root)
            clock = at(14, 9)
            self.assertIn("Marked applied: Org A", step(app, FakeSender(), clock, "applied to org a"))
            rows = {r["organisation"]: r for r in tracker.list_apps(conn)}
            self.assertEqual(set(rows), {"Org A", "Org B"})                                   # scout's row was kept
            text = csv_path.read_text(encoding="utf-8")
            self.assertIn("Org B", text)
            self.assertIn("applied", text)                                                   # and the bot's change is in the file

    def test_applied_command_variants(self):
        conn = loaded()
        tracker.add(conn, "Google", "Intern")
        tracker.add(conn, "Google", "Researcher")
        app = build_app(conn)
        clock = at(14, 9)
        s = FakeSender()
        self.assertIn("More than one match", step(app, s, clock, "applied to google"))
        self.assertIn("Marked applied: Google, Researcher", step(app, s, clock, "applied 2 portal"))
        self.assertEqual(tracker.get(conn, 2)["method"], "portal")
        self.assertIn("already marked applied", step(app, s, clock, "applied 2"))
        self.assertIn("could not find", step(app, s, clock, "applied to nowhere"))
        self.assertEqual(router.parse("applied to Google").kind, "applied")


class ShowAndFocusTests(unittest.TestCase):
    def test_show_lets_her_read_a_draft_before_deciding(self):
        conn = loaded()
        a = outreach.queue_draft(conn, SPACE, FACTS)
        app = build_app(conn)
        reply = step(app, FakeSender(), at(14, 9), f"show {a}")
        self.assertIn("Dear Professor Mayank", reply)
        self.assertIn("Summer 2027 research internship enquiry", reply)
        self.assertIn("There is no item 99", step(app, FakeSender(), at(14, 9), "show 99"))

    def test_focus_mode_silences_everything_but_the_card_and_checkin(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        sender = FakeSender()
        clock = at(21, 20, 5)                                     # streak nudge time
        self.assertIn("Focus mode on", step(app, sender, clock, "focus"))
        before = len(sender.sent)
        runtime.tick(app, sender, FakeHttp(), cfg(), clock)
        self.assertEqual(len(sender.sent), before)                # the 8 pm nudge was skipped
        clock.advance(hours=1)                                    # 21:05, check-in still allowed
        runtime.tick(app, sender, FakeHttp(), cfg(), clock)
        self.assertTrue(any("Evening check-in" in m[2] for m in sender.sent))
        self.assertIn("Focus mode off", step(app, sender, clock, "focus"))


class RolloverTests(unittest.TestCase):
    def test_unfinished_study_rolls_forward_once_and_can_be_undone(self):
        conn = loaded()
        yesterday = D("2026-11-18")                               # 3 LeetCode + GATE + YouTube
        before_yesterday = planner.study_minutes(conn, yesterday)
        today_before = planner.study_minutes(conn, D("2026-11-19"))          # 300 minutes already planned
        moved = replan.rollover(conn, D("2026-11-19"))            # 19 Nov is a buffer day, no exam
        self.assertIn("Moved 2 unfinished items", moved)                      # only 60 minutes of room under the 360 cap
        self.assertEqual(planner.study_minutes(conn, D("2026-11-19")), today_before + 60)
        self.assertEqual(planner.study_minutes(conn, yesterday), before_yesterday - 60)
        self.assertIsNone(replan.rollover(conn, D("2026-11-19")))            # day is full: the rest stays missed
        replan.undo_last(conn)
        self.assertEqual(planner.study_minutes(conn, yesterday), before_yesterday)

    def test_never_rolls_onto_an_exam_day_and_never_moves_fixed_items(self):
        conn = loaded()
        self.assertIsNone(replan.rollover(conn, D("2026-11-16")))            # exam day
        conn.execute("UPDATE tasks SET movable = 0")
        self.assertIsNone(replan.rollover(conn, D("2026-11-19")))

    def test_job_runs_before_the_morning_card_in_the_same_tick(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        sender = FakeSender()
        runtime.tick(app, sender, FakeHttp(), cfg(), at(19, 7, 45))
        card = [m[2] for m in sender.sent if "Good morning" in m[2]][0]
        self.assertIn("LeetCode 7: Problem 7", card)               # yesterday's leftover is already in today's card


class DigestJobTests(unittest.TestCase):
    def test_digest_is_sent_only_when_the_scout_wrote_it_today(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tracker").mkdir()
            c = cfg(tmp)
            sender = FakeSender()
            now = datetime.now(IST)
            clock = FakeClock(now.replace(hour=9, minute=30).astimezone(timezone.utc))
            runtime.tick(app, sender, FakeHttp(), c, clock)
            self.assertFalse(any("Digest for" in m[2] for m in sender.sent))      # no file: nothing stale is sent
            (Path(tmp) / "tracker" / "DAILY_DIGEST.md").write_text("# T\n\nA fresh note\n", encoding="utf-8")
            conn.execute("DELETE FROM settings WHERE key = 'last_digest_date'")
            runtime.tick(app, sender, FakeHttp(), c, clock)
            self.assertTrue(any("Digest for" in m[2] and "A fresh note" in m[2] for m in sender.sent))


class ExamWeekCapTests(unittest.TestCase):
    def test_at_most_five_proactive_messages_a_day_during_exams(self):
        conn = loaded()
        app = build_app(conn, owner="555")
        sender = FakeSender()
        for k in range(8):
            from ca import outbox
            outbox.enqueue(conn, "555", f"m{k}", "proactive", now=at(17, 12).now())
        runtime.tick(app, sender, FakeHttp(), cfg(), at(17, 12))
        self.assertEqual(len([m for m in sender.sent if m[2].startswith("m")]), runtime.EXAM_WEEK_CAP)


if __name__ == "__main__":
    unittest.main()


class LiveCheckRegressionTests(unittest.TestCase):
    """Problems found by running against the real plan, tracker and model."""

    def test_same_opportunity_is_not_added_twice(self):
        conn = loaded()
        tracker.add(conn, "Science Academies (IAS/INSA/NASI)", "Summer Research Fellowship 2027", source_link="https://x.org/f")
        self.assertIsNotNone(tracker.find_similar(conn, "Science Academies", "Summer Research Fellow", ""))     # same organisation
        self.assertIsNotNone(tracker.find_similar(conn, "Other name", "Other role", "https://x.org/f/"))        # same link
        self.assertIsNone(tracker.find_similar(conn, "Google", "SWE Intern", "https://g.com"))

    def test_triage_prompt_carries_todays_date(self):
        from ca import triage
        model = FakeModel([json.dumps({"decision": "APPLY", "reason": "ok", "organisation": "O", "role": "R"})])
        triage.triage(model, "a post", "2026-11-14")
        self.assertIn("Today is 2026-11-14", model.prompts[0])

    def test_closed_opportunities_stay_out_of_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tracker").mkdir()
            (root / "tracker" / "opportunities.csv").write_text(
                "id,name,deadline,decision,status\n1,Old thing,2026-07-01 (closed),WATCH,watching\n2,Open thing,unknown,APPLY,preparing\n",
                encoding="utf-8")
            names = [r["name"] for r in digest.open_opportunities(root, D("2026-11-14"))]
        self.assertEqual(names, ["Open thing"])

    def test_done_ticks_a_tracker_next_action_when_no_task_matches(self):
        conn = loaded()
        tracker.add(conn, "Google", "SWE Intern", next_action="confirm on the official page", next_action_date="2026-11-14")
        app = build_app(conn)
        reply = step(app, FakeSender(), at(14, 9), "done google")
        self.assertIn("Cleared from your due list", reply)
        self.assertEqual(tracker.get(conn, 1)["next_action"], "")
