# Career Autopilot: PROJECT_IDEA (what we started with; never deleted)

*Written 2026-11-13. Approved by the owner the same day.*

## What it is
A WhatsApp assistant for one person. You text it normally; it keeps your daily plan and calendar, reminds you, replans when you say things like "push today's DSA", tracks internship and fellowship applications, prepares tailored resumes and messages for you to send, summarises your application inbox, and nudges your LeetCode and GitHub habits. Anything that leaves your account waits for your one-tap approval.

## Why it is worth building
It removes the planning load during exams and gives a recruiter-checkable example of a tool-using agent with approvals, safety rules and tests.

## Smallest version (v1, 14 slices)
Chat (local simulator first, then WhatsApp), approvals, undo and a kill switch, application tracker with deadlines and Excel export, daily plan and replanning, resume variants from one facts file, link triage, opportunity digest, inbox summary, outreach drafts, weekly scorecard.

## Left out on purpose
LinkedIn or Reddit scraping and automation, fully automatic applying, Instagram posting, automatic pull requests, solving CAPTCHAs, handling passwords.

## Skills it covers
Agents and tool use, approval workflows, prompt design with a free model, FastAPI, scheduling, SQLite, testing with fake models, evaluation on labelled examples.

## Model
The free Gemini API for the running bot. Claude (the owner's own app) does the building.

## Honest limits
Free-tier quotas and data terms can change; the bot needs the owner's keys for Meta and Gemini; the first version runs on the owner's laptop.
