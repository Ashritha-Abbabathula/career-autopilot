import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ca import approvals, db, linkedin, mentor, outreach, runtime, scheduler, tracker
from ca.chat import build_app
from ca.clock import IST, FakeClock
from ca.config import load_config
from ca.http import FakeHttp
from ca.llm import FakeModel, ModelError
from ca.senders import FakeSender
from tests.test_nudges import lc_reply
from tests.test_outreach import DATA as OUTREACH_FACTS, SPACE


def fresh():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


class MentorTests(unittest.TestCase):
    def test_exam_weeks_are_short_and_kind(self):
        text = mentor.weekly_note(fresh(), date(2026, 11, 22), 100, 0)
        self.assertIn("Exam stretch", text)
        self.assertLess(len(text), 300)

    def test_normal_week_names_real_numbers_and_one_new_field(self):
        conn = fresh()
        conn.execute("INSERT INTO tasks (title, kind, planned_date, status, created_at) VALUES ('a','dsa','2026-12-14','done','t')")
        conn.execute("INSERT INTO tasks (title, kind, planned_date, status, created_at) VALUES ('b','gate','2026-12-15','done','t')")
        text = mentor.weekly_note(conn, date(2026, 12, 20), 100, 0)
        self.assertIn("2 things done (1 dsa, 1 gate)", text)
        self.assertIn("LeetCode is about", text)
        self.assertIn("Cloud and DevOps", text)
        self.assertIn("applications and outreach are at 0", text)

    def test_quiet_week_is_honest_not_shaming(self):
        text = mentor.weekly_note(fresh(), date(2027, 1, 17), None, None)
        self.assertIn("can't see anything ticked off", text)
        self.assertNotIn("LeetCode is about", text)                      # unknown stays unknown
        self.assertIn("Open source", text)


GOOD_POST = ("Last year I wanted a device that could tell rescuers someone was alive under rubble, not just that something was heavy. "
             "So I built a transmitter and receiver pair that only raises an alert when pressure, a fall and a body signal all agree. "
             "That rule cut false alarms compared with using one sensor alone. "
             "[ADD ONE REAL NUMBER OR MOMENT FROM YOUR OWN WORK] "
             "The code is open source under the MIT licence. github.com/example/project "
             "What would you test before trusting a rescue sensor?")


class LinkedInTests(unittest.TestCase):
    ENTRY = {"post_date": "2026-12-08", "project": "Buried Survivor Detector", "facts": ["bs1", "bs2"], "link": "github.com/example/project"}
    DATA = {"facts": {"bs1": {"text": "Wrote firmware for a sensor-fusion rescue system.", "verified": True},
                      "bs2": {"text": "Sent GPS over 433 MHz RF.", "verified": True}}}

    def test_due_window(self):
        sched = [self.ENTRY]
        self.assertIsNone(linkedin.due_entry(sched, date(2026, 11, 30)))
        self.assertEqual(linkedin.due_entry(sched, date(2026, 12, 1))["project"], "Buried Survivor Detector")
        self.assertIsNone(linkedin.due_entry(sched, date(2026, 12, 9)))

    def test_draft_saved_once_and_prompt_uses_only_listed_facts(self):
        model = FakeModel([json.dumps({"post": GOOD_POST})])
        with tempfile.TemporaryDirectory() as tmp:
            sched = Path(tmp) / "schedule.json"
            sched.write_text(json.dumps([self.ENTRY]), encoding="utf-8")
            text = linkedin.job(None, model, self.DATA, sched, Path(tmp) / "drafts", date(2026, 12, 2))
            self.assertIn("LinkedIn draft for Buried Survivor Detector", text)
            self.assertEqual(len(list((Path(tmp) / "drafts").glob("*.txt"))), 1)
            self.assertIn("Sent GPS over 433 MHz RF.", model.prompts[0])
            self.assertIsNone(linkedin.job(None, model, self.DATA, sched, Path(tmp) / "drafts", date(2026, 12, 3)))   # not again

    def test_failures_are_reported_and_nothing_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = Path(tmp) / "schedule.json"
            sched.write_text(json.dumps([self.ENTRY]), encoding="utf-8")
            for answer in (ModelError("down"), "not json", json.dumps({"post": "too short"}),
                           json.dumps({"post": GOOD_POST + " Our study is published in a journal."})):
                text = linkedin.job(None, FakeModel([answer]), self.DATA, sched, Path(tmp) / "d", date(2026, 12, 2))
                self.assertIn("couldn't write the LinkedIn draft", text)
            self.assertFalse((Path(tmp) / "d").exists())

    def test_no_verified_facts_means_no_draft(self):
        unverified = {"facts": {"bs1": {"text": "x", "verified": False}, "bs2": {"text": "y", "verified": False}}}
        with self.assertRaises(ValueError):
            linkedin.make_draft(FakeModel([json.dumps({"post": GOOD_POST})]), self.ENTRY, unverified)
        self.assertEqual(linkedin.load_schedule("nowhere.json"), [])


