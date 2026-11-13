import unittest

from ca.check_env import report
from ca.config import load_config

SECRETS = ["AIzaFAKE-key-123456", "tok-abc-999", "app-secret-xyz", "verify-me-please", "919876543210"]


class CheckEnvTests(unittest.TestCase):
    def test_empty_settings_are_reported_missing(self):
        text = report(load_config(env={}, env_file=None))
        self.assertIn("MISSING", text)
        self.assertIn("6 setting(s) still to fill in.", text)

    def test_filled_settings_are_set_and_values_never_shown(self):
        cfg = load_config(env={
            "GEMINI_API_KEY": SECRETS[0], "WHATSAPP_TOKEN": SECRETS[1], "WHATSAPP_PHONE_ID": "12345",
            "WHATSAPP_APP_SECRET": SECRETS[2], "WHATSAPP_VERIFY_TOKEN": SECRETS[3],
            "OWNER_WHATSAPP": SECRETS[4]}, env_file=None)
        text = report(cfg)
        self.assertIn("All settings are filled in.", text)
        self.assertNotIn("MISSING", text)
        for value in SECRETS + ["12345"]:
            self.assertNotIn(value, text)

    def test_old_phone_variable_name_still_works(self):
        cfg = load_config(env={"WHATSAPP_PHONE_NUMBER_ID": "777"}, env_file=None)
        self.assertEqual(cfg.whatsapp_phone_number_id, "777")


if __name__ == "__main__":
    unittest.main()
