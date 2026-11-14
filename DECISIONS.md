# Decisions

| # | Decision | Options considered | Why | What would change it |
|---|---|---|---|---|
| D1 | Free Gemini API for the running bot | Paid Claude API; Gemini free tier | The owner does not want to pay for an API; Gemini already passed the key check in PingFarm | Free quota disappears or quality is too low: swap the provider (the code uses a small interface) |
| D2 | Claude (the owner's app plan) builds; the bot runs on Gemini | Claude for both | Uses each where it costs nothing extra | Owner decides to pay for an API |
| D3 | WhatsApp only, no Telegram | Telegram first | Owner's decision | Meta setup blocks us for long: keep the local simulator as the fallback, not Telegram |
| D4 | Build and test through a local chat simulator first | WhatsApp first | WhatsApp needs Meta values and a stable public address; the simulator needs nothing | Never: the simulator stays as a test tool |
| D5 | SQLite, standard library first | Postgres, ORM | One user, one laptop, no extra setup | More than one user or a hosted database |
| D6 | Human approves everything outward | Automatic sending | Reputation and safety; the owner's name is on every message | Narrow categories can go automatic after a trial period, per category, by the owner's choice |
| D7 | No LinkedIn or Reddit automation | Scrapers | Terms of service and account risk | Official access becomes available |
| D8 | Settings loader reads `.env` itself and never prints values | python-dotenv | No extra dependency; redaction is tested | A library is clearly better |
| D10 | The bot never submits solutions or activity for the owner (no automatic LeetCode resubmission or filler commits to hold a streak). It may remind her and suggest which solved problem to revisit | Auto-resubmitting old solutions | A streak made by a bot is fake activity, breaks the site's terms, would need her login, and a recruiter who asks would find nothing real behind it | Never |
| D9 | This repo is public (from 2026-11-13) | Keep private | The owner wants it visible on her profile. Checked first: no secrets or personal data in files or history; only her usual commit email is visible. Her notes, resumes, tracker and plans stay in a separate private repo | A secret or personal detail ever appears: remove it, rotate the key, and consider making the repo private again |
| D11 | Telegram is the only chat channel (2026-11-13) | WhatsApp Cloud API | Meta account locked, business profile cannot be completed for India, tokens expire; Telegram needs only a free bot token, has no 24-hour window or templates, and long polling needs no public address | Telegram becomes unsuitable. The channel sits behind the Sender interface, so switching back is one module |
| D12 | The calendar is the owner's original 90-day page, run and saved by the bot (2026-11-14); no Google Calendar | Mirror into Google Calendar | She uses and wants her own page (Pomodoro, sticky notes, time log); one calendar means no two copies to keep in step, and no extra connector or login | She asks for phone-calendar alerts |
