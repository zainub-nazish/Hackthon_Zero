---
id: 011
title: LinkedIn Auto-Poster Business Goals Skill
stage: general
date: 2026-03-29
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: danish
command: create linkedin_poster.py and Claude skill for 24h LinkedIn posting
labels: ["silver-tier", "linkedin", "playwright", "claude-api", "content-generation", "scheduler"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - Business_Goals.md
  - linkedin_poster.py
  - skills/linkedin_post_skill.py
  - skills/__init__.py
tests:
  - python linkedin_poster.py --preview → PASS (insight post generated, 609 chars)
---

## Prompt

Business_Goals.md aur Dashboard.md se content leke:
- Har 24 hours mein ek helpful business post generate karo (sales lead generate karne wala)
- Browser MCP use karke LinkedIn pe post kar do (draft nahi, direct post with approval if needed)
- Log karo /Logs/ mein
File: linkedin_poster.py aur Claude skill banao.

## Response snapshot

Created Business_Goals.md template (vault-root) with sections: company overview, target audience, services, UVP, quarterly goals, content themes, brand voice, CTA options, social proof.

Created skills/linkedin_post_skill.py (SKILL-005): 6 rotating post formats (value_tip, insight, case_study, question, behind_scenes, myth_bust). Reads Business_Goals.md + Dashboard.md + Company_Handbook.md as Claude context. Returns structured JSON with content/hashtags/hook/cta/approval_needed. Auto-detects pricing/guarantees and flags for approval. Template fallback when no API key. Logs format rotation to Logs/linkedin_posts.log.

Created linkedin_poster.py: full pipeline — generate → approval_check → post or save to Pending_Approval/. Playwright browser poster reusing Logs/linkedin_profile/ (shared with linkedin_watcher.py). Multiple selector fallbacks for LinkedIn DOM. Types post line by line (respects LinkedIn rich editor). Logs to Logs/linkedin_poster.log + Logs/linkedin_post_history.jsonl. --schedule runs 24h loop. --approve posts a saved approval file. Dashboard updated after each action.

Smoke test: --preview → insight format template post generated (609 chars), approval_needed=False. PASSED.

## Outcome

- Impact: AI Employee can now auto-generate and post business content to LinkedIn every 24h
- Tests: --preview smoke test PASSED
- Files: 3 created, 1 updated
- Next: Fill Business_Goals.md with real company data; set ANTHROPIC_API_KEY; run --now for first real post
- Reflection: Shared Playwright profile with linkedin_watcher avoids double login setup

## Evaluation notes (flywheel)

- Failure modes observed: Business_Goals.md placeholder text bleeds into posts — user must fill it in
- Graders run and results (PASS/FAIL): preview PASS
- Prompt variant (if applicable): none
- Next experiment: Add image generation (DALL-E/Stability) for post thumbnails
