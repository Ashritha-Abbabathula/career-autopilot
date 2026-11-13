import unittest
from datetime import datetime, timezone

from ca import db
from ca.http import FakeHttp
from ca.llm import CapReached, FakeModel, GeminiModel, ModelError, NoModel, extract_json

KEY = "fake-key-for-tests"
NOW = datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc)


def ok(text, p=11, o=7):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": p, "candidatesTokenCount": o}}


def make(http, cap=150, models=("model-a", "model-b")):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn, GeminiModel(KEY, models, http, conn, daily_cap=cap, now_fn=lambda: NOW)


class GeminiTests(unittest.TestCase):
    def test_success_logs_usage_and_keeps_key_out_of_the_url(self):
        http = FakeHttp().add(200, ok('{"a": 1}'))
        conn, model = make(http)
        self.assertEqual(model.generate("hi", "triage"), '{"a": 1}')
        call = http.calls[0]
        self.assertNotIn(KEY, call["url"])
        self.assertEqual(call["headers"]["x-goog-api-key"], KEY)
        self.assertIn("model-a", call["url"])
        row = conn.execute("SELECT * FROM model_calls").fetchone()
        self.assertEqual((row["model"], row["purpose"], row["prompt_tokens"], row["output_tokens"], row["ok"]),
                         ("model-a", "triage", 11, 7, 1))

    def test_falls_back_to_the_next_model_on_429_and_5xx(self):
        for bad in (429, 503, 0):
            http = FakeHttp().add(bad, "busy").add(200, ok("fine"))
            conn, model = make(http)
            self.assertEqual(model.generate("hi"), "fine")
            self.assertIn("model-b", http.calls[1]["url"])
            self.assertEqual([r["ok"] for r in conn.execute("SELECT ok FROM model_calls ORDER BY id")], [0, 1])

    def test_client_error_stops_without_trying_other_models(self):
        http = FakeHttp().add(403, "forbidden").add(200, ok("never used"))
        _, model = make(http)
        with self.assertRaises(ModelError):
            model.generate("hi")
        self.assertEqual(len(http.calls), 1)

    def test_all_models_failing_and_bad_bodies(self):
        http = FakeHttp().add(200, "not json").add(200, {"candidates": []})
        _, model = make(http)
        with self.assertRaises(ModelError) as ctx:
            model.generate("hi")
        self.assertNotIn(KEY, str(ctx.exception))

    def test_daily_cap_blocks_before_any_network_call(self):
        http = FakeHttp().add(200, ok("one")).add(200, ok("two"))
        _, model = make(http, cap=1)
        model.generate("hi")
        with self.assertRaises(CapReached):
            model.generate("again")
        self.assertEqual(len(http.calls), 1)

    def test_needs_a_key(self):
        with self.assertRaises(ValueError):
            GeminiModel("", ["m"], FakeHttp(), None)


class HelperTests(unittest.TestCase):
    def test_fake_and_no_model(self):
        fake = FakeModel(["a", ModelError("down"), lambda p: p.upper()])
        self.assertEqual(fake.generate("x"), "a")
        with self.assertRaises(ModelError):
            fake.generate("x")
        self.assertEqual(fake.generate("hey"), "HEY")
        with self.assertRaises(ModelError):
            fake.generate("empty now")
        with self.assertRaises(ModelError):
            NoModel().generate("x")

    def test_extract_json(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Sure! {"a": {"b": 2}} hope that helps'), {"a": {"b": 2}})
        self.assertIsNone(extract_json("[1, 2]"))
        self.assertIsNone(extract_json("no json here"))
        self.assertIsNone(extract_json(""))


if __name__ == "__main__":
    unittest.main()
