---
id: 007
title: Silver Tier Gmail and WhatsApp Watchers
stage: general
date: 2026-03-29
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: danish
command: create gmail_watcher.py whatsapp_watcher.py base_watcher.py
labels: ["silver-tier", "gmail", "whatsapp", "playwright", "watcher", "agent-skill"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - watchers/gmail_watcher.py
  - watchers/whatsapp_watcher.py
  - base_watcher.py
  - watchers/__init__.py
tests:
  - none
---

## Prompt

You are building my Silver Tier Personal AI Employee.

Create these 3 Python files in my project root:

1. base_watcher.py (exact code from the hackathon document)
2. gmail_watcher.py (use Gmail API, credentials.json se load karo, Needs_Action mein EMAIL_*.md banao)
3. whatsapp_watcher.py (Playwright se, keywords: urgent, invoice, payment, pricing, asap)

Vault path use karo: current working directory.
Logging aur error handling rakho.
Sab files Agent Skill style mein banao taake main Claude se directly call kar saku.

## Response snapshot

Created 3 files for Silver Tier watcher system:

1. `base_watcher.py` (project root) — re-exports from `watchers/base_watcher.py` for standalone use
2. `watchers/gmail_watcher.py` — OAuth2 Gmail API watcher; polls INBOX for UNREAD emails every 60s; writes `EMAIL_<id>.md` to `Needs_Action/`; persists seen IDs in `Logs/gmail_seen_ids.json`; supports `--once`, `--interval`, `--max-results` flags
3. `watchers/whatsapp_watcher.py` — Playwright Chromium watcher; scans unread chats every 30s for keywords (urgent, invoice, payment, pricing, asap); writes `WHATSAPP_<chat>_<ts>.md` to `Needs_Action/`; persistent browser profile at `Logs/whatsapp_profile/`; supports `--once`, `--setup`, `--headless` flags
4. Updated `watchers/__init__.py` to export all 4 watchers

## Outcome

- Impact: Silver Tier now has Gmail and WhatsApp inbox monitoring with keyword filtering routing to Needs_Action vault folder
- Tests: none run (integration watchers require live credentials)
- Files: 4 files created/updated
- Next prompts: Run `--setup` for WhatsApp QR login; configure `credentials.json` for Gmail OAuth; wire watchers into `main.py` orchestrator
- Reflection: Used persistent browser profile pattern for WhatsApp to avoid QR scan on every run; Gmail watcher uses local seen-IDs JSON for dedup across restarts

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment: Add Claude AI summarization step before writing Needs_Action notes
