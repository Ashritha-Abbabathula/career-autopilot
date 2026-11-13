# Career Autopilot (work in progress)

A personal WhatsApp assistant for one person: daily plan and calendar, replanning by text, application tracker, tailored resume drafts, inbox summary and outreach drafts. **Everything that goes out in the owner's name waits for her approval.** The running bot uses the free Gemini API.

**Status (2026-11-13):** slice CA-1 done (project scaffold, skills radar, settings loader, database schema). Not yet built: chat simulator, planner, WhatsApp webhook, resumes, triage. See `BACKLOG.md`.

## What exists now
- `radar/`: counts which skills appear in public job postings (Greenhouse, Lever and Ashby job-board APIs) for India-based tech roles and compares them with the owner's resumes.
- `ca/config.py`: settings from environment variables or a `.env` file; secrets are never printed (`Config.redacted()`).
- `ca/db.py`: SQLite schema (tasks, events, applications, facts, approvals, messages, model calls, settings), a kill switch, an approval lifecycle and a daily model-call cap.

## Run the tests
```
python -m unittest discover -s tests
```
(Python 3.12, standard library only so far.)

## Run the skills radar
```
python -m radar.run --companies data/companies.txt --paste data/paste --out out
```
Add company boards to `data/companies.txt`. Text you collected yourself goes in `data/paste/*.txt` (kept local, git-ignored). Reports land in `out/`.

## Results so far (from the first run, 2026-11-13)
60 company boards tried, 37 answered, 368 India tech postings kept (276 senior, 85 mid, 6 intern, 1 entry-level). For the 92 non-senior postings the most-asked skills were Python (43%), AWS (36%), scalable systems (35%), LLMs (34%), testing (34%) and agents (30%). **These are keyword counts on a small, senior-heavy sample, not a measure of the whole market.**

## Not included, on purpose
No LinkedIn or Reddit scraping or automation, no automatic applying, no bot-detection evasion. See `DECISIONS.md`.

## Known limits and untested parts
- Job level (intern, entry, mid, senior) is guessed from the title only.
- Skill detection is keyword matching, so it can over- or under-count.
- Nothing has been run against real WhatsApp or Gemini yet; those need the owner's keys.
- The free Gemini tier has quotas and its data terms can change.

## How this was built
Built with Claude's help as a learning project. Plain-English study notes live in the owner's private notes repo.
