"""
PlanSkill — SKILL-001
Reads a Needs_Action file, calls Claude API to analyze it,
and writes a structured Plan_*.md with checkboxes to Plans/.

Claude system context includes Company_Handbook.md rules so plans
are always policy-compliant.

Fallback: if ANTHROPIC_API_KEY is not set, generates a template-based
plan so the orchestrator always produces output.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("PlanSkill")

# ---------------------------------------------------------------------------
# Anthropic SDK (optional — graceful fallback if missing or no key)
# ---------------------------------------------------------------------------
try:
    import anthropic as _anthropic_module
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic SDK not installed. Using template fallback.")


# ---------------------------------------------------------------------------
# Action type → plan template hints
# ---------------------------------------------------------------------------
_ACTION_HINTS = {
    "EMAIL_":      ("email_response",    "Draft and send a polite, professional email reply."),
    "WHATSAPP_":   ("whatsapp_followup", "Review WhatsApp message and decide on response."),
    "LINKEDIN_":   ("linkedin_action",   "Review LinkedIn message/notification and respond."),
    "FILE_":       ("file_review",       "Review the file and decide next action."),
}


def _action_hint(filename: str) -> tuple[str, str]:
    for prefix, hint in _ACTION_HINTS.items():
        if filename.startswith(prefix):
            return hint
    return ("general", "Review this item and plan next steps.")


# ---------------------------------------------------------------------------
# PlanSkill
# ---------------------------------------------------------------------------

class PlanSkill:
    """
    SKILL-001 — Needs_Action analyzer and Plan_*.md generator.

    Usage:
        skill = PlanSkill(vault_root)
        plan_path = skill.create_plan(needs_action_file_path)
    """

    MODEL = "claude-haiku-4-5-20251001"   # fast + cheap for planning

    def __init__(self, vault_root: Path) -> None:
        self.vault_root   = Path(vault_root)
        self.plans_dir    = self.vault_root / "Plans"
        self.logs_dir     = self.vault_root / "Logs"
        self.handbook     = self._load_handbook()
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None
        if _ANTHROPIC_AVAILABLE and api_key:
            self._client = _anthropic_module.Anthropic(api_key=api_key)
            logger.info("Claude API ready (model: %s).", self.MODEL)
        else:
            logger.warning(
                "ANTHROPIC_API_KEY not set or SDK missing — using template fallback."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_plan(self, source_file: Path) -> Path:
        """
        Analyze source_file and produce Plans/Plan_<slug>_<ts>.md.
        Returns the path to the created plan file.
        """
        now      = datetime.now(timezone.utc)
        ts       = now.strftime("%Y%m%d_%H%M%S")
        slug     = re.sub(r'\W+', '_', source_file.stem)[:35]
        plan_name = f"Plan_{slug}_{ts}.md"
        plan_path = self.plans_dir / plan_name

        content  = self._read(source_file)
        atype, hint = _action_hint(source_file.name)

        if self._client:
            plan_body = self._claude_plan(source_file.name, content, atype, hint, now)
        else:
            plan_body = self._template_plan(source_file.name, content, atype, hint, now)

        plan_path.write_text(plan_body, encoding="utf-8")
        self._log(f"SKILL-001 — Plan created: {plan_name} (source: {source_file.name})")
        logger.info("Plan created: %s", plan_name)
        return plan_path

    # ------------------------------------------------------------------
    # Claude-powered plan generation
    # ------------------------------------------------------------------

    def _claude_plan(
        self,
        filename: str,
        content: str,
        atype: str,
        hint: str,
        now: datetime,
    ) -> str:
        """Call Claude API to generate a smart, context-aware plan."""

        system_prompt = f"""You are a Silver-tier AI Employee assistant.
Your job is to analyze incoming work items and produce clear, actionable plans.

COMPANY HANDBOOK RULES (must be followed in every plan):
{self.handbook}

OUTPUT FORMAT:
Return a JSON object with these exact keys:
{{
  "title": "short plan title (max 60 chars)",
  "priority": "High | Medium | Low",
  "owner": "AI Employee",
  "due_note": "e.g. Respond within 24 hours",
  "summary": "1-2 sentence summary of what needs to be done",
  "steps": ["step 1", "step 2", "step 3", ...],
  "acceptance_criteria": ["criterion 1", "criterion 2", ...],
  "risks": ["risk 1 if any"],
  "handbook_notes": "relevant handbook rule that applies"
}}

Rules:
- Steps must be specific and actionable (max 7 steps).
- Acceptance criteria must be testable checkboxes.
- Tone in steps must always be polite and professional.
- If action involves payment > $100, add a step: "Obtain human approval before proceeding."
- Keep everything concise.
"""

        user_prompt = f"""Analyze this work item and produce a plan.

File: {filename}
Action type: {atype}
Hint: {hint}

Content:
---
{content[:3000]}
---

