"""
CEOBriefingSkill — SKILL-009
Gold Tier: Weekly Business Intelligence report delivered to the CEO.

Aggregates data from:
  - Vault activity logs (all Watcher + Orchestrator logs)
  - Odoo accounting (AR, AP, overdue, weekly revenue)
  - Social media (FB, IG, Twitter summaries from MCP)
  - Needs_Action / Pending_Approval queue depth

Uses Claude to write an executive summary, then:
  - Saves to Briefings/CEO_BRIEFING_<date>.md
  - Sends via email (email-mcp)
  - Updates Dashboard

Usage:
    from skills.ceo_briefing_skill import CEOBriefingSkill

    skill = CEOBriefingSkill(vault_root)
    result = skill.generate_and_deliver(send_email=True)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("CEOBriefingSkill")

try:
    import anthropic as _anthropic
    _CLAUDE_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))
except ImportError:
    _CLAUDE_AVAILABLE = False


class CEOBriefingSkill:
    """SKILL-009 — Weekly CEO Briefing generator."""

    MODEL      = "claude-sonnet-4-6"
    MAX_TOKENS = 2048

    def __init__(self, vault_root: Path) -> None:
        self.vault_root     = Path(vault_root)
        self.briefings_dir  = self.vault_root / "Briefings"
        self.logs_dir       = self.vault_root / "Logs"
        self.needs_dir      = self.vault_root / "Needs_Action"
        self.pending_dir    = self.vault_root / "Pending_Approval"
        self.done_dir       = self.vault_root / "Done"
        self.briefings_dir.mkdir(parents=True, exist_ok=True)

        self._client = None
        if _CLAUDE_AVAILABLE:
            self._client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            logger.info("CEOBriefingSkill initialized with Claude %s.", self.MODEL)

        self._ceo_email = os.environ.get("CEO_EMAIL", "")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate_and_deliver(self, send_email: bool = True) -> dict:
        """Generate weekly briefing and optionally email it."""
        now  = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")

        logger.info("Generating CEO briefing for week ending %s…", date)

        # 1. Gather all data sources
        raw_data = self._collect_data(now)

        # 2. Generate executive summary with Claude (or template)
        summary = self._generate_summary(raw_data, now)

        # 3. Build full briefing document
        briefing = self._build_briefing(summary, raw_data, now)

        # 4. Save to Briefings/
        fname    = f"CEO_BRIEFING_{date}.md"
        fpath    = self.briefings_dir / fname
        fpath.write_text(briefing, encoding="utf-8")
        logger.info("Briefing saved: %s", fname)

        # 5. Send email if requested
        email_sent = False
        if send_email and self._ceo_email:
            email_sent = self._send_email(briefing, date)

        return {
            "success":    True,
            "file":       str(fpath),
            "email_sent": email_sent,
            "date":       date,
        }

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _collect_data(self, now: datetime) -> dict:
        week_ago = now - timedelta(days=7)

        data = {
            "period":          f"{week_ago.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}",
            "needs_action":    len(list(self.needs_dir.glob("*.md"))),
            "pending":         len(list(self.pending_dir.glob("*.md"))),
            "done_this_week":  self._count_done_this_week(week_ago),
            "log_activity":    self._parse_logs(week_ago),
            "odoo_summary":    self._get_odoo_summary(),
            "social_summary":  self._get_social_summary(),
            "company_goals":   self._load_file("Business_Goals.md")[:800],
        }

        return data

    def _count_done_this_week(self, since: datetime) -> int:
        count = 0
        for f in self.done_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime >= since:
                    count += 1
            except Exception:
                pass
        return count

    def _parse_logs(self, since: datetime) -> str:
        lines = []
        for log_file in self.logs_dir.glob("*.log"):
            try:
                content = log_file.read_text(encoding="utf-8", errors="ignore")
                recent = [l for l in content.splitlines()[-200:] if l.strip()]
                lines.extend(recent[-20:])
            except Exception:
                pass
        return "\n".join(lines[-50:]) if lines else "No log data available."

    def _get_odoo_summary(self) -> str:
        server = self.vault_root / "odoo-mcp" / "index.js"
        if not server.exists():
            return "Odoo MCP not available."
        try:
            result = self._mcp_call(server, "run_weekly_audit", {})
            return result.get("text", "Odoo audit failed.")[:1500]
        except Exception as e:
            return f"Odoo unavailable: {e}"

    def _get_social_summary(self) -> str:
        fb_server = self.vault_root / "facebook-mcp" / "index.js"
        tw_server = self.vault_root / "twitter-mcp" / "index.js"
        parts = []

        if fb_server.exists():
            try:
                r = self._mcp_call(fb_server, "get_social_summary", {})
                parts.append(r.get("text", "FB/IG unavailable")[:500])
            except Exception:
                parts.append("Facebook/Instagram: unavailable")

        if tw_server.exists():
            try:
                r = self._mcp_call(tw_server, "get_twitter_summary", {})
                parts.append(r.get("text", "Twitter unavailable")[:500])
            except Exception:
                parts.append("Twitter: unavailable")

        return "\n\n".join(parts) if parts else "Social media data unavailable."

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    def _generate_summary(self, data: dict, now: datetime) -> str:
        if not self._client:
            return self._template_summary(data, now)

        prompt = f"""You are the AI Employee briefing system for a business.
