# Backlog: Career Autopilot
Sprint length: about 1 week while building (one slice a day). Story = one small, working, committable piece.
Definition of done for a story: it runs, it has a test or a visible result, it is committed with a clear message, README/DECISIONS updated if something changed.
Full plan with dates: the private notes repo, `notebooks/09-career-autopilot/IMPLEMENTATION_PLAN.md`.

## Sprint 1: the core loop in the simulator (14 to 20 Nov)
**CA-1 (Fri 13 Nov, done early)**
- [x] S1-1  Scaffold: README, idea, backlog, decisions, `.env.example`, `.gitignore`
- [x] S1-2  Skills radar module with tests
- [x] S1-3  Settings loader that never prints secrets, with tests
- [x] S1-4  SQLite schema (tasks, events, applications, facts, approvals, messages, model calls, settings) with tests

**CA-2**
- [ ] S1-5  Local chat simulator `python -m ca.chat`
- [ ] S1-6  Router for menu words (today, week, apps, inbox, pause, undo)
- [ ] S1-7  Approval queue, pause, undo, message log; test: nothing sends while paused

**CA-3**
- [ ] S1-8  Applications tracker module, `apps` command
- [ ] S1-9  CSV and Excel export; import the four starter rows
- [ ] S1-10 Deadline reminders (SRFP first)

**CA-4**
- [ ] S1-11 Parse the 90-day plan HTML into the database
- [ ] S1-12 Morning plan card
- [ ] S1-13 Tests for FAT days and empty days

**CA-5**
- [ ] S1-14 Replan engine (rules first)
- [ ] S1-15 Gemini client with fallback list, daily cap, usage log, fake model for tests
- [ ] S1-16 Natural-language intent layer + undo of every change

**CA-6**
- [ ] S1-17 Scheduler (7:30 card, 9 pm check-in, nudges)
- [ ] S1-18 LeetCode public-stats check (HTTP mocked in tests)
- [ ] S1-19 GitHub activity check (HTTP mocked in tests)

## Sprint 2: WhatsApp and the application machine (23 Nov to 2 Dec)
CA-7 to CA-14 as in the plan: webhook and hosting decision, facts file and resume variants, link triage, opportunity digest, inbox summary job, outreach drafts, buttons and weekly scorecard, hardening.

## Later / ideas
- Own Google credentials so inbox work does not need the Claude app
- Voice notes in
- Move to a free cloud host
