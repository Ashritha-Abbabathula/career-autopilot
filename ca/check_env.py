"""Say which settings are filled in, without ever showing a value.

Run:  python -m ca.check_env
"""
from __future__ import annotations

from .config import Config, load_config

# (label, attribute, needed from which slice / for what)
CHECKS = [
    ("GEMINI_API_KEY", "gemini_api_key", "the model (slice CA-5)"),
    ("WHATSAPP_TOKEN", "whatsapp_token", "sending WhatsApp messages (CA-7)"),
    ("WHATSAPP_PHONE_ID", "whatsapp_phone_number_id", "sending WhatsApp messages (CA-7)"),
    ("WHATSAPP_APP_SECRET", "whatsapp_app_secret", "checking incoming WhatsApp messages are really from Meta (CA-7)"),
    ("WHATSAPP_VERIFY_TOKEN", "whatsapp_verify_token", "Meta's webhook handshake (CA-7)"),
    ("OWNER_WHATSAPP", "owner_whatsapp", "the only number the bot will talk to (CA-7)"),
]


def report(cfg: Config) -> str:
    lines = []
    for label, attr, why in CHECKS:
        state = "set" if getattr(cfg, attr) else "MISSING"
        lines.append(f"{label:<24} {state:<8} needed for {why}")
    missing = sum(1 for _, attr, _ in CHECKS if not getattr(cfg, attr))
    lines.append("")
    lines.append("All settings are filled in." if missing == 0 else f"{missing} setting(s) still to fill in.")
    return "\n".join(lines)


def main() -> None:
    print(report(load_config()))


if __name__ == "__main__":
    main()
