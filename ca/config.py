"""Settings for Career Autopilot.

Reads environment variables and an optional .env file (the environment wins).
Secrets are never printed: use Config.redacted() whenever settings go into a
log or a chat message. Error messages never contain a setting's value.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields
from typing import Mapping, Optional

SECRET_FIELDS = {"gemini_api_key", "whatsapp_token", "whatsapp_app_secret", "whatsapp_verify_token", "telegram_bot_token"}
# Not secret, but personal: shown only as set or missing.
PERSONAL_FIELDS = {"owner_whatsapp", "telegram_owner_chat_id", "leetcode_user", "github_user", "private_dir"}


def parse_env_file(text: str) -> dict:
    """Parse KEY=VALUE lines. Ignores blanks and # comments; strips matching quotes."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        # Never include the value in the message: it could be a secret typed in the wrong line.
        raise ValueError(f"setting {key} must be a whole number") from None


@dataclass(frozen=True)
class Config:
    gemini_api_key: str = ""
    gemini_models: tuple = ("gemini-flash-lite-latest", "gemini-3.8-flash")
    model_daily_call_cap: int = 150
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    owner_whatsapp: str = ""
    db_path: str = "data/ca.sqlite"
    timezone: str = "Asia/Kolkata"
    quiet_start: int = 23
    quiet_end: int = 7
    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""
    private_dir: str = "../notebooks/09-career-autopilot"
    leetcode_user: str = ""
    github_user: str = ""
    daily_proactive_cap: int = 8
    calendar_port: int = 8765

    def redacted(self) -> dict:
        """Settings safe to log: secrets become 'set' or 'missing', nothing partial."""
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in SECRET_FIELDS:
                out[f.name] = "set" if value else "missing"
            elif f.name in PERSONAL_FIELDS:
                out[f.name] = "set" if value else "missing"
            else:
                out[f.name] = value
        return out

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_owner_chat_id)


def load_config(env: Optional[Mapping[str, str]] = None, env_file: Optional[str] = ".env") -> Config:
    """Environment variables override the .env file. A missing file is fine."""
    values: dict = {}
    if env_file and os.path.isfile(env_file):
        with open(env_file, encoding="utf-8") as f:
            values.update(parse_env_file(f.read()))
    values.update(os.environ if env is None else env)

    models = tuple(m.strip() for m in values.get("GEMINI_MODELS", "").split(",") if m.strip())
    defaults = Config()
    return Config(
        gemini_api_key=values.get("GEMINI_API_KEY", ""),
        gemini_models=models or defaults.gemini_models,
        model_daily_call_cap=_int(values, "MODEL_DAILY_CALL_CAP", defaults.model_daily_call_cap),
        whatsapp_token=values.get("WHATSAPP_TOKEN", ""),
        # Same name as PingFarm's .env so the value can be copied across; the longer name still works.
        whatsapp_phone_number_id=values.get("WHATSAPP_PHONE_ID", "") or values.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        whatsapp_app_secret=values.get("WHATSAPP_APP_SECRET", ""),
        whatsapp_verify_token=values.get("WHATSAPP_VERIFY_TOKEN", ""),
        owner_whatsapp=re.sub(r"\D", "", values.get("OWNER_WHATSAPP", "")),
        db_path=values.get("CA_DB_PATH", "") or defaults.db_path,
        timezone=values.get("TIMEZONE", "") or defaults.timezone,
        quiet_start=_int(values, "QUIET_START", defaults.quiet_start),
        quiet_end=_int(values, "QUIET_END", defaults.quiet_end),
        telegram_bot_token=values.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_owner_chat_id=re.sub(r"[^0-9-]", "", values.get("TELEGRAM_OWNER_CHAT_ID", "")),
        private_dir=values.get("CA_PRIVATE_DIR", "") or defaults.private_dir,
        leetcode_user=values.get("LEETCODE_USER", "").strip(),
        github_user=values.get("GITHUB_USER", "").strip(),
        daily_proactive_cap=_int(values, "DAILY_PROACTIVE_CAP", defaults.daily_proactive_cap),
        calendar_port=_int(values, "CALENDAR_PORT", defaults.calendar_port),
    )