class SchedulerTests(unittest.TestCase):
    def test_new_jobs_fire_on_their_days(self):
        done = {"morning_card": "2026-12-15", "checkin": "", "streak_nudge": ""}
        self.assertIn("outreach_queue", scheduler.due_jobs(datetime(2026, 12, 15, 11, 0), done))        # a Tuesday
        self.assertNotIn("outreach_queue", scheduler.due_jobs(datetime(2026, 12, 16, 11, 0), done))
        self.assertIn("mentor", scheduler.due_jobs(datetime(2026, 12, 20, 19, 30), {}))                  # a Sunday
        self.assertIn("linkedin_draft", scheduler.due_jobs(datetime(2026, 12, 16, 9, 30), {}))


class OutreachQueueTests(unittest.TestCase):
    def targets_csv(self, tmp):
        p = Path(tmp) / "t.csv"
        p.write_text("id,name,institution,topic_match,evidence,official_email_source,status\n"
                     "1,Prateek Mayank,IIT A,solar flare prediction,2023: A Paper (doi 1),https://iit.example/faculty,candidate\n"
                     "2,Asha Rao,IIT B,embedded systems,,the faculty page,candidate\n"
                     "3,Sam Roy,IIT C,embedded systems,,,verified\n"
                     "4,Done Already,IIT D,embedded systems,,https://x,candidate\n", encoding="utf-8")
        return p

    def test_selection_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = outreach.select_targets(self.targets_csv(tmp), 5, skip_ids=["4"])
        self.assertEqual([r["id"] for r in rows], ["1", "3"])             # no official URL and not verified: left out

    def test_weekly_job_queues_drafts_once_and_tells_her(self):
        conn = fresh()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "facts").mkdir()
            (root / "tracker").mkdir()
            full = dict(OUTREACH_FACTS, person={}, projects={}, variants={})
            (root / "facts" / "facts.json").write_text(json.dumps(full), encoding="utf-8")
            (root / "tracker" / "outreach_targets.csv").write_text(self.targets_csv(tmp).read_text(encoding="utf-8"), encoding="utf-8")
            cfg = load_config(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "555", "CA_PRIVATE_DIR": str(root)}, env_file=None)
            app = build_app(conn, owner="555")
            sender = FakeSender()
            clock = FakeClock(datetime(2026, 12, 15, 11, 0, tzinfo=IST).astimezone(timezone.utc))      # Tuesday
            runtime.tick(app, sender, FakeHttp(), cfg, clock)
            # facts fixture has no 'bs1' variant issue: both targets draft, space one first
            queued = [r for r in approvals.pending(conn)]
            self.assertGreaterEqual(len(queued), 1)
            self.assertIn("professor email draft", sender.sent[-1][2])
            first_count = len(queued)
            clock.advance(days=7)
            runtime.tick(app, sender, FakeHttp(), cfg, clock)
            self.assertEqual(len(approvals.pending(conn)), first_count)                               # no duplicates next week


if __name__ == "__main__":
    unittest.main()
