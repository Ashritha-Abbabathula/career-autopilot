"""Say which settings are filled in, without ever showing a value.

Run:  python -m ca.check_env
"""
from __future__ import annotations

from .config import Config, load_config

# (label, attribute, needed from which slice / for what)
CHECKS = [
    ("GEMINI_API_KEY", "gemini_api_key", "the model (slice CA-5)"),
    ("TELEGRAM_BOT_TOKEN", "telegram_bot_token", "sending and receiving Telegram messages (CA-7)"),
    ("TELEGRAM_OWNER_CHAT_ID", "telegram_owner_chat_id", "the only chat the bot will talk to (CA-7)"),
    ("LEETCODE_USER", "leetcode_user", "LeetCode reminders (CA-6)"),
    ("GITHUB_USER", "github_user", "GitHub reminders (CA-6)"),
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
