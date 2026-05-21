---
id: 008
title: Silver Tier LinkedIn Watcher Playwright
stage: general
date: 2026-03-29
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: danish
command: create linkedin_watcher.py playwright based
labels: ["silver-tier", "linkedin", "playwright", "watcher", "agent-skill"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - watchers/linkedin_watcher.py
  - watchers/__init__.py
tests:
  - none
---

## Prompt

Ab LinkedIn watcher bhi banao (Playwright based).
- LinkedIn homepage pe unread messages/notifications check karo
- Agar "sales", "inquiry", "proposal", "pricing" keyword ho toh Needs_Action mein LINKEDIN_*.md file banao
- Session reuse karo
File naam: linkedin_watcher.py

## Response snapshot

Created `watchers/linkedin_watcher.py` — Playwright Chromium LinkedIn watcher with:
- Persistent profile at `Logs/linkedin_profile/` for session reuse (no re-login)
- Scans two sources per poll: /messaging/ (unread threads) and /notifications/
- Keywords: sales, inquiry, proposal, pricing (word-boundary regex, case-insensitive)
- Writes `LINKEDIN_MESSAGE_<slug>_<ts>.md` or `LINKEDIN_NOTIFICATION_<slug>_<ts>.md` to Needs_Action/
- Dedup via `Logs/linkedin_seen.txt`
- `--setup` mode opens browser to login page and waits for manual login + 2FA
- `--headless`, `--once`, `--interval` flags
- Custom user-agent to avoid LinkedIn bot detection
- Updated `watchers/__init__.py` to export LinkedInWatcher

## Outcome

- Impact: Silver Tier now monitors LinkedIn messages and notifications for business-relevant keywords
- Tests: none (requires live LinkedIn session)
- Files: 2 files created/updated
- Next prompts: Run --setup to log in; wire into main.py orchestrator alongside Gmail/WhatsApp watchers
- Reflection: LinkedIn scraping requires persistent profile + real user-agent; split messaging vs notifications into separate scan methods for clarity

## Evaluation notes (flywheel)

- Failure modes observed: LinkedIn may update selectors — fallback selectors included for resilience
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment: Use LinkedIn API (if available) instead of scraping for more reliable data extraction
