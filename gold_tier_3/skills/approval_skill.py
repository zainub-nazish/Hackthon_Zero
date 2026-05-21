"""
ApprovalSkill — SKILL-004
Detects sensitive actions and creates structured approval requests
in Pending_Approval/ instead of proceeding automatically.

Approval thresholds (Company_Handbook.md):
  - Any email send action              → ALWAYS needs approval
  - LinkedIn post with business intent → needs approval
  - Any payment/expense > $100         → needs approval (Handbook rule)
  - LinkedIn with pricing/proposal     → needs approval if value > $50
  - WhatsApp/email mentioning payment  → needs approval if amount > $100
  - File deletion / external sharing   → needs approval
  - Anything flagged suspicious        → needs approval

Auto-processable (no approval):
  - Informational emails (read-only)
  - WhatsApp keyword alerts (informational)
  - File metadata notes
  - Payments < $100
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("ApprovalSkill")


# ---------------------------------------------------------------------------
# Sensitive action detection rules
# ---------------------------------------------------------------------------

# Keywords that signal a financial transaction in the text
_PAYMENT_KEYWORDS = re.compile(
    r'\b(payment|invoice|expense|charge|fee|cost|price|bill|quote|proposal|budget|'
    r'purchase|subscription|pay|refund|deposit|transfer)\b',
    re.IGNORECASE,
)

# Dollar amount extractor — matches $50, $1,000, USD 200, etc.
_AMOUNT_RE = re.compile(
    r'(?:USD?|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)',
    re.IGNORECASE,
)

# Action types derived from filename prefix
_ACTION_TYPE_MAP = {
    "EMAIL_":      "email_send",
    "WHATSAPP_":   "whatsapp_message",
    "LINKEDIN_":   "linkedin_action",
    "FILE_":       "file_operation",
    "APPROVAL-":   "approval_request",   # already an approval, skip
}


def _extract_amounts(text: str) -> list[float]:
    """Pull all dollar amounts from text, return as floats."""
    amounts = []
    for m in _AMOUNT_RE.finditer(text):
        try:
            amounts.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return amounts


def _action_type(filename: str) -> str:
    for prefix, atype in _ACTION_TYPE_MAP.items():
        if filename.startswith(prefix):
            return atype
    return "unknown"


# ---------------------------------------------------------------------------
# ApprovalSkill
# ---------------------------------------------------------------------------

class ApprovalSkill:
    """
    SKILL-004 — Sensitive action detection and approval request generator.

    Usage:
        skill = ApprovalSkill(vault_root)
        if skill.needs_approval(path_to_needs_action_file):
            skill.create_approval(path_to_needs_action_file)
    """

    PAYMENT_THRESHOLD     = 100.0   # Company_Handbook: >$100 needs approval
    LINKEDIN_THRESHOLD    = 50.0    # User spec: LinkedIn post >$50 value
    APPROVAL_THRESHOLD    = 50.0    # Minimum dollar amount to trigger approval

    def __init__(self, vault_root: Path) -> None:
        self.vault_root      = Path(vault_root)
        self.pending_dir     = self.vault_root / "Pending_Approval"
        self.logs_dir        = self.vault_root / "Logs"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def needs_approval(self, file_path: Path) -> bool:
        """
        Returns True if this Needs_Action file requires human approval
        before any action can be taken.
        """
        name = file_path.name
        atype = _action_type(name)
        content = self._read(file_path)

        # Already an approval file — skip
        if atype == "approval_request":
            return False

        # Rule 1: Email sends always need approval (sensitive outbound action)
        if atype == "email_send":
            logger.debug("Approval needed: email send is always sensitive.")
            return True

        # Rule 2: LinkedIn with business-intent keywords
        if atype == "linkedin_action":
            biz_keywords = re.compile(
                r'\b(sales|inquiry|proposal|pricing|contract|deal|partnership|'
                r'investment|revenue|client|customer|prospect)\b',
                re.IGNORECASE,
            )
            if biz_keywords.search(content):
                amounts = _extract_amounts(content)
                if not amounts or any(a >= self.LINKEDIN_THRESHOLD for a in amounts):
                    logger.debug("Approval needed: LinkedIn action with business intent.")
                    return True

        # Rule 3: Any mention of payment/invoice with amount > threshold
        if _PAYMENT_KEYWORDS.search(content):
            amounts = _extract_amounts(content)
            if amounts and max(amounts) > self.PAYMENT_THRESHOLD:
                logger.debug(
                    "Approval needed: payment keyword + amount $%.2f > $%.2f",
                    max(amounts), self.PAYMENT_THRESHOLD,
                )
                return True
            # Even without explicit amount, >$100 payment mentions need approval
            if not amounts and _PAYMENT_KEYWORDS.search(content):
                # Conservative: if payment keywords present but no amount found,
                # still flag for approval
                logger.debug("Approval needed: payment keywords with no parseable amount.")
                return True

        # Rule 4: Suspicious/security keywords
        suspicious = re.compile(
            r'\b(delete|remove|destroy|wipe|external|share|export|transfer|'
            r'credentials?|password|secret|token|api.?key)\b',
            re.IGNORECASE,
        )
        if suspicious.search(content):
            logger.debug("Approval needed: suspicious/security keyword found.")
            return True

        return False

    def create_approval(self, source_file: Path) -> Path:
        """
        Create a structured approval request in Pending_Approval/.
        Returns the path to the created approval file.
        """
        now   = datetime.now(timezone.utc)
        date  = now.strftime("%Y-%m-%d")
        ts    = now.strftime("%Y%m%d_%H%M%S")
        name  = source_file.stem[:40]
        atype = _action_type(source_file.name)

        approval_filename = f"APPROVAL-{date}-{name}.md"
        approval_path     = self.pending_dir / approval_filename

        # Avoid overwriting an existing approval for the same file
        if approval_path.exists():
            logger.info("Approval already exists: %s", approval_filename)
            return approval_path

        content      = self._read(source_file)
        risk_level   = self._assess_risk(atype, content)
        amounts      = _extract_amounts(content)
        amount_str   = f"${max(amounts):,.2f}" if amounts else "N/A"
        action_label = self._action_label(atype, source_file.name)

        approval_content = f"""\
