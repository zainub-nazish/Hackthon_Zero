---
id: 003
title: Agent Skills and Plan Template
stage: general
date: 2026-03-09
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: user
command: natural language request
labels: ["bronze-tier","agent-skills","skills","plan-template","automation"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - AGENT_SKILLS.md
 - Plans/TEMPLATE_TASK.md
 - history/prompts/general/003-agent-skills-and-plan-template.general.prompt.md
tests:
 - none
---

## Prompt

Now create a file called AGENT_SKILLS.md in the root.

This file will contain all my Agent Skills as markdown.

Add these skills (as separate sections):

- Skill 001: Read Needs_Action folder and create Plan.md
- Skill 002: Move completed tasks to Done folder
- Skill 003: Update Dashboard.md after every action
- Skill 004: Create approval request for sensitive actions

For each skill, write:
- Skill ID
- Description
- When to use
- Step-by-step process

Also create one empty Plan template: Plans/TEMPLATE_TASK.md

After finishing, say "Agent Skills ready".

## Response snapshot

Created AGENT_SKILLS.md with 4 fully documented skills (SKILL-001 through SKILL-004), each with Skill ID, Description, When to Use, and a numbered Step-by-Step Process. Created Plans/TEMPLATE_TASK.md as a blank task template with YAML frontmatter, Description, Steps, Acceptance Criteria, and Notes sections.

## Outcome

- ✅ Impact: Bronze Tier AI Employee now has a defined, executable skill library and a reusable task template
- 🧪 Tests: none — content generation task
- 📁 Files: AGENT_SKILLS.md, Plans/TEMPLATE_TASK.md
- 🔁 Next prompts: Implement skills as actual automation; wire Skill 003 to trigger after every skill execution; add more skills
- 🧠 Reflection: All 4 skills are self-consistent — each ends with a Skill 003 call and a Logs entry, creating a coherent operational loop.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Add SKILL-005 for daily briefing generation from Logs
