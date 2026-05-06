---
id: "004"
title: File System Watcher Bronze Tier
stage: general
date: 2026-03-09
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: DANISH LAPTOP
command: "Create complete ready-to-run File System Watcher for Bronze tier"
labels: ["filesystem-watcher","bronze-tier","polling","pathlib","obsidian"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - watchers/__init__.py
  - watchers/base_watcher.py
  - watchers/filesystem_watcher.py
tests:
  - manual: drop file in Inbox, verify FILE_ copy in Needs_Action
  - manual: verify .meta.md created with correct YAML frontmatter
  - manual: restart watcher, verify no duplicate processing
---

## Prompt

Create a complete, ready-to-run File System Watcher for Bronze tier.

Create these two files:

1. watchers/base_watcher.py
2. watchers/filesystem_watcher.py

Requirements:
- Use the BaseWatcher class pattern (abstract)
- Watch the folder "Inbox" inside the vault
- Jab koi bhi file Inbox mein drop ho, usko copy karo Needs_Action mein with prefix FILE_
- Create a .md metadata file
- Run every 10 seconds
- Proper logging
- Use pathlib

After creating both files, give me the exact command to run this watcher in background using PM2 (if PM2 installed) or simple nohup.

Finally say "File System Watcher ready for testing".

## Response snapshot

Created three files:
- `watchers/__init__.py` — package marker
- `watchers/base_watcher.py` — abstract BaseWatcher with setup_logging, stop(), _sleep()
- `watchers/filesystem_watcher.py` — concrete FileSystemWatcher polling Inbox every 10s, copying files with FILE_ prefix and generating .meta.md companion files in Needs_Action/

Run commands provided for PM2, nohup, and direct execution.

## Outcome

- Impact: Inbox is now auto-monitored; any dropped file is immediately routed to Needs_Action with metadata
- Tests: Manual drop test required; no unit tests written yet
- Files: watchers/base_watcher.py, watchers/filesystem_watcher.py, watchers/__init__.py
- Next prompts: Add email/webhook notification on file detection; add unit tests with tmp_path fixtures
- Reflection: Poll-based approach avoids watchdog dependency; restart-safe via dest-file existence check

## Evaluation notes (flywheel)

- Failure modes observed: none at creation time
- Graders run and results (PASS/FAIL): not yet run
- Prompt variant (if applicable): none
- Next experiment: add watchdog-based inotify variant for lower latency
