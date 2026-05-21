"""
orchestrator.py — Silver-tier AI Employee Orchestrator

Full autonomous loop:
  1. Scan Needs_Action/  → route to Plans/ or Pending_Approval/
  2. Scan Approved/      → execute via MCP (email-mcp), move to Done/
  3. Update Dashboard.md after every action
  4. Follow Company_Handbook.md rules at all times

Agent Skills used:
  SKILL-001 (PlanSkill)     — analyze items, create Plans/Plan_*.md
  SKILL-003 (DashboardSkill) — update Dashboard.md
  SKILL-004 (ApprovalSkill) — detect sensitive actions, create Pending_Approval/*.md

Approved file format (Approved/*.md must contain action metadata):
  The approval files created by SKILL-004 carry all needed parameters.
  Orchestrator parses them to reconstruct the original action.

Usage (Agent Skill):
    python orchestrator.py                # continuous loop (30s interval)
    python orchestrator.py --once         # single cycle, then exit
    python orchestrator.py --skill 001    # run only SKILL-001 (plan generation)
    python orchestrator.py --skill 004    # run only SKILL-004 (approval check)
    python orchestrator.py --dry-run      # analyze only, no writes
    python orchestrator.py --interval 60  # custom poll interval
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_VAULT_ROOT = Path(__file__).parent
sys.path.insert(0, str(_VAULT_ROOT))

from skills.approval_skill   import ApprovalSkill
from skills.plan_skill        import PlanSkill
from skills.dashboard_skill   import DashboardSkill
from skills.mcp_client        import MCPEmailClient

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_LOG_DIR  = _VAULT_ROOT / "Logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_DIR / "orchestrator.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Orchestrator")

# ---------------------------------------------------------------------------
# State tracking — prevents re-processing files across restarts
# ---------------------------------------------------------------------------
_STATE_FILE = _LOG_DIR / "orchestrator_state.json"


def _load_state() -> set[str]:
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            return set(data.get("processed", []))
        except Exception:
            pass
    return set()


def _save_state(processed: set[str]) -> None:
    try:
        _STATE_FILE.write_text(
            json.dumps({"processed": sorted(processed)}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Could not save state: %s", e)


# ---------------------------------------------------------------------------
# Approved action parser
# ---------------------------------------------------------------------------

def _parse_approved_action(file_path: Path) -> dict | None:
    """
    Read an Approved/*.md file and extract the action to execute.
    Returns dict with keys: action_type, source_file, content, raw_approval
    or None if parsing fails.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Extract frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    frontmatter = {}
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                frontmatter[k.strip()] = v.strip()

    action_type  = frontmatter.get("action_type", "")
    source_file  = frontmatter.get("source_file", "")

    return {
        "action_type":  action_type,
        "source_file":  source_file,
        "raw_approval": text,
        "frontmatter":  frontmatter,
    }


def _extract_email_params(approval_text: str) -> dict:
    """
    Try to pull email To/Subject/Body from the original content
    embedded in an approval file.

    Heuristic: look for From/To/Subject in the quoted content block.
    """
    params = {"to": "", "subject": "", "body": ""}

    to_match = re.search(r'\|\s*(?:To|Recipient)\s*\|\s*([^\|]+)\|', approval_text, re.IGNORECASE)
    if to_match:
        params["to"] = to_match.group(1).strip()

    subj_match = re.search(r'\|\s*Subject\s*\|\s*([^\|]+)\|', approval_text, re.IGNORECASE)
    if subj_match:
        params["subject"] = subj_match.group(1).strip()

    # Extract From field as fallback for "to"
    from_match = re.search(r'\|\s*From\s*\|\s*([^\|]+)\|', approval_text, re.IGNORECASE)
    if from_match and not params["to"]:
        params["to"] = from_match.group(1).strip()

    # Body: extract text between ``` markers
    body_match = re.search(r'```\s*\n(.*?)\n```', approval_text, re.DOTALL)
    if body_match:
        params["body"] = body_match.group(1).strip()[:2000]

    return params


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Main Silver-tier orchestrator.

    Cycle:
      1. _process_needs_action() — route new items
      2. _process_approved()     — execute approved actions via MCP
      3. Dashboard update
    """

    def __init__(self, dry_run: bool = False) -> None:
        self.vault_root      = _VAULT_ROOT
        self.needs_action_dir = self.vault_root / "Needs_Action"
        self.approved_dir     = self.vault_root / "Approved"
        self.done_dir         = self.vault_root / "Done"
        self.plans_dir        = self.vault_root / "Plans"
        self.pending_dir      = self.vault_root / "Pending_Approval"
        self.logs_dir         = self.vault_root / "Logs"
        self.dry_run          = dry_run

        # Ensure all folders exist
        for d in [self.needs_action_dir, self.approved_dir, self.done_dir,
                  self.plans_dir, self.pending_dir, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Skills
        self.approval_skill   = ApprovalSkill(self.vault_root)
        self.plan_skill       = PlanSkill(self.vault_root)
        self.dashboard_skill  = DashboardSkill(self.vault_root)
        self.mcp_client       = MCPEmailClient(self.vault_root)

        # State
        self._processed: set[str] = _load_state()
        self._running = False

        logger.info("Orchestrator initialized (dry_run=%s)", dry_run)
        logger.info("Vault root: %s", self.vault_root)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, once: bool = False, interval: int = 30) -> None:
        """Start the orchestration loop."""
        self._running = True
        logger.info("Orchestrator started. Press Ctrl+C to stop.")

        while self._running:
            try:
                self._cycle()
            except Exception as e:
                logger.error("Unexpected error in cycle: %s", e, exc_info=True)

            if once:
                break

            logger.debug("Sleeping %ds before next cycle…", interval)
            time.sleep(interval)

        logger.info("Orchestrator stopped.")

    def _cycle(self) -> None:
        """One full orchestration cycle."""
        logger.info("--- Cycle start ---")
        stats = {"needs_processed": 0, "approvals_created": 0,
                 "plans_created": 0, "actions_executed": 0}

        stats.update(self._process_needs_action())
        stats.update(self._process_approved())

        if stats["approvals_created"] or stats["plans_created"] or stats["actions_executed"]:
            summary = (
                f"Cycle: {stats['needs_processed']} items scanned | "
                f"{stats['approvals_created']} approval(s) | "
                f"{stats['plans_created']} plan(s) | "
                f"{stats['actions_executed']} action(s) executed"
            )
            if not self.dry_run:
                self.dashboard_skill.refresh_pending_counts()
            logger.info(summary)
        else:
            logger.debug("Cycle complete — nothing new to process.")

    # ------------------------------------------------------------------
    # SKILL-001 + SKILL-004: Process Needs_Action
    # ------------------------------------------------------------------

    def _process_needs_action(self) -> dict:
        """
        Scan Needs_Action/ and route each unprocessed .md file to either:
          - Pending_Approval/ (sensitive action detected)
          - Plans/            (safe to plan immediately)
        """
        counts = {"needs_processed": 0, "approvals_created": 0, "plans_created": 0}

        md_files = sorted(self.needs_action_dir.glob("*.md"))
        if not md_files:
            logger.debug("Needs_Action is empty.")
            return counts

        for file_path in md_files:
            file_key = f"needs_action::{file_path.name}"

            if file_key in self._processed:
                logger.debug("Already processed, skipping: %s", file_path.name)
                continue

            logger.info("Processing: %s", file_path.name)
            counts["needs_processed"] += 1

            try:
                if self.approval_skill.needs_approval(file_path):
                    # SKILL-004: Create approval request
                    logger.info(
                        "Sensitive action detected — routing to Pending_Approval: %s",
                        file_path.name,
                    )
                    if not self.dry_run:
                        approval_path = self.approval_skill.create_approval(file_path)
                        self.dashboard_skill.update(
                            f"Approval request created for {file_path.name}",
                            status="Pending_Approval",
                            authorized_by="ApprovalSkill (SKILL-004)",
                        )
                        logger.info("Approval created: %s", approval_path.name)
                    counts["approvals_created"] += 1

                else:
                    # SKILL-001: Generate plan
                    logger.info("Safe action — generating plan: %s", file_path.name)
                    if not self.dry_run:
                        plan_path = self.plan_skill.create_plan(file_path)
                        self.dashboard_skill.update(
                            f"Plan created for {file_path.name} → {plan_path.name}",
                            status="In Planning",
                            authorized_by="PlanSkill (SKILL-001)",
                        )
                        logger.info("Plan created: %s", plan_path.name)
                    counts["plans_created"] += 1

            except Exception as e:
                logger.error("Error processing %s: %s", file_path.name, e, exc_info=True)
                continue

            # Mark as processed (regardless of dry_run, to avoid infinite loops)
            self._processed.add(file_key)
            _save_state(self._processed)

        return counts

    # ------------------------------------------------------------------
    # Execute approved actions via MCP
    # ------------------------------------------------------------------

    def _process_approved(self) -> dict:
        """
        Scan Approved/ for files ready to execute.
        Parse action type → call MCP tool → move to Done/.
        """
        counts = {"actions_executed": 0}

        approved_files = sorted(self.approved_dir.glob("*.md"))
        if not approved_files:
            logger.debug("Approved/ is empty.")
            return counts

        for file_path in approved_files:
            file_key = f"approved::{file_path.name}"

            if file_key in self._processed:
                logger.debug("Already executed, skipping: %s", file_path.name)
                continue

            logger.info("Executing approved action: %s", file_path.name)
            action = _parse_approved_action(file_path)

            if not action:
                logger.warning("Could not parse approved file: %s", file_path.name)
                self._processed.add(file_key)
                continue

            success = self._execute_action(action, file_path)
            counts["actions_executed"] += 1

            if not self.dry_run:
                # Move to Done/ regardless of success (log failure, don't retry blindly)
                done_path = self.done_dir / file_path.name
                try:
                    shutil.move(str(file_path), str(done_path))
                    logger.info("Moved to Done: %s", file_path.name)
                except OSError as e:
                    logger.error("Could not move to Done: %s", e)

                status = "Done" if success else "Failed — check logs"
                self.dashboard_skill.update(
                    f"Executed: {file_path.name} → {status}",
                    status=status,
                    authorized_by="Orchestrator + MCP",
                )

            self._processed.add(file_key)
            _save_state(self._processed)

        return counts

    def _execute_action(self, action: dict, file_path: Path) -> bool:
        """
        Route action to the correct MCP tool based on action_type.
        Returns True on success.
        """
        atype = action.get("action_type", "")
        text  = action.get("raw_approval", "")

        logger.info("Action type: %s | File: %s", atype, file_path.name)

        if self.dry_run:
            logger.info("[DRY RUN] Would execute: %s", atype)
            return True

        # Email send
        if atype == "email_send":
            return self._execute_email(text, send=True)

        # Email draft (for anything else flagged for approval — safer)
        if atype in ("whatsapp_message", "linkedin_action", "unknown"):
            return self._execute_email(text, send=False)

        # File operation — just log it
        if atype == "file_operation":
            logger.info("File operation approved — no automated action required.")
            self._append_log(f"File operation approved: {file_path.name}")
            return True

        logger.warning("No MCP handler for action_type=%s — logged only.", atype)
        self._append_log(f"Approved but no handler: {file_path.name} (type={atype})")
        return True

    def _execute_email(self, approval_text: str, send: bool) -> bool:
        """Parse email params from approval text and call email-mcp."""
        params = _extract_email_params(approval_text)

        if not params["to"]:
            logger.error("Cannot execute email: no recipient found in approval file.")
            return False

        if not params["subject"]:
            params["subject"] = "Re: Action Required"
        if not params["body"]:
            params["body"] = (
                "Dear recipient,\n\n"
                "Please see the attached action item that has been approved for follow-up.\n\n"
                "Best regards,\nAI Employee"
            )

        if send:
            logger.info("Sending email to: %s | Subject: %s", params["to"][:40], params["subject"][:40])
            result = self.mcp_client.send_email(
                to=params["to"],
                subject=params["subject"],
                body=params["body"],
            )
        else:
            logger.info("Drafting email to: %s | Subject: %s", params["to"][:40], params["subject"][:40])
            result = self.mcp_client.draft_email(
                to=params["to"],
                subject=params["subject"],
                body=params["body"],
            )

        if result["success"]:
            logger.info("MCP success: %s", result["text"][:100])
        else:
            logger.error("MCP error: %s", result["error"])

        return result["success"]

    # ------------------------------------------------------------------
    # Individual skill runners (for --skill flag)
    # ------------------------------------------------------------------

    def run_skill_001(self) -> None:
        """SKILL-001: Generate plans for all unprocessed Needs_Action items."""
        logger.info("Running SKILL-001 (PlanSkill) standalone…")
        for f in sorted(self.needs_action_dir.glob("*.md")):
            key = f"needs_action::{f.name}"
            if key not in self._processed:
                path = self.plan_skill.create_plan(f)
                logger.info("Plan: %s", path.name)
                self._processed.add(key)
        _save_state(self._processed)
        logger.info("SKILL-001 complete.")

    def run_skill_004(self) -> None:
        """SKILL-004: Check all Needs_Action items for approval requirements."""
        logger.info("Running SKILL-004 (ApprovalSkill) standalone…")
        for f in sorted(self.needs_action_dir.glob("*.md")):
            key = f"needs_action::{f.name}"
            if key not in self._processed:
                if self.approval_skill.needs_approval(f):
                    path = self.approval_skill.create_approval(f)
                    logger.info("Approval: %s", path.name)
                else:
                    logger.info("No approval needed: %s", f.name)
                self._processed.add(key)
        _save_state(self._processed)
        logger.info("SKILL-004 complete.")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_log(self, message: str) -> None:
        now      = datetime.now(timezone.utc)
        log_file = self.logs_dir / "orchestrator.log"
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] {message}\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Silver-tier AI Employee Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Skills:
  001  Generate plans for Needs_Action items (SKILL-001)
  004  Check items for approval requirements (SKILL-004)

Examples:
  python orchestrator.py                  # continuous loop
  python orchestrator.py --once           # single cycle
  python orchestrator.py --skill 001      # plan generation only
  python orchestrator.py --dry-run --once # preview without writing
""",
    )
    p.add_argument("--once",     action="store_true", help="Run one cycle then exit")
    p.add_argument("--dry-run",  action="store_true", help="Analyze only — no files written, no MCP calls")
    p.add_argument("--skill",    choices=["001", "004"],  help="Run a specific skill standalone")
    p.add_argument("--interval", type=int, default=30,   help="Poll interval in seconds (default: 30)")
    return p


def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[Orchestrator] Shutdown signal received…")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args   = _build_parser().parse_args()
    orch   = Orchestrator(dry_run=args.dry_run)

    if args.skill == "001":
        orch.run_skill_001()
    elif args.skill == "004":
        orch.run_skill_004()
    else:
        orch.run(once=args.once, interval=args.interval)
