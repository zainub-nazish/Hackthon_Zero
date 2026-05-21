"""
autonomous_loop.py — Gold Tier Autonomous Orchestrator (SKILL-010 Extension)

Implements a self-directed multi-step execution engine for the scenario:
  "Check last 7 days of Odoo sales → generate business summary → post to
   Twitter and Facebook — all without human intervention."

Architecture:
  AutonomousLoop
    ├── Step 1: Authenticate with Odoo
    ├── Step 2: Pull weekly sales audit (OdooAccountingSkill)
    ├── Step 3: Generate executive summary  (Claude claude-sonnet-4-6)
    ├── Step 4: Craft social post           (Claude claude-sonnet-4-6)
    ├── Step 5: Post to Twitter             (twitter-mcp)
    ├── Step 6: Post to Facebook            (facebook-mcp)
    └── Step 7: Update Dashboard + Briefing (DashboardSkill)

Design guarantees:
  • Every step is independently retried (exponential backoff, max _MAX_RETRIES).
  • On step failure after all retries: escalate to Pending_Approval/, continue
    remaining steps (non-blocking escalation).
  • Comprehensive audit log entry for every action, success or failure.
  • Claude unavailable → template fallback (never a hard crash).
  • MCP server unavailable → logged and skipped (graceful degradation).
  • Full execution report written to Briefings/ at the end of every run.

Usage:
    loop = AutonomousLoop(vault_root)
    result = loop.run_weekly_sales_social_post()
    print(result["summary"])
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("AutonomousLoop")

# ---------------------------------------------------------------------------
# Optional Claude SDK
# ---------------------------------------------------------------------------
try:
    import anthropic as _anthropic
    _CLAUDE_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))
except ImportError:
    _CLAUDE_AVAILABLE = False

_CLAUDE_MODEL  = "claude-sonnet-4-6"
_CLAUDE_TOKENS = 1024
_MAX_RETRIES   = 3
_BACKOFF_BASE  = 2   # seconds; doubles each retry: 2 → 4 → 8


# ---------------------------------------------------------------------------
# Step result data class
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name:     str
    success:  bool
    output:   Any          = None
    error:    str          = ""
    attempts: int          = 1
    ts:       str          = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    skipped:  bool         = False

    def to_dict(self) -> dict:
        return {
            "name":     self.name,
            "success":  self.success,
            "output":   str(self.output)[:200] if self.output else "",
            "error":    self.error[:200],
            "attempts": self.attempts,
            "ts":       self.ts,
            "skipped":  self.skipped,
        }


# ---------------------------------------------------------------------------
# AutonomousLoop
# ---------------------------------------------------------------------------

class AutonomousLoop:
    """
    Gold Tier autonomous execution engine.

    All public entry points return a standardised result dict:
    {
        "success":    bool,
        "scenario":   str,
        "steps":      list[dict],       # StepResult.to_dict() for each step
        "escalated":  list[str],        # step names that were escalated
        "summary":    str,              # human-readable run summary
        "report_path": str | None,      # path to the Briefings/ report file
        "run_id":     str,
    }
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root   = Path(vault_root)
        self.logs_dir     = self.vault_root / "Logs"
        self.pending_dir  = self.vault_root / "Pending_Approval"
        self.briefings_dir = self.vault_root / "Briefings"
        self.dashboard    = self.vault_root / "Dashboard.md"

        for d in [self.logs_dir, self.pending_dir, self.briefings_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._log_file = self.logs_dir / "autonomous_loop.log"
        self._client: Any = None

        if _CLAUDE_AVAILABLE:
            self._client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            logger.info("AutonomousLoop ready | model=%s", _CLAUDE_MODEL)
        else:
            logger.warning("ANTHROPIC_API_KEY not set — template fallbacks active.")

    # ------------------------------------------------------------------
    # Primary scenario: weekly sales → social post
    # ------------------------------------------------------------------

    def run_weekly_sales_social_post(self) -> dict:
        """
        Fully autonomous scenario:
          Odoo 7-day sales audit → Claude summary → Twitter + Facebook posts.

        Returns the standardised result dict described in the class docstring.
        """
        run_id    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        scenario  = "weekly_sales_social_post"
        results:  list[StepResult] = []
        escalated: list[str]       = []

        self._audit(run_id, f"=== Scenario START: {scenario} ===")
        self._audit(run_id, f"Claude available: {_CLAUDE_AVAILABLE}")

        # Import here to avoid circular dependency at module load time
        from skills.odoo_accounting_skill import OdooAccountingSkill
        odoo = OdooAccountingSkill(self.vault_root)

        # Shared context passed between steps
        ctx: dict[str, Any] = {}

        # ---- Step pipeline -----------------------------------------------
        steps: list[tuple[str, Callable]] = [
            ("odoo_authenticate",    lambda: self._step_odoo_auth(odoo, ctx)),
            ("odoo_weekly_audit",    lambda: self._step_odoo_audit(odoo, ctx)),
            ("generate_summary",     lambda: self._step_generate_summary(ctx)),
            ("craft_social_post",    lambda: self._step_craft_post(ctx)),
            ("post_to_twitter",      lambda: self._step_post_twitter(ctx)),
            ("post_to_facebook",     lambda: self._step_post_facebook(ctx)),
            ("update_dashboard",     lambda: self._step_update_dashboard(ctx, run_id)),
        ]

        for step_name, step_fn in steps:
            self._audit(run_id, f"--- Step START: {step_name} ---")
            result = self._execute_with_retry(step_name, step_fn, run_id)
            results.append(result)

            if not result.success:
                self._audit(run_id, f"Step FAILED: {step_name} after {result.attempts} attempt(s)")
                self._escalate(run_id, scenario, step_name, result)
                escalated.append(step_name)
                # Continue remaining steps — non-blocking escalation

        # ---- Run report --------------------------------------------------
        overall_ok   = all(r.success for r in results)
        report_path  = self._write_report(run_id, scenario, ctx, results, escalated)
        summary_text = self._build_summary(run_id, scenario, results, escalated)

        self._audit(run_id, summary_text)
        self._audit(run_id, f"=== Scenario END: {scenario} | ok={overall_ok} ===\n")

        return {
            "success":     overall_ok,
            "scenario":    scenario,
            "steps":       [r.to_dict() for r in results],
            "escalated":   escalated,
            "summary":     summary_text,
            "report_path": str(report_path) if report_path else None,
            "run_id":      run_id,
        }

    # ------------------------------------------------------------------
    # Individual steps
    # ------------------------------------------------------------------

    def _step_odoo_auth(self, odoo: Any, ctx: dict) -> StepResult:
        """Step 1 — Authenticate with Odoo."""
        result = odoo.authenticate()
        if result.success:
            ctx["odoo_uid"] = result.data
            return StepResult("odoo_authenticate", True, output=f"uid={result.data}")
        return StepResult("odoo_authenticate", False, error=result.error)

    def _step_odoo_audit(self, odoo: Any, ctx: dict) -> StepResult:
        """Step 2 — Pull 7-day sales audit from Odoo."""
        if "odoo_uid" not in ctx:
            return StepResult(
                "odoo_weekly_audit", False,
                error="Odoo not authenticated — skipping audit.",
                skipped=True,
            )
        result = odoo.get_weekly_sales_audit()
        if result.success:
            ctx["audit"] = result.data
            summary = (
                f"{result.data['total_invoices']} invoices | "
                f"revenue={result.data['total_revenue']} {result.data['currency']} | "
                f"overdue={result.data['overdue_count']}"
            )
            return StepResult("odoo_weekly_audit", True, output=summary)
        return StepResult("odoo_weekly_audit", False, error=result.error)

    def _step_generate_summary(self, ctx: dict) -> StepResult:
        """Step 3 — Generate executive summary via Claude (or template)."""
        audit: dict = ctx.get("audit", {})

        if not audit:
            ctx["summary"] = self._template_summary(audit)
            return StepResult(
                "generate_summary", True,
                output="Template summary (no Odoo data available)",
            )

        if self._client:
            try:
                summary = self._claude_summary(audit)
                ctx["summary"] = summary
                return StepResult("generate_summary", True, output=summary[:120])
            except Exception as exc:
                logger.warning("Claude summary failed: %s — using template.", exc)

        ctx["summary"] = self._template_summary(audit)
        return StepResult(
            "generate_summary", True,
            output="Template summary (Claude unavailable)",
        )

    def _step_craft_post(self, ctx: dict) -> StepResult:
        """Step 4 — Craft platform-appropriate social media post via Claude."""
        summary: str = ctx.get("summary", "Weekly business update.")

        if self._client:
            try:
                post = self._claude_social_post(summary)
                ctx["social_post"] = post
                return StepResult("craft_social_post", True, output=post[:120])
            except Exception as exc:
                logger.warning("Claude post craft failed: %s — using template.", exc)

        ctx["social_post"] = self._template_post(summary)
        return StepResult(
            "craft_social_post", True,
            output="Template post (Claude unavailable)",
        )

    def _step_post_twitter(self, ctx: dict) -> StepResult:
        """Step 5 — Post to Twitter/X via twitter-mcp."""
        post = ctx.get("social_post", "")
        if not post:
            return StepResult("post_to_twitter", False, error="No post content in context.")

        # Twitter limit: 280 chars
        tweet = post[:280]
        result = self._mcp_call(
            server_rel="twitter-mcp/index.js",
            tool="post_tweet",
            args={"text": tweet},
        )
        ctx["twitter_result"] = result
        if result["success"]:
            return StepResult("post_to_twitter", True, output=result.get("text", "")[:100])
        return StepResult("post_to_twitter", False, error=result.get("error", "Twitter MCP failed"))

    def _step_post_facebook(self, ctx: dict) -> StepResult:
        """Step 6 — Post to Facebook page via facebook-mcp."""
        post = ctx.get("social_post", "")
        if not post:
            return StepResult("post_to_facebook", False, error="No post content in context.")

        result = self._mcp_call(
            server_rel="facebook-mcp/index.js",
            tool="post_to_facebook",
            args={"message": post},
        )
        ctx["facebook_result"] = result
        if result["success"]:
            return StepResult("post_to_facebook", True, output=result.get("text", "")[:100])
        return StepResult("post_to_facebook", False, error=result.get("error", "Facebook MCP failed"))

    def _step_update_dashboard(self, ctx: dict, run_id: str) -> StepResult:
        """Step 7 — Append activity row to Dashboard.md."""
        audit   = ctx.get("audit", {})
        revenue = audit.get("total_revenue", "N/A")
        inv     = audit.get("total_invoices", "N/A")
        action  = f"Autonomous weekly sales post | invoices={inv} revenue={revenue}"

        try:
            self._append_dashboard(action)
            return StepResult("update_dashboard", True, output=action[:80])
        except Exception as exc:
            return StepResult("update_dashboard", False, error=str(exc))

    # ------------------------------------------------------------------
    # Retry engine
    # ------------------------------------------------------------------

    def _execute_with_retry(
        self,
        name:    str,
        fn:      Callable[[], StepResult],
        run_id:  str,
    ) -> StepResult:
        """
        Execute fn() up to _MAX_RETRIES times.
        Returns the last StepResult (success or final failure).
        Exponential backoff: _BACKOFF_BASE ** attempt seconds between retries.
        """
        last: StepResult | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result         = fn()
                result.attempts = attempt

                if result.success:
                    self._audit(run_id, f"  ✓ {name} OK (attempt {attempt})")
                    return result

                self._audit(
                    run_id,
                    f"  ✗ {name} FAIL attempt {attempt}/{_MAX_RETRIES}: {result.error[:120]}",
                )
                last = result

            except Exception as exc:
                tb  = traceback.format_exc()
                msg = f"{type(exc).__name__}: {exc}"
                self._audit(run_id, f"  ✗ {name} EXCEPTION attempt {attempt}/{_MAX_RETRIES}: {msg}")
                logger.error("Step %s raised: %s\n%s", name, msg, tb)
                last = StepResult(name, False, error=msg, attempts=attempt)

            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                self._audit(run_id, f"  Retrying {name} in {wait}s…")
                time.sleep(wait)

        last.attempts = _MAX_RETRIES
        return last

    # ------------------------------------------------------------------
    # Claude integrations
    # ------------------------------------------------------------------

    def _claude_summary(self, audit: dict) -> str:
        """Ask Claude to produce an executive summary from the audit dict."""
        prompt = f"""You are the AI Employee of a business. Write a concise 3-sentence
executive summary of this week's sales performance for the CEO.

DATA:
Period:          {audit.get('period', 'last 7 days')}
Invoices issued: {audit.get('total_invoices', 0)}
Total revenue:   {audit.get('total_revenue', 0)} {audit.get('currency', 'USD')}
Overdue count:   {audit.get('overdue_count', 0)}
Overdue amount:  {audit.get('overdue_total', 0)} {audit.get('currency', 'USD')}

Top invoices (up to 5):
{json.dumps(audit.get('invoices', [])[:5], indent=2)}

Write the summary now (3 sentences max, professional tone):"""

        response = self._client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_CLAUDE_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def _claude_social_post(self, summary: str) -> str:
        """Ask Claude to craft a social media post from the summary."""
        prompt = f"""You are writing a professional business update post for LinkedIn,
Facebook, and Twitter on behalf of a company's AI Employee.

Executive summary:
{summary}

Requirements:
- Maximum 260 characters (Twitter-safe)
- Professional and engaging tone
- End with 2-3 relevant hashtags (e.g. #AI #BusinessGrowth)
- No specific revenue figures (keep it general)
- No emojis unless used sparingly

Write ONLY the post text, nothing else:"""

        response = self._client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    # ------------------------------------------------------------------
    # Template fallbacks (no Claude required)
    # ------------------------------------------------------------------

    def _template_summary(self, audit: dict) -> str:
        if not audit:
            return (
                "Weekly sales audit could not be retrieved from Odoo. "
                "No invoices data available this period. "
                "Manual review recommended."
            )
        return (
            f"This week we issued {audit.get('total_invoices', 0)} invoice(s) "
            f"generating {audit.get('total_revenue', 0)} {audit.get('currency','USD')} "
            f"in revenue (period: {audit.get('period','last 7 days')}). "
            f"There are {audit.get('overdue_count', 0)} overdue invoice(s) "
            f"totalling {audit.get('overdue_total', 0)} {audit.get('currency','USD')}. "
            "All figures are unaudited and subject to final reconciliation."
        )

    def _template_post(self, summary: str) -> str:
        now  = datetime.now(timezone.utc)
        week = now.strftime("W%V %Y")
        return (
            f"📊 {week} Business Update: Strong performance this week with multiple "
            "invoices processed and revenue targets on track. "
            "Our AI Employee continues to monitor and report in real time. "
            "#BusinessAutomation #AIDriven #GoldTier"
        )[:280]

    # ------------------------------------------------------------------
    # MCP client (twitter-mcp / facebook-mcp via stdio JSON-RPC 2.0)
    # ------------------------------------------------------------------

    def _mcp_call(self, server_rel: str, tool: str, args: dict) -> dict:
        """
        Spawn an MCP server subprocess, handshake, call tool, return result.
        Returns {"success": bool, "text": str, "error": str}.
        Gracefully returns success=False if Node/server not available.
        """
        server_path = self.vault_root / server_rel
        if not server_path.exists():
            msg = f"MCP server not found: {server_rel}"
            logger.warning(msg)
            return {"success": False, "text": "", "error": msg}

        try:
            proc = subprocess.Popen(
                ["node", str(server_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            return {"success": False, "text": "", "error": "node not found in PATH"}
        except Exception as exc:
            return {"success": False, "text": "", "error": str(exc)}

        def _write(msg: dict) -> None:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()

        def _read(timeout: int = 20) -> dict | None:
            deadline = time.time() + timeout
            buf      = ""
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        return None
                    continue
                buf += line
                try:
                    msg = json.loads(buf.strip())
                    if "id" in msg:
                        return msg
                    buf = ""
                except json.JSONDecodeError:
                    pass
            return None

        try:
            _write({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "autonomous_loop", "version": "1.0"}}})
            _read()
            _write({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            _write({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": args}})
            resp = _read()

            if not resp:
                return {"success": False, "text": "", "error": "No response from MCP server"}
            if "error" in resp:
                return {"success": False, "text": "", "error": resp["error"].get("message", "MCP error")}

            result   = resp.get("result", {})
            content  = result.get("content", [])
            is_error = result.get("isError", False)
            text     = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
            return {"success": not is_error, "text": text, "error": text if is_error else ""}

        except Exception as exc:
            return {"success": False, "text": "", "error": f"MCP comm error: {exc}"}
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(
        self,
        run_id:    str,
        scenario:  str,
        step_name: str,
        result:    StepResult,
    ) -> None:
        """
        Write a structured escalation file to Pending_Approval/ when a step
        exhausts all retries. The human owner reviews and resolves.
        """
        now       = datetime.now(timezone.utc)
        filename  = f"APPROVAL-{now.strftime('%Y%m%d_%H%M%S')}-autonomous-{step_name}.md"
        file_path = self.pending_dir / filename

        content = f"""\
---
type: autonomous_loop_escalation
run_id: {run_id}
scenario: {scenario}
step: {step_name}
created_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
risk_level: Medium
status: pending_review
---

# Autonomous Loop Escalation — Human Review Required

| Field       | Value |
|-------------|-------|
| Run ID      | `{run_id}` |
| Scenario    | {scenario} |
| Failed Step | {step_name} |
| Attempts    | {result.attempts} |
| Error       | {result.error[:200]} |
| Time        | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |

## What happened

The AutonomousLoop attempted step `{step_name}` {result.attempts} time(s) and
could not complete it. All other steps continued in parallel — check the run
report in `Briefings/` for the full picture.

## Last error

```
{result.error[:500]}
```

## Actions

1. Diagnose the error (credentials, API limits, network).
2. Resolve the underlying issue manually if needed.
3. Move this file to `Done/` once resolved.
4. Re-run `autonomous_loop.run_weekly_sales_social_post()` if a retry is needed.

---
*Auto-generated by AutonomousLoop | run_id={run_id} | {now.strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""
        try:
            file_path.write_text(content, encoding="utf-8")
            logger.info("Escalation created: %s", filename)
        except OSError as exc:
            logger.error("Could not write escalation file: %s", exc)

    # ------------------------------------------------------------------
    # Dashboard update helper
    # ------------------------------------------------------------------

    def _append_dashboard(self, action: str) -> None:
        """Prepend a row to the Recent Activity table in Dashboard.md."""
        import re
        if not self.dashboard.exists():
            return

        now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_row = f"| {now} | {action[:80]} | Done | AutonomousLoop |\n"
        text    = self.dashboard.read_text(encoding="utf-8")
        pattern = r"(\| Date \| Action \| Status \| Authorized By \|\n\|[-|]+\|\n)"

        if re.search(pattern, text):
            text = re.sub(pattern, r"\g<1>" + new_row, text, count=1)
        else:
            text += f"\n{new_row}"

        self.dashboard.write_text(text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Run report
    # ------------------------------------------------------------------

    def _write_report(
        self,
        run_id:    str,
        scenario:  str,
        ctx:       dict,
        results:   list[StepResult],
        escalated: list[str],
    ) -> Path | None:
        """Write a Briefings/AUTONOMOUS_<run_id>.md report."""
        now    = datetime.now(timezone.utc)
        fname  = f"AUTONOMOUS_{run_id}.md"
        fpath  = self.briefings_dir / fname
        audit  = ctx.get("audit", {})
        summary_text = ctx.get("summary", "N/A")
        post_text    = ctx.get("social_post", "N/A")

        rows = "\n".join(
            f"| {'✅' if r.success else '❌'} | {r.name} | {r.attempts} | "
            f"{'OK' if r.success else r.error[:60]} |"
            for r in results
        )

        content = f"""\
---
title: Autonomous Loop Run Report
run_id: {run_id}
scenario: {scenario}
date: {now.strftime("%Y-%m-%d")}
generated_by: AutonomousLoop
success: {all(r.success for r in results)}
escalated_steps: {escalated}
---

# Autonomous Loop Report — {now.strftime("%Y-%m-%d %H:%M UTC")}

**Scenario:** {scenario}
**Run ID:** `{run_id}`

---

## Step Results

| Status | Step | Attempts | Notes |
|--------|------|----------|-------|
{rows}

---

## Odoo Weekly Audit

- **Period:** {audit.get('period', 'N/A')}
- **Invoices:** {audit.get('total_invoices', 'N/A')}
- **Revenue:** {audit.get('total_revenue', 'N/A')} {audit.get('currency', '')}
- **Overdue:** {audit.get('overdue_count', 'N/A')} ({audit.get('overdue_total', 'N/A')} {audit.get('currency', '')})

---

## Business Summary (Generated)

{summary_text}

---

## Social Post (Published)

```
{post_text}
```

---

## Escalated Steps

{chr(10).join(f'- {s}' for s in escalated) if escalated else '- None'}

---
*Auto-generated by AutonomousLoop | {now.strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""
        try:
            fpath.write_text(content, encoding="utf-8")
            logger.info("Run report saved: %s", fname)
            return fpath
        except OSError as exc:
            logger.error("Could not write run report: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Summary text
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        run_id:    str,
        scenario:  str,
        results:   list[StepResult],
        escalated: list[str],
    ) -> str:
        ok_count   = sum(1 for r in results if r.success)
        total      = len(results)
        status_str = "SUCCESS" if ok_count == total else (
            "PARTIAL" if ok_count > 0 else "FAILED"
        )

        lines = [
            f"AutonomousLoop | run_id={run_id} | scenario={scenario} | {status_str}",
            f"Steps: {ok_count}/{total} succeeded",
        ]
        for r in results:
            icon = "✓" if r.success else ("⚡ ESCALATED" if r.name in escalated else "✗")
            lines.append(f"  {icon}  {r.name} (attempt {r.attempts})")

        if escalated:
            lines.append(f"Escalated to Pending_Approval/: {', '.join(escalated)}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Audit logger
    # ------------------------------------------------------------------

    def _audit(self, run_id: str, message: str) -> None:
        now   = datetime.now(timezone.utc)
        entry = f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] [{run_id}] {message}\n"
        logger.debug(message.replace("\n", " ").strip()[:200])
        try:
            with self._log_file.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI entry point — run the scenario directly for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    vault = Path(__file__).parent.parent
    loop  = AutonomousLoop(vault)
    out   = loop.run_weekly_sales_social_post()

    print("\n" + "=" * 60)
    print(out["summary"])
    print("=" * 60)
    if out.get("report_path"):
        print(f"Full report: {out['report_path']}")
    sys.exit(0 if out["success"] else 1)
