import json
import unittest
from datetime import date, datetime, timezone

from ca import db, intents, planner
from ca.chat import build_app, step
from ca.clock import FakeClock
from ca.llm import FakeModel, ModelError
from ca.senders import FakeSender
from tests.test_planner import PLAN, SETTINGS

TODAY = date(2026, 11, 18)


def answer(action, args=None, confidence=0.9, question=""):
    return json.dumps({"action": action, "args": args or {}, "confidence": confidence, "question": question})


def run(model_answer, text="whatever"):
    return intents.interpret(FakeModel([model_answer]), text, TODAY, ["LeetCode 7: Problem 7"])


class ParseTests(unittest.TestCase):
    def test_valid_requests_become_commands(self):
        i = run(answer("push", {"task": "gate", "to": "tomorrow"}), "move gate to tmrw")
        self.assertEqual((i.command.kind, i.command.args), ("push", {"task": "gate", "to": "tomorrow"}))
        i = run(answer("free_hours", {"hours": "2.5"}))
        self.assertEqual(i.command.args, {"hours": 2.5})
        self.assertEqual(run(answer("show_today")).command.kind, "today")
        self.assertEqual(run(answer("done", {"task": "leetcode"})).command.kind, "done")
        self.assertEqual(run(answer("skip", {"task": "youtube"})).command.kind, "skip_task")

    def test_doubt_becomes_a_question_never_an_action(self):
        self.assertIn("Which", run(answer("done", {"task": "x"}, 0.4, "Which task?")).ask)
        self.assertIsNone(run(answer("done", {"task": "x"}, 0.4)).command)
        self.assertIsNone(run(answer("done", {})).command)                          # missing argument
        self.assertIsNone(run(answer("push", {"task": "gate"})).command)           # missing "to"
        self.assertIsNone(run(answer("free_hours", {"hours": "lots"})).command)
        self.assertIsNone(run(answer("free_hours", {"hours": 40})).command)
        self.assertIsNone(run(answer("delete_everything", {"task": "all"})).command)   # not an allowed action
        self.assertIsNone(run("not json at all").command)
        self.assertIsNone(run(json.dumps({"action": "done", "args": {"task": "a"}, "confidence": "high"})).command)

    def test_none_action_is_plain_free_text(self):
        i = run(answer("none"), "how are you")
        self.assertEqual(i.command.kind, "free_text")

    def test_model_failure_is_reported_not_raised(self):
        i = intents.interpret(FakeModel([ModelError("down for now")]), "x", TODAY, [])
        self.assertTrue(i.failed)
        self.assertEqual(i.ask, "down for now")

    def test_prompt_contains_tasks_and_no_extra_data(self):
        model = FakeModel([answer("none")])
        intents.interpret(model, "hello", TODAY, ["Task A"])
        self.assertIn("- Task A", model.prompts[0])
        self.assertIn("2026-11-18", model.prompts[0])


class ChatTests(unittest.TestCase):
    def test_free_text_runs_through_the_normal_handler(self):
        conn = db.connect(":memory:")
        db.init_schema(conn)
        planner.import_plan(conn, PLAN, SETTINGS)
        model = FakeModel([answer("push", {"task": "gate", "to": "tomorrow"}), answer("none"),
                           answer("done", {"task": "leetcode"}, 0.3, "Which one did you finish?")])
        app = build_app(conn)
        app.model = model
        clock = FakeClock(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc))
        s = FakeSender()
        self.assertIn("Moved to Thu 19 Nov", step(app, s, clock, "can you shift the gate stuff to tomorrow"))
        self.assertIn("did not understand", step(app, s, clock, "what is the weather"))
        self.assertEqual(step(app, s, clock, "i did some lc"), "Which one did you finish?")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
