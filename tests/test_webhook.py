import hashlib
import hmac
import json
import unittest

from ca import db
from ca.config import load_config
from ca.webhook import extract_text_messages, handle_post, valid_signature, verify_challenge

SECRET = "test-app-secret"
OWNER = "919876543210"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payload(sender: str, text: str = "hello", mtype: str = "text") -> bytes:
    msg = {"from": sender, "id": "wamid.1", "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": text}
    return json.dumps({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()


def setup(secret=SECRET, owner=OWNER):
    cfg = load_config(env={"WHATSAPP_APP_SECRET": secret, "OWNER_WHATSAPP": owner,
                           "WHATSAPP_VERIFY_TOKEN": "vt"}, env_file=None)
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return cfg, conn


class HandshakeTests(unittest.TestCase):
    def test_correct_token_echoes_challenge(self):
        p = {"hub.mode": ["subscribe"], "hub.verify_token": ["vt"], "hub.challenge": ["12345"]}
        self.assertEqual(verify_challenge(p, "vt"), "12345")

    def test_wrong_token_or_mode_is_refused(self):
        p = {"hub.mode": ["subscribe"], "hub.verify_token": ["nope"], "hub.challenge": ["1"]}
        self.assertIsNone(verify_challenge(p, "vt"))
        p2 = {"hub.mode": ["other"], "hub.verify_token": ["vt"], "hub.challenge": ["1"]}
        self.assertIsNone(verify_challenge(p2, "vt"))

    def test_no_configured_token_refuses_everything(self):
        p = {"hub.mode": ["subscribe"], "hub.verify_token": [""], "hub.challenge": ["1"]}
        self.assertIsNone(verify_challenge(p, ""))


class SignatureTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        body = b'{"a":1}'
        self.assertTrue(valid_signature(SECRET, body, sign(body)))
        self.assertFalse(valid_signature(SECRET, body, sign(body, "other-secret")))
        self.assertFalse(valid_signature(SECRET, body, ""))
        self.assertFalse(valid_signature(SECRET, body, "sha1=abc"))

    def test_fails_closed_without_a_secret(self):
        body = b"{}"
        self.assertFalse(valid_signature("", body, sign(body, "")))


class PostTests(unittest.TestCase):
    def test_owner_message_is_stored(self):
        cfg, conn = setup()
        body = payload(OWNER, "plan my day")
        self.assertEqual(handle_post(conn, cfg, body, sign(body)), (200, 1))
        row = conn.execute("SELECT direction, channel, body FROM messages").fetchone()
        self.assertEqual((row["direction"], row["channel"], row["body"]), ("in", "whatsapp", "plan my day"))

    def test_stranger_is_dropped_not_stored(self):
        cfg, conn = setup()
        body = payload("911111111111", "hi")
        self.assertEqual(handle_post(conn, cfg, body, sign(body)), (200, 0))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_bad_signature_is_rejected_and_nothing_stored(self):
        cfg, conn = setup()
        body = payload(OWNER)
        self.assertEqual(handle_post(conn, cfg, body, sign(body, "wrong"))[0], 403)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_no_app_secret_rejects_every_request(self):
        cfg, conn = setup(secret="")
        body = payload(OWNER)
        self.assertEqual(handle_post(conn, cfg, body, sign(body, ""))[0], 403)

    def test_broken_json_is_a_400(self):
        cfg, conn = setup()
        body = b"not json"
        self.assertEqual(handle_post(conn, cfg, body, sign(body))[0], 400)

    def test_non_text_message_is_stored_as_a_marker(self):
        cfg, conn = setup()
        body = payload(OWNER, mtype="image")
        handle_post(conn, cfg, body, sign(body))
        self.assertEqual(conn.execute("SELECT body FROM messages").fetchone()["body"], "[image message]")

    def test_extract_handles_empty_payload(self):
        self.assertEqual(extract_text_messages({}), [])


if __name__ == "__main__":
    unittest.main()
