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
