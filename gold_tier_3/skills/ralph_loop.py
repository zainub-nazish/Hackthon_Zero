"""
RalphLoop — SKILL-010: Autonomous Multi-Step Task Executor

Named after Ralph Wiggum (The Simpsons) — runs in circles until it gets it right.

The Ralph Loop is the Gold Tier's autonomous execution engine:
  1. Takes a high-level goal
  2. Uses Claude to decompose it into ordered steps
  3. Executes each step (with access to all skills + MCP tools)
  4. Evaluates success/failure after each step
  5. On failure: asks Claude to suggest a corrected approach and retries
  6. Continues until all steps succeed OR max_retries exhausted
  7. Writes a full execution log to Logs/ralph_loop.log

Design principle: Human-in-the-loop escalation
  - If a step fails 3× in a row, escalate to Pending_Approval/
  - Never silently fail — always leave a trace
  - Always update Dashboard after completion

Usage:
    from skills.ralph_loop import RalphLoop

    loop = RalphLoop(vault_root)
    result = loop.execute(
        goal="Process the new invoice in Needs_Action and create Odoo customer + invoice",
        context={"file": "Needs_Action/EMAIL_abc123.md"},
        max_retries=3,
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("RalphLoop")

try:
    import anthropic as _anthropic
    _CLAUDE_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))
except ImportError:
    _CLAUDE_AVAILABLE = False


class StepResult:
    def __init__(self, step: str, success: bool, output: str, attempt: int) -> None:
        self.step    = step
        self.success = success
        self.output  = output
        self.attempt = attempt
        self.ts      = datetime.now(timezone.utc).isoformat()


class RalphLoop:
    """
    Autonomous multi-step task executor with retry, self-correction, and escalation.
    """

    MODEL      = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 2048

    def __init__(self, vault_root: Path) -> None:
        self.vault_root    = Path(vault_root)
        self.logs_dir      = self.vault_root / "Logs"
        self.pending_dir   = self.vault_root / "Pending_Approval"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.pending_dir.mkdir(parents=True, exist_ok=True)

        self._log_file = self.logs_dir / "ralph_loop.log"
        self._client   = None

        if _CLAUDE_AVAILABLE:
            self._client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            logger.info("RalphLoop initialized with Claude (%s).", self.MODEL)
        else:
            logger.warning("ANTHROPIC_API_KEY not set — RalphLoop will use rule-based fallback.")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def execute(
        self,
        goal: str,
        context: dict | None = None,
        max_retries: int = 3,
        executor=None,
    ) -> dict:
        """
        Execute a goal autonomously.

        Args:
            goal:        Natural language description of what to accomplish
            context:     Dict with supporting data (file paths, IDs, etc.)
            max_retries: Max retry attempts per step before escalating
            executor:    Optional callable(step_description, context) → (success, output)
                         If not provided, uses _simulate_executor (dry run)

        Returns:
            {
                "success":      bool,
                "goal":         str,
                "steps_total":  int,
                "steps_done":   int,
                "results":      list[StepResult],
                "escalated":    bool,
                "summary":      str,
            }
        """
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._log(f"\n{'='*60}\nRalph Loop START | run_id={run_id}\nGoal: {goal}\nContext: {context}\n{'='*60}")

        steps = self._decompose(goal, context)
        self._log(f"Decomposed into {len(steps)} step(s): {steps}")

        results: list[StepResult] = []
        escalated = False

        for i, step in enumerate(steps, 1):
            self._log(f"\n--- Step {i}/{len(steps)}: {step} ---")
            step_result = self._execute_step(
                step, context or {}, max_retries, executor, run_id, i
            )
            results.append(step_result)

            if not step_result.success:
                self._log(f"Step {i} FAILED after {step_result.attempt} attempt(s). Escalating.")
                self._escalate(goal, step, step_result, run_id)
                escalated = True
                break

        steps_done = sum(1 for r in results if r.success)
        overall_ok = steps_done == len(steps)

        summary = self._build_summary(goal, steps, results, overall_ok, escalated, run_id)
        self._log(f"\n{summary}\n{'='*60}\nRalph Loop END | run_id={run_id}\n{'='*60}")

        return {
            "success":     overall_ok,
            "goal":        goal,
            "steps_total": len(steps),
            "steps_done":  steps_done,
            "results":     results,
            "escalated":   escalated,
            "summary":     summary,
            "run_id":      run_id,
        }

    # ------------------------------------------------------------------
    # Goal decomposition
    # ------------------------------------------------------------------

    def _decompose(self, goal: str, context: dict | None) -> list[str]:
        """Use Claude to decompose the goal into ordered steps."""
        if not self._client:
            return self._rule_based_decompose(goal)

        prompt = f"""You are a task decomposition engine for an autonomous AI employee.

Goal: {goal}
Context: {json.dumps(context or {}, indent=2)}

Break this goal into 3-7 concrete, executable steps.
Each step must be a single, specific action (not vague).
Return ONLY a JSON array of step strings, no other text.

