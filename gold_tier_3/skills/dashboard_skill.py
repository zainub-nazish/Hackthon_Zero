"""
DashboardSkill — SKILL-003
Keeps Dashboard.md current: Recent Activity table + Pending Tasks checklist.
Runs automatically after every other skill execution.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("DashboardSkill")


class DashboardSkill:
    """
    SKILL-003 — Dashboard.md updater.

    Usage:
        skill = DashboardSkill(vault_root)
        skill.log_activity("Email sent to client@example.com", "Done", "AI Employee")
        skill.refresh_pending_counts()
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root      = Path(vault_root)
        self.dashboard_path  = self.vault_root / "Dashboard.md"
        self.logs_dir        = self.vault_root / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_activity(
        self,
        action: str,
        status: str = "Done",
        authorized_by: str = "AI Employee",
    ) -> None:
        """Append a row to the Recent Activity table in Dashboard.md."""
        if not self.dashboard_path.exists():
            logger.warning("Dashboard.md not found at %s", self.dashboard_path)
            return

        now     = datetime.now(timezone.utc)
        date    = now.strftime("%Y-%m-%d %H:%M UTC")
        new_row = f"| {date} | {action[:80]} | {status} | {authorized_by} |\n"

        text = self.dashboard_path.read_text(encoding="utf-8")

        # Insert after the header row of Recent Activity table
        pattern = r'(\| Date \| Action \| Status \| Authorized By \|\n\|[-|]+\|\n)'
        if re.search(pattern, text):
            text = re.sub(pattern, r'\g<1>' + new_row, text, count=1)
        else:
            # Fallback: append to end of Recent Activity section
            text += f"\n{new_row}"

        self.dashboard_path.write_text(text, encoding="utf-8")
        self._log(f"SKILL-003 — Dashboard.md activity logged: {action[:60]}")
        logger.debug("Dashboard updated: %s", action[:60])

    def refresh_pending_counts(self) -> dict[str, int]:
        """
        Count files in each vault folder and update the
        last_updated timestamp in Dashboard.md frontmatter.
        Returns folder counts for logging.
        """
        folders = ["Needs_Action", "Pending_Approval", "Approved", "Done", "Inbox"]
        counts  = {}
        for folder in folders:
            d = self.vault_root / folder
            counts[folder] = len(list(d.glob("*.md"))) if d.exists() else 0

        # Update the last_updated frontmatter field
        if self.dashboard_path.exists():
            text = self.dashboard_path.read_text(encoding="utf-8")
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            text = re.sub(
                r'^(last_updated:\s*).*$',
                rf'\g<1>{now}',
                text,
                flags=re.MULTILINE,
            )
            self.dashboard_path.write_text(text, encoding="utf-8")

        logger.debug("Folder counts: %s", counts)
        return counts

    def update(self, action: str, status: str = "Done", authorized_by: str = "AI Employee") -> None:
        """Convenience: log activity + refresh counts in one call."""
        self.log_activity(action, status, authorized_by)
        self.refresh_pending_counts()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        now      = datetime.now(timezone.utc)
        log_file = self.logs_dir / "dashboard_skill.log"
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] {message}\n")
        except OSError:
            pass
