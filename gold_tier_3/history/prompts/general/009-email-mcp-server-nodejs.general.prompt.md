---
id: 009
title: Email MCP Server Node.js Silver Tier
stage: general
date: 2026-03-29
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: danish
command: create email-mcp server with send_email and draft_email tools
labels: ["silver-tier", "mcp", "gmail", "nodejs", "email", "attachment"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - email-mcp/index.js
  - email-mcp/package.json
  - email-mcp/auth.js
  - C:/Users/DANISH LAPTOP/.claude/settings.json
tests:
  - echo tools/list | node email-mcp/index.js → PASS (both tools returned)
---

## Prompt

Create a working Email MCP server (Node.js) jo Claude Code call kar sake.
File: email-mcp/index.js
Capabilities:
- send_email(to, subject, body, attachment_path)
- draft_email (for approval)
Use Gmail API (same credentials).
MCP protocol follow karo (modelcontextprotocol.io standard).
Phir ~/.config/claude-code/mcp.json mein add kar do example ke mutabiq.

## Response snapshot

Created `email-mcp/` with 3 files:

1. `index.js` — MCP server v2 with `send_email` + `draft_email` tools. Reads credentials.json + token.json from project root (no manual env var setup). Auto-refreshes token. Multipart MIME builder for attachments (PDF/DOCX/XLSX/PNG/etc.). `draft_email` saves to Gmail Drafts folder for human approval.

2. `auth.js` — One-time OAuth2 consent helper. Opens browser, captures callback on localhost:8765, saves token.json. Run `node auth.js` once.

3. `package.json` — `@modelcontextprotocol/sdk ^1.12`, `googleapis ^144`. npm install completed (116 packages, 0 vulnerabilities).

Updated `~/.claude/settings.json` to point to `D:/Hackthon_0/silver_tier_3/email-mcp/index.js` (removed old env var block — credentials loaded from project files).

Server verified: `tools/list` returns both tools correctly.

## Outcome

- Impact: Claude Code can now call send_email and draft_email as MCP tools in any conversation
- Tests: tools/list smoke test PASSED
- Files: 3 created, 1 updated (settings.json)
- Next prompts: Run `node email-mcp/auth.js` to generate token.json; then restart Claude Code to load MCP server
- Reflection: Used credentials.json + token.json pattern (same as Python watchers) so no duplicate OAuth setup needed

## Evaluation notes (flywheel)

- Failure modes observed: token.json not yet generated — auth.js must be run first
- Graders run and results (PASS/FAIL): tools/list smoke test PASS
- Prompt variant (if applicable): none
- Next experiment: Add read_drafts tool to list pending drafts for approval workflow
