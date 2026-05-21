---
id: 013
title: OdooAccountingSkill and AutonomousLoop — Gold Tier
stage: general
date: 2026-05-09
surface: agent
model: claude-sonnet-4-6
feature: none
branch: main
user: zainub-nazish
command: >
  Generate OdooAccountingSkill (xmlrpc.client, Odoo 19+) and AutonomousLoop
  (weekly sales → summary → social post), with audit logging, error recovery,
  and ARCHITECTURE.md snippet.
labels: ["odoo", "xmlrpc", "autonomous-loop", "gold-tier", "skill-008", "skill-010"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - skills/odoo_accounting_skill.py
  - skills/autonomous_loop.py
  - docs/ARCHITECTURE.md
tests:
  - none
---

## Prompt

System Role: You are an expert AI Engineer specializing in the Agentic Dev Stack, MCP (Model Context Protocol), and Odoo 19+ integrations.
Task: I am building a Gold Tier: Autonomous Employee (Digital FTE). I need you to generate the core logic for the Odoo Accounting Skill and the Ralph Wiggum Autonomous Loop.
Technical Requirements:
Odoo Integration: Write a Python class OdooAccountingSkill that uses xmlrpc.client for JSON-RPC communication. Implement methods: authenticate(), get_weekly_sales_audit(), and create_invoice(). Target Odoo 19+ architecture.
Ralph Wiggum Loop (Autonomous Logic): Create an orchestrator function that executes a multi-step task without human intervention. Scenario: The agent must check Odoo for the last 7 days of sales, generate a business summary, and prepare a post for Social Media (Twitter/Facebook).
Gold Tier Standards: Include Comprehensive Audit Logging for every step. Implement Error Recovery with try-except blocks (Graceful Degradation). The code should be modular, following the Agent Skills pattern.
Output: Provide the Python code for odoo_skill.py and autonomous_loop.py. Provide a sample ARCHITECTURE.md snippet explaining how these components interact.
Context: My current stack uses Python, FastAPI, and Docker. Ensure the code is production-ready for a 2026 AI Agent.

## Response snapshot

Created two production-ready Python files and updated ARCHITECTURE.md:

**skills/odoo_accounting_skill.py** (OdooAccountingSkill — SKILL-008):
- Direct xmlrpc.client connection to Odoo 19+ (/xmlrpc/2/common + /xmlrpc/2/object)
- authenticate(): 3× retry with exponential backoff, caches uid
- get_weekly_sales_audit(): account.move domain query (7 days, posted invoices), returns invoices + overdue breakdown
- create_invoice(): resolves/creates partner, builds invoice lines, posts invoice, returns id + name
- get_accounting_summary(): AR/AP/overdue snapshot
- OdooResult uniform return type (success, data, error) — callers never handle raw exceptions
- Full audit log to Logs/odoo_accounting_skill.log

**skills/autonomous_loop.py** (AutonomousLoop — SKILL-010 Extension):
- 7-step hard-coded scenario: Odoo auth → audit → Claude summary → Claude social post → Twitter MCP → Facebook MCP → Dashboard
- _execute_with_retry(): exponential backoff (2→4→8s), up to 3 attempts per step
- _escalate(): writes APPROVAL-*.md to Pending_Approval/ on exhausted retries
- Shared context dict passed between steps
- Template fallbacks for Claude unavailable
- Graceful degradation: MCP missing → logged + skipped, not crashed
- Run report written to Briefings/AUTONOMOUS_<run_id>.md

**docs/ARCHITECTURE.md**: Added sections 10 and 11 documenting XML-RPC design,
Odoo 19 auth flow, retry contract, step engine diagram, and degradation matrix.

## Outcome

- ✅ Impact: SKILL-008 and SKILL-010 now production-ready with full audit trail and graceful degradation
- 🧪 Tests: None run (credentials required for Odoo + social API keys)
- 📁 Files: 2 new files created, 1 existing file updated
- 🔁 Next prompts: Wire AutonomousLoop into orchestrator.py; fill .env credentials; test against live Odoo Docker instance
- 🧠 Reflection: xmlrpc.client approach eliminates Node.js subprocess overhead for Odoo calls; OdooResult wrapper makes callers clean; non-blocking escalation allows remaining steps to proceed after partial failures

## Evaluation notes (flywheel)

- Failure modes observed: None during generation
- Graders run and results (PASS/FAIL): N/A
- Prompt variant (if applicable): N/A
- Next experiment (smallest change to try): Add integration test with Odoo Docker using test DB
