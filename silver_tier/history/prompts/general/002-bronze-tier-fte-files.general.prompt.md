---
id: 002
title: Bronze Tier FTE Handbook and Dashboard
stage: general
date: 2026-03-09
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: user
command: natural language request
labels: ["bronze-tier","handbook","dashboard","ai-employee","rules-of-engagement"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - Company_Handbook.md
 - Dashboard.md
 - history/prompts/general/002-bronze-tier-fte-files.general.prompt.md
tests:
 - none
---

## Prompt

You are now my Personal AI Employee (Digital FTE).
We are building the Bronze tier.

First, create two files in the root of the vault:

1. Company_Handbook.md
   - Must have clear "Rules of Engagement"
   - Always be polite
   - Flag any payment over $100 for human approval
   - Use simple language
   - Add sections: Communication Rules, Approval Rules, Security Rules

2. Dashboard.md
   - Clean dashboard layout
   - Sections: Bank Balance (placeholder), Pending Tasks, Recent Activity, Next Actions
   - Use markdown tables and checkboxes

Use frontmatter (---) at the top of both files.
After creating both files, tell me "Files created successfully" and show me the first 15 lines of each file.

## Response snapshot

Rewrote Company_Handbook.md (v2.0) with YAML frontmatter, Rules of Engagement summary table, Communication Rules, Approval Rules (payments >$100 flagged for human approval), and Security Rules. Rewrote Dashboard.md with YAML frontmatter, Bank Balance section with placeholders, Pending Tasks checklist, Recent Activity table, and Next Actions list. Reported "Files created successfully" and displayed first 15 lines of each file.

## Outcome

- ✅ Impact: Bronze Tier AI Employee operational baseline established with handbook and command center
- 🧪 Tests: none — content generation task
- 📁 Files: Company_Handbook.md (rewritten v2.0), Dashboard.md (rewritten v2.0)
- 🔁 Next prompts: Connect live data to bank balance placeholders; define task intake workflow; set up Logs folder template
- 🧠 Reflection: Both files now have YAML frontmatter as required; approval rule (>$100 = human approval) is explicit and formatted for easy reference.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Add Dataview queries to Dashboard for live task counts from Inbox/Needs_Action folders
