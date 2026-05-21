---
id: 001
title: Obsidian Workspace Setup
stage: general
date: 2026-03-09
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: user
command: natural language request
labels: ["obsidian","workspace","markdown","automation","python"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - Company_Handbook.md
 - Dashboard.md
 - setup_vault.py
 - history/prompts/general/001-obsidian-workspace-setup.general.prompt.md
tests:
 - none
---

## Prompt

Hey Claude, I need you to help me set up my Obsidian workspace. I have already planned the folder structure, and now I need you to generate the content for two specific files: Company_Handbook.md and Dashboard.md.

1. The Folder Structure (For Context):
Inbox, Needs_Action, Done, Pending_Approval, Approved, Rejected, Plans, Logs, Briefings.

2. Task - Generate File Content:

Company_Handbook.md: Create a professional handbook structure. Include sections for Mission, Core Values, the 'Folder Lifecycle' (how tasks move from Inbox to Done), and Communication Guidelines.

Dashboard.md: Create a 'Command Center' view. Include a 'High Priority' checklist, a status table for the different folders, and internal Obsidian links ([[ ]]) to the Handbook and Logs.

3. Bonus - Automation Script:
Please provide a simple Python script that I can run in my Obsidian vault folder to automatically create all 9 folders and these 2 Markdown files with the content you generated. This will save me from doing it manually!

## Response snapshot

Created three files:
- `Company_Handbook.md`: Professional handbook with Mission, Core Values, Folder Lifecycle table (all 9 folders with states and SLAs), and Communication Guidelines (written-first culture, SLA table, escalation path, language standards).
- `Dashboard.md`: Command Center with High Priority checklist, System Status table with emoji indicators, Quick Links using Obsidian `[[wikilinks]]`, lifecycle diagram, and a copy-paste daily log template.
- `setup_vault.py`: Python script that creates all 9 folders (with `.gitkeep` files) and writes both markdown files, with skip-if-exists protection.

## Outcome

- ✅ Impact: Obsidian vault fully structured with content and automation script
- 🧪 Tests: none — content generation task
- 📁 Files: Company_Handbook.md, Dashboard.md, setup_vault.py
- 🔁 Next prompts: Add template notes per folder, set up Obsidian Dataview queries for Dashboard, extend script with date-stamped log entries
- 🧠 Reflection: All three deliverables created in one pass; handbook and dashboard are self-consistent (same folder names, same lifecycle flow).

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Add Dataview query blocks to Dashboard.md for live task counts
