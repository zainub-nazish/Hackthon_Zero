---
id: 010
title: Orchestrator Approval Plan Skills System
stage: general
date: 2026-03-29
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: danish
command: create orchestrator with approval, plan, dashboard, mcp_client skills
labels: ["silver-tier", "orchestrator", "approval", "plan", "skills", "mcp", "claude-api"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - orchestrator.py
  - skills/__init__.py
  - skills/approval_skill.py
  - skills/plan_skill.py
  - skills/dashboard_skill.py
  - skills/mcp_client.py
  - pyproject.toml
tests:
  - python orchestrator.py --dry-run --once → PASS (1 item scanned, 1 plan detected)
---

## Prompt

Ab yeh features add karo:
1. Jab sensitive action ho (email send, LinkedIn post >$50 value, etc.) toh /Pending_Approval/ folder mein approval file banao (.md)
2. Claude har Needs_Action file ko process kare aur /Plans/ mein Plan_*.md file banaye with checkboxes.
3. Company_Handbook.md ke rules follow karo (polite replies, approval thresholds).
4. Orchestrator script banao (orchestrator.py) jo:
   - Needs_Action check kare
   - Claude ko prompt kare
   - Plan banaye
   - Agar approved ho toh MCP call kare
Sab kuch Agent Skills ke through ho.

## Response snapshot

Created full orchestration system:

`skills/approval_skill.py` (SKILL-004): Detects sensitive actions via rules from Company_Handbook — email sends always flagged, LinkedIn with business keywords flagged, payments >$100 flagged, suspicious/security keywords flagged. Creates APPROVAL-<date>-<name>.md in Pending_Approval/ with risk level (High/Medium/Low), expiry 48h, approve/reject instructions.

`skills/plan_skill.py` (SKILL-001): Calls Claude Haiku API with Company_Handbook as system context. Returns JSON plan → renders Plan_<slug>_<ts>.md with checkboxes. Graceful fallback to template-based plans when ANTHROPIC_API_KEY not set.

`skills/dashboard_skill.py` (SKILL-003): Updates Dashboard.md Recent Activity table, refreshes last_updated frontmatter.

`skills/mcp_client.py`: Minimal JSON-RPC 2.0 MCP client — spawns node email-mcp/index.js, performs MCP initialize handshake, calls send_email or draft_email, returns result.

`orchestrator.py`: Main loop (30s interval). Cycle: (1) scan Needs_Action → route to approval or plan; (2) scan Approved → parse action → MCP call → move to Done; (3) dashboard update. Supports --once, --dry-run, --skill 001/004, --interval flags. State persisted in Logs/orchestrator_state.json to avoid reprocessing.

Added anthropic>=0.40.0 to pyproject.toml. Smoke test: --dry-run --once PASSED.

## Outcome

- Impact: Full autonomous Silver-tier loop — items flow from Needs_Action through approval/planning to execution
- Tests: dry-run smoke test PASSED (1 item detected, routed correctly)
- Files: 6 created, 1 updated (pyproject.toml)
- Next prompts: Set ANTHROPIC_API_KEY env var for Claude-powered plans; move an EMAIL_* file to Needs_Action to test approval flow; move APPROVAL file to Approved/ to test MCP execution
- Reflection: Kept approval detection rule-based (no AI needed for security-critical decisions); Claude only used for plan generation where fallback is safe

## Evaluation notes (flywheel)

- Failure modes observed: Windows cp1252 console encoding issue with Unicode chars — fixed to ASCII
- Graders run and results (PASS/FAIL): dry-run PASS
- Prompt variant (if applicable): none
- Next experiment: Add SKILL-002 (move completed to Done) as standalone skill