Return only the JSON object, no extra text."""

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text.strip()

            # Strip markdown code fences if present
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)

            plan_data = json.loads(raw)
            return self._render_plan(filename, plan_data, now)

        except json.JSONDecodeError as e:
            logger.warning("Claude returned invalid JSON, using fallback: %s", e)
            return self._template_plan(filename, content, atype, hint, now)
        except Exception as e:
            logger.error("Claude API error: %s — using fallback.", e)
            return self._template_plan(filename, content, atype, hint, now)

    def _render_plan(self, filename: str, data: dict, now: datetime) -> str:
        """Render a plan dict into markdown with checkboxes."""
        steps_md = "\n".join(f"{i+1}. {s}" for i, s in enumerate(data.get("steps", [])))
        criteria_md = "\n".join(f"- [ ] {c}" for c in data.get("acceptance_criteria", []))
        risks_md = "\n".join(f"- {r}" for r in data.get("risks", [])) or "- None identified."

        return f"""\
---
title: {data.get('title', 'Untitled Plan')}
task_id: PLAN-{now.strftime('%Y%m%d%H%M%S')}
source_file: {filename}
owner: {data.get('owner', 'AI Employee')}
priority: {data.get('priority', 'Medium')}
status: pending
created: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
due_note: {data.get('due_note', 'Review within 24 hours')}
approved_by:
---

# Plan: {data.get('title', 'Untitled')}

## Summary

{data.get('summary', 'Review this item and take appropriate action.')}

## Steps

{steps_md}

## Acceptance Criteria

{criteria_md}

## Risks & Notes

{risks_md}

## Handbook Reference

> {data.get('handbook_notes', 'Follow Company_Handbook.md rules at all times.')}

---
*Generated by PlanSkill (SKILL-001) via Claude on {now.strftime('%Y-%m-%d %H:%M:%S UTC')}.*
*Source: `{filename}` | Reference: [[Company_Handbook]]*
"""

    # ------------------------------------------------------------------
    # Template-based fallback (no API key needed)
    # ------------------------------------------------------------------

    def _template_plan(
        self,
        filename: str,
        content: str,
        atype: str,
        hint: str,
        now: datetime,
    ) -> str:
        """Generate a best-effort plan from templates when Claude is unavailable."""

        atype_steps = {
            "email_response": [
                "Read the full email carefully.",
                "Identify the key request or question.",
                "Draft a polite, professional reply following Company Handbook tone guidelines.",
                "Review draft — ensure no sensitive data is exposed.",
                "Obtain approval if content involves commitments > $100.",
                "Send via email-mcp tool or save as draft for review.",
            ],
            "whatsapp_followup": [
                "Review the WhatsApp message and identify the keyword trigger.",
                "Determine if this is a sales inquiry, payment request, or general query.",
                "If payment > $100: create approval request before responding.",
                "Draft a brief, professional response.",
                "Log the interaction in Logs/.",
            ],
            "linkedin_action": [
                "Review the LinkedIn message or notification.",
                "Identify if this is a sales inquiry, proposal, or general connection.",
                "If business value > $50: route to Pending_Approval/.",
                "Otherwise: draft a polite response.",
                "Log the interaction in Logs/.",
            ],
            "file_review": [
                "Open and review the file.",
                "Identify the file type and purpose.",
                "Route to appropriate folder: Approved, Rejected, or Needs_Action.",
                "Update Dashboard.md with status.",
            ],
            "general": [
                "Review the item thoroughly.",
                "Identify required action.",
                "Check Company_Handbook.md for applicable rules.",
                "Execute action or escalate as needed.",
                "Log outcome in Logs/.",
            ],
        }

        steps = atype_steps.get(atype, atype_steps["general"])
        steps_md   = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        snippet    = content[:300].replace('\n', ' ').strip()

        return f"""\
---
title: Review {filename[:50]}
task_id: PLAN-{now.strftime('%Y%m%d%H%M%S')}
source_file: {filename}
owner: AI Employee
priority: Medium
status: pending
created: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
due_note: Review within 24 hours
approved_by:
---

# Plan: Review {filename[:50]}

## Summary

{hint} Triggered by `{filename}`.

> Preview: {snippet}...

## Steps

{steps_md}

## Acceptance Criteria

- [ ] Item has been reviewed and understood.
- [ ] Appropriate action taken (reply / approve / reject / escalate).
- [ ] If payment involved, approval obtained before proceeding.
- [ ] Outcome logged in Logs/.
- [ ] Dashboard.md updated.

## Risks & Notes

- If this involves a payment > $100, stop and create an approval request (SKILL-004).
- Always be polite and professional in all replies (Company Handbook Rule 1).

## Handbook Reference

> *Any payment or expense over $100 must be flagged for human approval before proceeding.*
> *Always be polite and professional. No exceptions.*

---
*Generated by PlanSkill (SKILL-001) — template fallback on {now.strftime('%Y-%m-%d %H:%M:%S UTC')}.*
*Source: `{filename}` | Reference: [[Company_Handbook]]*
"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_handbook(self) -> str:
        handbook_path = self.vault_root / "Company_Handbook.md"
        try:
            # Extract just the rules sections (skip YAML frontmatter)
            text = handbook_path.read_text(encoding="utf-8")
            # Strip YAML frontmatter
            text = re.sub(r'^---.*?---\s*', '', text, flags=re.DOTALL)
            return text[:3000]
        except OSError:
            return "Follow all professional communication and approval rules."

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _log(self, message: str) -> None:
        now      = datetime.now(timezone.utc)
        log_file = self.logs_dir / "plan_skill.log"
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] {message}\n")
        except OSError:
            pass