Example output:
["Read the file Needs_Action/EMAIL_abc.md", "Extract customer name and email", "Call create_customer MCP tool", "Confirm creation in Odoo"]"""

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw   = response.content[0].text.strip()
            raw   = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw   = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
            steps = json.loads(raw)
            if isinstance(steps, list) and all(isinstance(s, str) for s in steps):
                return steps
        except Exception as e:
            logger.warning("Claude decomposition failed: %s — using fallback.", e)

        return self._rule_based_decompose(goal)

    def _rule_based_decompose(self, goal: str) -> list[str]:
        """Fallback decomposition when Claude is unavailable."""
        goal_lower = goal.lower()
        if "invoice" in goal_lower:
            return [
                "Read the invoice file from Needs_Action/",
                "Extract customer name, amount, and due date",
                "Create Odoo customer if not exists",
                "Create Odoo invoice with extracted data",
                "Update Dashboard with invoice status",
            ]
        if "email" in goal_lower or "reply" in goal_lower:
            return [
                "Read the email note from Needs_Action/",
                "Analyze email content and determine required action",
                "Draft reply using available context",
                "Send reply via email-mcp",
                "Move email note to Done/",
            ]
        if "post" in goal_lower or "linkedin" in goal_lower or "twitter" in goal_lower:
            return [
                "Read Business_Goals.md for context",
                "Generate post content appropriate for the platform",
                "Check if approval is required",
                "Post via social media MCP tool",
                "Log post in Logs/",
            ]
        return [
            "Analyze the task requirements",
            "Gather necessary context from vault",
            "Execute the primary action",
            "Verify the result",
            "Update Dashboard with outcome",
        ]

    # ------------------------------------------------------------------
    # Step execution with retry + self-correction
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        step: str,
        context: dict,
        max_retries: int,
        executor,
        run_id: str,
        step_num: int,
    ) -> StepResult:
        last_output = ""
        correction  = ""

        for attempt in range(1, max_retries + 1):
            self._log(f"  Attempt {attempt}/{max_retries}: {step}")
            if correction:
                self._log(f"  Correction hint: {correction}")

            if executor:
                effective_step = f"{step}. {correction}" if correction else step
                try:
                    success, output = executor(effective_step, context)
                except Exception as e:
                    success, output = False, str(e)
            else:
                success, output = self._simulate_executor(step, context)

            last_output = output
            self._log(f"  → {'OK' if success else 'FAIL'}: {output[:120]}")

            if success:
                return StepResult(step, True, output, attempt)

            # Generate correction for next attempt
            if attempt < max_retries:
                correction = self._get_correction(step, output, attempt)
                time.sleep(2 ** attempt)  # exponential backoff: 2, 4, 8 seconds

        return StepResult(step, False, last_output, max_retries)

    def _get_correction(self, step: str, error_output: str, attempt: int) -> str:
        """Ask Claude for a corrected approach after a failed step."""
        if not self._client:
            return f"Retry attempt {attempt + 1} — previous error: {error_output[:100]}"

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": (
                        f"A step in an autonomous task failed.\n"
                        f"Step: {step}\n"
                        f"Error: {error_output[:300]}\n"
                        f"Attempt: {attempt}\n\n"
                        "In one sentence, what adjustment should be made for the next attempt?"
                    )
                }],
            )
            return response.content[0].text.strip()[:200]
        except Exception:
            return f"Check dependencies and retry — error was: {error_output[:100]}"

    def _simulate_executor(self, step: str, context: dict) -> tuple[bool, str]:
        """
        Dry-run executor used when no real executor is provided.
        In production, replace this with actual skill/MCP dispatch.
        """
        logger.info("[DRY RUN] Would execute: %s | Context keys: %s", step[:60], list(context.keys()))
        return True, f"[DRY RUN] Step simulated: {step[:80]}"

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(self, goal: str, failed_step: str, result: StepResult, run_id: str) -> None:
        """Write an escalation request to Pending_Approval/ when all retries exhausted."""
        now       = datetime.now(timezone.utc)
        file_name = f"APPROVAL-{now.strftime('%Y%m%d_%H%M%S')}-ralph-escalation.md"
        file_path = self.pending_dir / file_name

        content = f"""\
---
type: ralph_loop_escalation
run_id: {run_id}
created_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
risk_level: Medium
status: pending_approval
---

# Ralph Loop Escalation — Human Review Required

| Field         | Value |
|---------------|-------|
| Run ID        | `{run_id}` |
| Goal          | {goal} |
| Failed Step   | {failed_step} |
| Attempts Made | {result.attempt} |
| Last Error    | {result.output[:200]} |
| Created At    | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |

## What Happened

The autonomous Ralph Loop attempted to complete the goal above but failed on the step
"{failed_step}" after {result.attempt} attempt(s).

## Last Error Output

```
{result.output[:500]}
```

## Action Required

1. Review the error above.
2. Fix the underlying issue (credentials, data, connectivity).
3. Either: manually complete the step, or mark this file as `status: resolved` to retry.
4. Move this file to Done/ once resolved.

---
*Auto-generated by RalphLoop (SKILL-010) on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            file_path.write_text(content, encoding="utf-8")
            logger.info("Escalation created: %s", file_name)
        except OSError as e:
            logger.error("Could not write escalation: %s", e)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(self, goal: str, steps: list[str], results: list[StepResult],
                        success: bool, escalated: bool, run_id: str) -> str:
        lines = [
            f"Ralph Loop Summary — run_id={run_id}",
            f"Goal: {goal}",
            f"Status: {'SUCCESS' if success else 'ESCALATED' if escalated else 'PARTIAL'}",
            f"Steps: {sum(1 for r in results if r.success)}/{len(steps)} completed",
            "",
        ]
        for i, result in enumerate(results, 1):
            icon = "✓" if result.success else "✗"
            lines.append(f"  {icon} Step {i}: {result.step[:60]} (attempt {result.attempt})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        logger.info(message.replace("\n", " ").strip()[:200])
        try:
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(message + "\n")
        except OSError:
            pass
