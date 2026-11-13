import os
import tempfile
import unittest

from ca.config import Config, load_config, parse_env_file

SECRET = "AIzaFAKE-secret-value-123456"


class ParseTests(unittest.TestCase):
    def test_comments_blanks_and_quotes(self):
        text = "# note\n\nA=1\nB = 'two words'\nC=\"x\"\nbad line\nD=\n"
        self.assertEqual(parse_env_file(text), {"A": "1", "B": "two words", "C": "x", "D": ""})


class LoadTests(unittest.TestCase):
    def test_defaults_when_nothing_is_set(self):
        cfg = load_config(env={}, env_file=None)
        self.assertEqual(cfg, Config())
        self.assertFalse(cfg.gemini_ready)

    def test_environment_overrides_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("TIMEZONE=UTC\nQUIET_START=22\n")
            cfg = load_config(env={"TIMEZONE": "Asia/Kolkata"}, env_file=path)
        self.assertEqual(cfg.timezone, "Asia/Kolkata")
        self.assertEqual(cfg.quiet_start, 22)

    def test_missing_file_is_fine(self):
        cfg = load_config(env={}, env_file="does-not-exist.env")
        self.assertEqual(cfg.db_path, "data/ca.sqlite")

    def test_models_list_and_phone_digits(self):
        cfg = load_config(env={"GEMINI_MODELS": " a , b ,", "OWNER_WHATSAPP": "+91 98765-43210"}, env_file=None)
        self.assertEqual(cfg.gemini_models, ("a", "b"))
        self.assertEqual(cfg.owner_whatsapp, "919876543210")

    def test_bad_number_error_never_contains_the_value(self):
        with self.assertRaises(ValueError) as ctx:
            load_config(env={"MODEL_DAILY_CALL_CAP": SECRET}, env_file=None)
        self.assertNotIn(SECRET, str(ctx.exception))


class RedactionTests(unittest.TestCase):
    def test_secrets_are_hidden_everywhere(self):
        cfg = load_config(env={"GEMINI_API_KEY": SECRET, "WHATSAPP_TOKEN": "tok-123",
                               "OWNER_WHATSAPP": "919876543210"}, env_file=None)
        shown = cfg.redacted()
        self.assertEqual(shown["gemini_api_key"], "set")
        self.assertEqual(shown["whatsapp_token"], "set")
        self.assertEqual(shown["whatsapp_app_secret"], "missing")
        self.assertEqual(shown["owner_whatsapp"], "set")
        text = repr(shown)
        for secret in (SECRET, "tok-123", "919876543210"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
