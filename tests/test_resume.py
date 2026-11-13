import copy
import json
import tempfile
import unittest
from pathlib import Path

from ca import facts, resume
from ca.facts import FactError

DATA = {
    "person": {"name": "Sample Person", "headline": "B.Tech student", "contact": ["person@example.org", "github.com/sample"]},
    "facts": {
        "sum": {"kind": "summary", "text": "Builds small ML and robotics projects.", "source": "owner", "verified": True},
        "sk1": {"kind": "skill", "text": "Python, C++", "source": "owner", "verified": True, "group": "Languages"},
        "b1": {"kind": "bullet", "text": "Wrote a pick-and-place pipeline with 10 passing tests.", "source": "repo", "verified": True},
        "b2": {"kind": "bullet", "text": "Led a three-person team.", "source": "owner", "verified": True},
        "edu": {"kind": "education", "text": "Example University, B.Tech, batch of 2028", "source": "owner", "verified": True},
        "cgpa": {"kind": "extra", "text": "CGPA 8.3", "source": "owner, semester unconfirmed", "verified": False},
    },
    "projects": {"p1": {"title": "Kitting Robot", "meta": "Python, ROS"}},
    "variants": {
        "software": {"summary": "sum", "skills": ["sk1"], "education": ["edu"],
                     "projects": [{"id": "p1", "bullets": ["b1", "b2"]}]},
        "with_cgpa": {"summary": "sum", "education": ["edu"], "extras": ["cgpa"]},
    },
}


def variant(**changes):
    d = copy.deepcopy(DATA)
    d["facts"].update(changes)
    return d


class RenderTests(unittest.TestCase):
    def test_renders_html_with_every_section(self):
        html = resume.render_resume(DATA, "software")
        for piece in ("<h1>Sample Person</h1>", "Languages: </b>Python, C++", "Kitting Robot", "<li>Led a three-person team.</li>", "Example University"):
            self.assertIn(piece, html)

    def test_text_is_escaped(self):
        d = variant(b2={"kind": "bullet", "text": "Built <script>alert(1)</script> & more", "source": "x", "verified": True})
        html = resume.render_resume(d, "software")
        self.assertNotIn("<script>", html)
        self.assertIn("&amp; more", html)

    def test_unverified_fact_blocks_the_render_unless_draft(self):
        with self.assertRaises(FactError) as ctx:
            resume.render_resume(DATA, "with_cgpa")
        self.assertIn("cgpa: not verified", str(ctx.exception))
        draft = resume.render_resume(DATA, "with_cgpa", allow_unverified=True)
        self.assertIn("[verify]", draft)

    def test_banned_phrases_block_the_render(self):
        for bad in ("Nationally shortlisted Smart India Hackathon project", "Smart India Hackathon 2025 finalist",
                    "Author of a published paper", "Patent application filed", "Built FailBox"):
            d = variant(b2={"kind": "bullet", "text": bad, "source": "x", "verified": True})
            with self.assertRaises(FactError, msg=bad):
                resume.render_resume(d, "software")
        self.assertEqual(facts.lint("Wrote an unpublished study"), [])        # "unpublished" is the allowed wording

    def test_unknown_variant_and_check_all(self):
        with self.assertRaises(FactError):
            resume.render_resume(DATA, "nope")
        report = resume.check_all(DATA)
        self.assertIsNone(report["software"])
        self.assertIn("cgpa", report["with_cgpa"])


class ValidateTests(unittest.TestCase):
    def test_unknown_references_are_refused(self):
        d = copy.deepcopy(DATA)
        d["variants"]["software"]["projects"][0]["bullets"].append("ghost")
        with self.assertRaises(FactError) as ctx:
            facts.validate(d)
        self.assertIn("ghost", str(ctx.exception))
        d = copy.deepcopy(DATA)
        d["variants"]["software"]["projects"][0]["id"] = "ghost_project"
        with self.assertRaises(FactError):
            facts.validate(d)

    def test_fact_without_a_source_is_refused(self):
        d = variant(b2={"kind": "bullet", "text": "Something", "source": "", "verified": True})
        with self.assertRaises(FactError):
            facts.validate(d)

    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "facts.json"
            good.write_text(json.dumps(DATA), encoding="utf-8")
            self.assertEqual(facts.load(good)["person"]["name"], "Sample Person")
            with self.assertRaises(FactError):
                facts.load(Path(tmp) / "missing.json")
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(FactError):
                facts.load(bad)


if __name__ == "__main__":
    unittest.main()