---
type: approval_request
source_file: {source_file.name}
action_type: {atype}
created_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
risk_level: {risk_level}
status: pending_approval
expires_at: {now.strftime("%Y-%m-%d")} + 48h
---

# APPROVAL REQUEST

> **APPROVAL REQUIRED: {action_label}** | Amount: {amount_str} | Awaiting sign-off.

---

## Details

| Field              | Value |
|--------------------|-------|
| Requested by       | AI Employee (Silver Tier) |
| Date               | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| Source file        | `{source_file.name}` |
| Action type        | {atype} |
| Estimated value    | {amount_str} |
| Risk level         | **{risk_level}** |
| Expires in         | 48 hours |
| Awaiting approval  | Human Owner |

## Reason

The following action was detected and flagged per Company Handbook rules:

> *Any payment > $100, email sends, LinkedIn business actions, and security-sensitive
> operations require human approval before execution.*

## Original Content Summary

```
{content[:1500]}
```

## Actions

To **approve**: Move this file to `Approved/` folder.
To **reject**: Move this file to `Rejected/` folder.
To **defer**: Leave in `Pending_Approval/` (will re-flag after 48 hours).

---
*Auto-generated by ApprovalSkill (SKILL-004) on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
*Reference: Company_Handbook.md — Approval Rules*
"""

        approval_path.write_text(approval_content, encoding="utf-8")
        self._log(f"SKILL-004 — Approval request created: {approval_filename}")
        logger.info("Approval created: %s (risk=%s)", approval_filename, risk_level)
        return approval_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _assess_risk(self, atype: str, content: str) -> str:
        amounts = _extract_amounts(content)
        max_amount = max(amounts) if amounts else 0.0

        if max_amount > 1000 or atype in ("email_send",):
            return "High"
        if max_amount > 100 or atype == "linkedin_action":
            return "Medium"
        return "Low"

    def _action_label(self, atype: str, filename: str) -> str:
        labels = {
            "email_send":       "Send Email",
            "whatsapp_message": "WhatsApp Message Response",
            "linkedin_action":  "LinkedIn Business Action",
            "file_operation":   "File Operation",
        }
        return labels.get(atype, f"Action: {filename[:40]}")

    def _log(self, message: str) -> None:
        now      = datetime.now(timezone.utc)
        log_file = self.logs_dir / "approval_skill.log"
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] {message}\n")
        except OSError:
            pass
