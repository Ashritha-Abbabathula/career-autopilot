import tempfile
import unittest
from datetime import date
from pathlib import Path

from ca import approvals, db, outreach
from ca.approvals import ApprovalError, Executors
from ca.facts import FactError
from ca.outreach import DraftError

DATA = {"facts": {
    "edu_vit": {"kind": "education", "text": "Example University: B.Tech, batch of 2028", "source": "owner", "verified": True},
    "hel1": {"kind": "bullet", "text": "Designed a Random Forest ensemble over payload data.", "source": "owner", "verified": True},
    "bs1": {"kind": "bullet", "text": "Wrote firmware for a sensor-fusion rescue system.", "source": "owner", "verified": True},
}}
SPACE = {"id": "1", "name": "Prateek Mayank", "institution": "IIT Example", "topic_match": "solar flare prediction",
         "evidence": "2023: Solar Flare Prediction Using Boosting (doi 10.1/abc)", "official_email_source": "the faculty page"}
OTHER = {"id": "2", "name": "Asha Rao", "institution": "IIT Other", "topic_match": "embedded systems", "evidence": ""}


class DraftTests(unittest.TestCase):
    def test_space_target_uses_the_space_project_and_quotes_the_paper(self):
        d = outreach.draft_professor_email(SPACE, DATA)
        self.assertIn("Dear Professor Mayank", d["body"])
        self.assertIn("Solar Flare Prediction Using Boosting", d["body"])
        self.assertNotIn("10.1/abc", d["body"])                            # the DOI itself is not pasted into the letter
        self.assertIn("designed a Random Forest ensemble", d["body"])
        self.assertIn("Find the address on the official page", d["to_note"])
        self.assertTrue(outreach.has_marker(d["body"]))                    # her own line is left for her

    def test_other_target_without_evidence_makes_no_claim_about_a_paper(self):
        d = outreach.draft_professor_email(OTHER, DATA)
        self.assertNotIn("I read your work", d["body"])
        self.assertIn("firmware", d["body"])

    def test_refuses_what_it_cannot_do_honestly(self):
        with self.assertRaises(DraftError):
            outreach.draft_professor_email({"name": "", "topic_match": "x"}, DATA)
        unverified = {"facts": dict(DATA["facts"], hel1=dict(DATA["facts"]["hel1"], verified=False))}
        with self.assertRaises(DraftError):
            outreach.draft_professor_email(SPACE, unverified)
        banned = {"facts": dict(DATA["facts"], hel1=dict(DATA["facts"]["hel1"], text="Author of a published paper."))}
        with self.assertRaises(FactError):
            outreach.draft_professor_email(SPACE, banned)
        with self.assertRaises(DraftError):
            outreach.draft_professor_email(SPACE, {"facts": {k: v for k, v in DATA["facts"].items() if k != "hel1"}})


class ApprovalFlowTests(unittest.TestCase):
    def test_draft_waits_for_a_finished_text_then_is_saved_never_sent(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        with tempfile.TemporaryDirectory() as tmp:
            ex = Executors(run={"email_draft": outreach.make_executor(tmp, lambda: date(2026, 11, 20))})
            a = outreach.queue_draft(conn, SPACE, DATA)
            with self.assertRaises(ApprovalError) as ctx:                  # placeholders still there
                approvals.approve(conn, a, ex)
            self.assertIn("placeholder", str(ctx.exception))
            self.assertEqual(approvals.get(conn, a)["status"], "pending")
            approvals.edit(conn, a, "Dear Professor Mayank, a finished letter with no placeholders.")
            message = approvals.approve(conn, a, ex)
            files = list((Path(tmp) / "ready").glob("*.txt"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].name.startswith("2026-11-20-1-"))
            text = files[0].read_text(encoding="utf-8")
            self.assertIn("Subject: Summer 2027 research internship enquiry", text)
            self.assertIn("a finished letter", text)
            self.assertIn("never send", message.replace("I never send", "never send"))
            self.assertEqual(approvals.get(conn, a)["status"], "approved")


if __name__ == "__main__":
    unittest.main()