Write a concise, executive-style CEO weekly briefing based on the data below.

FORMAT:
1. Executive Summary (3-4 sentences) — overall health and top priority
2. Operations (2-3 bullets) — what was processed this week
3. Finance (2-3 bullets) — accounting status from Odoo
4. Social Media (2-3 bullets) — engagement and reach
5. Action Items for CEO (max 3) — what needs human decision

TONE: Professional, direct, data-driven. No filler sentences.

DATA:
Period: {data['period']}
Items in Needs_Action: {data['needs_action']}
Items Pending Approval: {data['pending']}
Items Completed: {data['done_this_week']}

ODOO ACCOUNTING:
{data['odoo_summary'][:800]}

SOCIAL MEDIA:
{data['social_summary'][:600]}

BUSINESS GOALS:
{data['company_goals'][:400]}

Write the briefing now:"""

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning("Claude briefing failed: %s — using template.", e)
            return self._template_summary(data, now)

    def _template_summary(self, data: dict, now: datetime) -> str:
        return f"""## Executive Summary

The AI Employee processed {data['done_this_week']} items this week. There are currently
{data['needs_action']} items awaiting action and {data['pending']} awaiting approval.

## Operations
- Items completed this week: {data['done_this_week']}
- Needs Action queue depth: {data['needs_action']}
- Pending approvals: {data['pending']}

## Finance
{data['odoo_summary'][:400] if data['odoo_summary'] else '- Odoo data unavailable'}

## Social Media
{data['social_summary'][:300] if data['social_summary'] else '- Social data unavailable'}

## Action Items for CEO
- Review {data['pending']} item(s) in Pending_Approval/
- Check overdue invoices in Odoo dashboard
- Review social media engagement and approve scheduled posts"""

    # ------------------------------------------------------------------
    # Document builder
    # ------------------------------------------------------------------

    def _build_briefing(self, summary: str, data: dict, now: datetime) -> str:
        return f"""\
---
title: CEO Weekly Briefing
date: {now.strftime("%Y-%m-%d")}
period: {data['period']}
generated_by: CEOBriefingSkill (SKILL-009)
model: {self.MODEL if self._client else 'template'}
---

# CEO Weekly Briefing — {now.strftime("%B %d, %Y")}

**Period:** {data['period']}
**Generated:** {now.strftime("%Y-%m-%d %H:%M UTC")}

---

{summary}

---

## Raw Metrics

| Metric | Value |
|--------|-------|
| Needs Action | {data['needs_action']} |
| Pending Approval | {data['pending']} |
| Completed This Week | {data['done_this_week']} |

## Odoo Accounting

```
{data['odoo_summary'][:1000]}
```

## Social Media

```
{data['social_summary'][:600]}
```

---
*Auto-generated by CEOBriefingSkill (SKILL-009) — Gold Tier AI Employee.*
"""

    # ------------------------------------------------------------------
    # Email delivery
    # ------------------------------------------------------------------

    def _send_email(self, briefing: str, date: str) -> bool:
        server = self.vault_root / "email-mcp" / "index.js"
        if not server.exists():
            logger.warning("email-mcp not found — cannot send briefing email.")
            return False

        result = self._mcp_call(server, "send_email", {
            "to":      self._ceo_email,
            "subject": f"Weekly CEO Briefing — {date}",
            "body":    briefing[:4000],
        })

        if result.get("success"):
            logger.info("Briefing emailed to %s.", self._ceo_email)
            return True
        else:
            logger.error("Email failed: %s", result.get("error", "unknown"))
            return False

    # ------------------------------------------------------------------
    # MCP helper
    # ------------------------------------------------------------------

    def _mcp_call(self, server_path: Path, tool: str, args: dict) -> dict:
        msg_id = 1
        proc = subprocess.Popen(
            ["node", str(server_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            def write(msg):
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()

            def read():
                import time
                deadline = time.time() + 20
                buf = ""
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

            write({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ceo_briefing","version":"1.0"}}})
            read()
            write({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
            write({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":tool,"arguments":args}})
            resp = read()

            if not resp:
                return {"success": False, "error": "No response"}
            result  = resp.get("result", {})
            content = result.get("content", [])
            text    = " ".join(c.get("text","") for c in content if c.get("type") == "text")
            return {"success": not result.get("isError", False), "text": text}
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    def _load_file(self, filename: str) -> str:
        path = self.vault_root / filename
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
