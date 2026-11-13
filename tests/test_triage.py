import json
import unittest
from datetime import datetime, timezone

from ca import db, router, tracker, triage
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.llm import FakeModel, ModelError
from ca.senders import FakeSender

# Labelled examples for the rule layer. The rules only ever say SKIP, so we measure two things:
# every scam or fee example is caught, and no honest example is wrongly skipped.
MUST_SKIP = [
    "Summer internship! Registration fee of Rs. 999 to confirm your seat.",
    "Pay 2500 to join our training and get a guaranteed placement",
    "Earn Rs 5000 per day from home, no interview needed",
    "WhatsApp us to apply, limited seats left hurry",
    "Security deposit of Rs 1000 refundable after the internship",
    "Offer letter fee applies, certificate with lifetime validity",
    "Guaranteed job after our 3 month course, enrol now",
    "Processing fee payable before your selection is confirmed",
]
MUST_PASS = [
    "Science Academies Summer Research Fellowship 2027. Apply by 30 Nov. Stipend provided.",
    "ISRO URSC internship for B.Tech students. Apply on the official portal.",
    "Google STEP internship for second and third year students, Bengaluru.",
    "DRDO summer training, no fee, stipend as per norms.",
    "Hackathon: 36 hours, free entry, prizes worth 1 lakh.",
    "Research internship at IISc: write to the professor with your CV.",
    "Pay attention to the deadline: applications close 15 Dec.",
]


def good(**over):
    d = {"decision": "APPLY", "reason": "Open and fits.", "organisation": "Example Academy",
         "role": "Summer Fellow", "location": "Bengaluru", "deadline": "2026-11-30"}
    d.update(over)
    return json.dumps(d)


class RuleTests(unittest.TestCase):
    def test_scams_and_fees_are_caught(self):
        missed = [t for t in MUST_SKIP if triage.rule_check(t) is None]
        self.assertEqual(missed, [])

    def test_honest_posts_are_not_wrongly_skipped(self):
        wrong = [t for t in MUST_PASS if triage.rule_check(t) is not None]
        self.assertEqual(wrong, [])

    def test_rule_skip_never_calls_the_model(self):
        model = FakeModel([good()])
        v = triage.triage(model, MUST_SKIP[0])
        self.assertEqual((v.decision, v.by_rule), ("SKIP", True))
        self.assertEqual(model.prompts, [])


class ModelTests(unittest.TestCase):
    def test_valid_answer(self):
        v = triage.triage(FakeModel([good()]), "post text https://example.org/apply")
        self.assertEqual((v.decision, v.organisation, v.deadline, v.link), ("APPLY", "Example Academy", "2026-11-30", "https://example.org/apply"))

    def test_junk_is_handled_without_guessing(self):
        self.assertEqual(triage.triage(FakeModel(["nonsense"]), "x").decision, "MAYBE")
        self.assertEqual(triage.triage(FakeModel([good(decision="HIRE_NOW")]), "x").decision, "MAYBE")
        self.assertEqual(triage.triage(FakeModel([good(deadline="next friday")]), "x").deadline, "")
        v = triage.triage(FakeModel([ModelError("down")]), "x")
        self.assertEqual(v.decision, "MAYBE")
        self.assertIn("check it yourself", v.reason)

    def test_tracker_row_only_when_organisation_and_role_known(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        v = triage.triage(FakeModel([good(), good(), good(organisation="")]), "x")
        a = triage.add_to_tracker(conn, v, "2026-11-14")
        self.assertEqual(triage.add_to_tracker(conn, v, "2026-11-14"), a)         # same post again: no duplicate row
        self.assertEqual(len(tracker.list_apps(conn)), 1)
        self.assertIsNone(triage.add_to_tracker(conn, triage.triage(FakeModel([good(organisation="")]), "x"), "2026-11-14"))


class RouterAndChatTests(unittest.TestCase):
    def test_router(self):
        self.assertEqual(router.parse("https://example.org/job").kind, "triage")
        self.assertEqual(router.parse("check this out https://example.org/job").kind, "triage")
        self.assertEqual(router.parse("triage " + "a long pasted post " * 10).kind, "triage")
        self.assertEqual(router.parse("check").kind, "free_text")
        self.assertEqual(router.parse("done leetcode").kind, "done")

    def test_chat(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        app = build_app(conn)
        app.model = FakeModel([good()])
        clock = FakeClock(datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc))
        reply = step(app, FakeSender(), clock, "https://example.org/fellowship")
        self.assertIn("APPLY: Open and fits.", reply)
        self.assertIn("Saved to your tracker as #1", reply)
        self.assertEqual(tracker.get(conn, 1)["source_link"], "https://example.org/fellowship")


if __name__ == "__main__":
    unittest.main()
