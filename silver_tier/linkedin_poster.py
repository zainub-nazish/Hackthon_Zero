"""
linkedin_poster.py — Silver-tier LinkedIn Auto-Poster

Flow:
  1. LinkedInPostSkill generates a post from Business_Goals.md + Dashboard.md
  2. If approval_needed → save to Pending_Approval/ and stop
  3. If clear → post directly to LinkedIn via Playwright (reuses linkedin_profile/)
  4. Log everything to Logs/linkedin_poster.log

Schedule:
  --schedule   run once then sleep 24 hours, repeat (daemon mode)
  --now        post immediately and exit (one-shot)
  --preview    generate and print post, no browser, no files written
  --approve    post a file from Pending_Approval/ by filename

LinkedIn session reuse:
  Shares the same Chromium profile as linkedin_watcher.py
  (Logs/linkedin_profile/) — one login works for both.
  If not logged in, run: python watchers/linkedin_watcher.py --setup

Usage (Agent Skill):
    python linkedin_poster.py --now               # post once immediately
    python linkedin_poster.py --schedule          # 24h loop (production)
    python linkedin_poster.py --preview           # see generated post, no posting
    python linkedin_poster.py --format value_tip  # force a post format
    python linkedin_poster.py --approve APPROVAL-2026-03-29-linkedin_post.md
"""

from __future__ import annotations

import argparse
import re
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

from skills.linkedin_post_skill import LinkedInPostSkill, POST_FORMATS  # noqa: E402
from skills.approval_skill       import ApprovalSkill                    # noqa: E402
from skills.dashboard_skill      import DashboardSkill                   # noqa: E402

# ---------------------------------------------------------------------------
# Playwright
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import (
        BrowserContext,
        Page,
        Playwright,
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
import logging

_LOG_DIR  = _VAULT_ROOT / "Logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_DIR / "linkedin_poster.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("LinkedInPoster")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROFILE_DIR      = _LOG_DIR / "linkedin_profile"
PENDING_DIR      = _VAULT_ROOT / "Pending_Approval"
APPROVED_DIR     = _VAULT_ROOT / "Approved"
DONE_DIR         = _VAULT_ROOT / "Done"
LOG_FILE         = _LOG_DIR / "linkedin_poster.log"
POST_LOG_FILE    = _LOG_DIR / "linkedin_post_history.jsonl"

LINKEDIN_URL     = "https://www.linkedin.com/feed/"
PAGE_TIMEOUT     = 60_000   # ms
POST_INTERVAL    = 86_400   # 24 hours in seconds

# ---------------------------------------------------------------------------
# Browser poster
# ---------------------------------------------------------------------------

class LinkedInBrowserPoster:
    """Posts content to LinkedIn feed via Playwright."""

    def __init__(self, headless: bool = False) -> None:
        self.headless    = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *_):
        self._stop()

    def _start(self) -> None:
        if not _PLAYWRIGHT_OK:
            raise RuntimeError(
                "Playwright not installed. Run: uv add playwright && playwright install chromium"
            )
        logger.info("Launching Chromium (headless=%s)…", self.headless)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def _stop(self) -> None:
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning("Error closing browser: %s", e)

    def _is_logged_in(self) -> bool:
        try:
            self._page.wait_for_selector(
                "nav.global-nav, [data-test-global-nav-link], .share-box-feed-entry__trigger",
                timeout=8_000,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    def post(self, content: str) -> dict:
        """
        Navigate to LinkedIn feed, open the post composer, type content, submit.
        Returns {"success": bool, "url": str|None, "error": str|None}
        """
        if not self._page:
            return _err("Browser not started.")

        # Navigate to feed
        try:
            logger.info("Navigating to LinkedIn feed…")
            self._page.goto(LINKEDIN_URL, timeout=PAGE_TIMEOUT)
        except PlaywrightTimeoutError:
            return _err("Timed out loading LinkedIn feed.")

        if not self._is_logged_in():
            return _err(
                "Not logged in. Run: python watchers/linkedin_watcher.py --setup"
            )

        # Open the post composer
        try:
            composer = self._open_composer()
            if not composer:
                return _err("Could not open LinkedIn post composer.")
        except Exception as e:
            return _err(f"Error opening composer: {e}")

        # Type the post content
        try:
            self._type_post(composer, content)
        except Exception as e:
            return _err(f"Error typing post content: {e}")

        # Click the Post button
        try:
            self._click_post_button()
        except Exception as e:
            return _err(f"Error clicking Post button: {e}")

        # Wait briefly and grab current URL as confirmation
        time.sleep(3)
        url = self._page.url
        logger.info("Post submitted. Current URL: %s", url)
        return {"success": True, "url": url, "error": None}

    def _open_composer(self) -> "Page | None":
        """Click the 'Start a post' button and return the focused textarea."""
        # Multiple selector variants for LinkedIn's ever-changing DOM
        trigger_selectors = [
            ".share-box-feed-entry__trigger",
            "[data-control-name='share.sharebox_entry_point']",
            "button.share-box-feed-entry__trigger",
            "div.share-creation-state__placeholder",
            "[placeholder='Start a post']",
            ".artdeco-button--muted",
        ]
        for sel in trigger_selectors:
            try:
                btn = self._page.query_selector(sel)
                if btn:
                    btn.click()
                    time.sleep(1.5)
                    logger.debug("Opened composer via: %s", sel)
                    break
            except Exception:
                continue

        # Wait for the editor textarea to appear
        editor_selectors = [
            "div.ql-editor[contenteditable='true']",
            "div[data-placeholder][contenteditable='true']",
            "div.editor-content[contenteditable='true']",
            ".share-editor div[contenteditable='true']",
        ]
        for sel in editor_selectors:
            try:
                editor = self._page.wait_for_selector(sel, timeout=8_000)
                if editor:
                    return editor
            except PlaywrightTimeoutError:
                continue

        return None

    def _type_post(self, editor, content: str) -> None:
        """Click the editor and type the post content."""
        editor.click()
        time.sleep(0.5)

        # Split into lines and type with Enter between them
        # (Playwright's type() doesn't handle \n well in LinkedIn's rich editor)
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line:
                editor.type(line, delay=10)
            if i < len(lines) - 1:
                editor.press("Enter")
            time.sleep(0.05)

        logger.debug("Typed %d chars into post editor.", len(content))
        time.sleep(1)

    def _click_post_button(self) -> None:
        """Find and click the final 'Post' submit button."""
        post_selectors = [
            "button.share-actions__primary-action",
            "button[data-control-name='share.post']",
            "button.artdeco-button--primary[type='button']:not([disabled])",
            "button.share-box-send__submit",
        ]
        for sel in post_selectors:
            try:
                btn = self._page.query_selector(sel)
                if btn and btn.is_enabled():
                    btn.click()
                    logger.debug("Clicked post button: %s", sel)
                    return
            except Exception:
                continue

        # Final fallback: look for any button with text "Post"
        try:
            self._page.get_by_role("button", name=re.compile(r"^Post$", re.IGNORECASE)).click()
            return
        except Exception:
            pass

        raise RuntimeError("Could not find the Post submit button.")


# ---------------------------------------------------------------------------
# Approval file writer
# ---------------------------------------------------------------------------

def _save_pending_approval(post_result: dict) -> Path:
    """Save a post to Pending_Approval/ for human review."""
    now   = datetime.now(timezone.utc)
    date  = now.strftime("%Y-%m-%d")
    ts    = now.strftime("%Y%m%d_%H%M%S")
    fname = f"APPROVAL-{date}-linkedin_post_{ts}.md"
    path  = PENDING_DIR / fname
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    content = f"""\
---
type: approval_request
action_type: linkedin_post
post_type: {post_result['post_type']}
created_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
risk_level: Medium
status: pending_approval
approval_reason: {post_result['approval_reason']}
expires_at: {date} + 48h
char_count: {post_result['char_count']}
---

# APPROVAL REQUEST — LinkedIn Post

> **APPROVAL REQUIRED: LinkedIn Post** | Awaiting sign-off before publishing.

**Reason:** {post_result['approval_reason']}

---

## Proposed Post Content

```
{post_result['content']}
```

## Post Details

| Field       | Value |
|-------------|-------|
| Format      | {post_result['post_type']} |
| Characters  | {post_result['char_count']} |
| Hashtags    | {', '.join(post_result['hashtags'])} |
| Hook        | {post_result['hook'][:80]} |

## Actions

To **approve and post**: Move this file to `Approved/` folder.
  The orchestrator will pick it up and post automatically.
To **reject**: Move to `Rejected/`.
To **edit**: Modify the content block above, then move to `Approved/`.

---
*Auto-generated by LinkedInPoster on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Post history logger
# ---------------------------------------------------------------------------

def _log_post_history(post_result: dict, status: str, url: str = "") -> None:
    """Append a JSONL record to Logs/linkedin_post_history.jsonl."""
    import json
    now    = datetime.now(timezone.utc)
    record = {
        "timestamp":   now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "post_type":   post_result["post_type"],
        "char_count":  post_result["char_count"],
        "status":      status,        # "posted" | "pending_approval" | "failed"
        "url":         url,
        "hook":        post_result["hook"][:100],
        "hashtags":    post_result["hashtags"],
    }
    POST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with POST_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Core post-or-approve logic
# ---------------------------------------------------------------------------

def run_post_cycle(
    headless: bool = False,
    force_format: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    1. Generate post content with Claude
    2. If approval needed → save to Pending_Approval/
    3. If clear → post via Playwright
    Returns {"status": "posted"|"pending_approval"|"failed", ...}
    """
    dashboard = DashboardSkill(_VAULT_ROOT)

    logger.info("=== LinkedIn Post Cycle ===")

    # Step 1: Generate post
    skill = LinkedInPostSkill(_VAULT_ROOT)
    post  = skill.generate(force_format=force_format)

    logger.info(
        "Generated: type=%s | chars=%d | approval=%s",
        post["post_type"], post["char_count"], post["approval_needed"],
    )

    # Step 2: Preview mode
    if dry_run:
        print("\n" + "="*60)
        print("PREVIEW — Post not published (--preview mode)")
        print("="*60)
        print(post["content"])
        print("="*60)
        print(f"Type: {post['post_type']} | Chars: {post['char_count']}")
        print(f"Approval needed: {post['approval_needed']}")
        if post["approval_reason"]:
            print(f"Reason: {post['approval_reason']}")
        return {"status": "preview", "post": post}

    # Step 3: Needs approval?
    if post["approval_needed"]:
        approval_path = _save_pending_approval(post)
        logger.info(
            "Post saved to Pending_Approval: %s\nReason: %s",
            approval_path.name, post["approval_reason"],
        )
        _log_post_history(post, "pending_approval")
        dashboard.update(
            f"LinkedIn post awaiting approval: {approval_path.name}",
            status="Pending_Approval",
            authorized_by="LinkedInPoster",
        )
        return {"status": "pending_approval", "file": str(approval_path), "post": post}

    # Step 4: Post directly
    if not _PLAYWRIGHT_OK:
        logger.error("Playwright not available — cannot post.")
        return {"status": "failed", "error": "Playwright not installed."}

    logger.info("Posting to LinkedIn (no approval required)…")
    with LinkedInBrowserPoster(headless=headless) as poster:
        result = poster.post(post["content"])

    if result["success"]:
        logger.info("Posted successfully! URL: %s", result["url"])
        _log_post_history(post, "posted", url=result.get("url", ""))
        dashboard.update(
            f"LinkedIn post published ({post['post_type']}, {post['char_count']} chars)",
            status="Done",
            authorized_by="LinkedInPoster",
        )
        return {"status": "posted", "url": result["url"], "post": post}
    else:
        logger.error("Post failed: %s", result["error"])
        _log_post_history(post, "failed")
        dashboard.update(
            f"LinkedIn post FAILED: {result['error'][:60]}",
            status="Failed",
            authorized_by="LinkedInPoster",
        )
        return {"status": "failed", "error": result["error"], "post": post}


def post_approved_file(approval_filename: str, headless: bool = False) -> dict:
    """
    Post a previously saved approval file from Pending_Approval/ or Approved/.
    Used when: human approves → moves file to Approved/ → orchestrator or manual call.
    """
    import json as _json

    # Search both dirs
    for d in [APPROVED_DIR, PENDING_DIR]:
        candidate = d / approval_filename
        if candidate.exists():
            approval_file = candidate
            break
    else:
        logger.error("File not found: %s", approval_filename)
        return {"status": "failed", "error": f"File not found: {approval_filename}"}

    text = approval_file.read_text(encoding="utf-8")

    # Extract post content from the approval file
    m = re.search(r'```\s*\n(.*?)\n```', text, re.DOTALL)
    if not m:
        return {"status": "failed", "error": "Could not extract post content from approval file."}

    content = m.group(1).strip()

    # Extract metadata
    post_type = "unknown"
    for line in text.splitlines():
        if line.startswith("post_type:"):
            post_type = line.split(":", 1)[1].strip()
            break

    post = {
        "content":   content,
        "post_type": post_type,
        "char_count": len(content),
        "hashtags":  re.findall(r'#\w+', content),
        "hook":      content.split("\n")[0],
        "cta":       "",
        "approval_needed": False,
        "approval_reason": "",
    }

    logger.info("Posting approved file: %s", approval_filename)

    if not _PLAYWRIGHT_OK:
        return {"status": "failed", "error": "Playwright not installed."}

    with LinkedInBrowserPoster(headless=headless) as poster:
        result = poster.post(content)

    if result["success"]:
        _log_post_history(post, "posted", url=result.get("url", ""))
        # Move to Done
        DONE_DIR.mkdir(parents=True, exist_ok=True)
        approval_file.rename(DONE_DIR / approval_file.name)
        logger.info("Posted and moved to Done: %s", approval_filename)
        return {"status": "posted", "url": result["url"]}
    else:
        logger.error("Post failed: %s", result["error"])
        return {"status": "failed", "error": result["error"]}


# ---------------------------------------------------------------------------
# 24-hour scheduler
# ---------------------------------------------------------------------------

def run_scheduler(headless: bool = False, force_format: str | None = None) -> None:
    """Run post cycles every 24 hours until stopped."""
    logger.info("LinkedIn Poster scheduler started (interval: 24h). Ctrl+C to stop.")

    while True:
        try:
            result = run_post_cycle(headless=headless, force_format=force_format)
            next_ts = datetime.now(timezone.utc)
            logger.info(
                "Cycle done (status=%s). Next post in 24 hours at ~%s UTC.",
                result["status"],
                next_ts.strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error("Scheduler cycle error: %s", e, exc_info=True)

        time.sleep(POST_INTERVAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"success": False, "url": None, "error": msg}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Silver-tier LinkedIn Auto-Poster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python linkedin_poster.py --now                  # post once immediately
  python linkedin_poster.py --preview              # see post, no browser
  python linkedin_poster.py --schedule             # 24h loop (production)
  python linkedin_poster.py --now --headless       # post without visible window
  python linkedin_poster.py --format value_tip     # force a specific format
  python linkedin_poster.py --approve APPROVAL-2026-03-29-linkedin_post_123.md

Post formats: value_tip | insight | case_study | question | behind_scenes | myth_bust
""",
    )
    p.add_argument("--now",      action="store_true", help="Post once immediately")
    p.add_argument("--schedule", action="store_true", help="Run on 24h loop (production)")
    p.add_argument("--preview",  action="store_true", help="Generate and print — no browser, no files")
    p.add_argument("--headless", action="store_true", help="Run Chromium headless")
    p.add_argument("--approve",  metavar="FILENAME",  help="Post a specific approved file by filename")
    p.add_argument(
        "--format",
        choices=POST_FORMATS,
        help="Force a specific post format (default: auto-rotate)",
    )
    return p


def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[LinkedInPoster] Shutdown signal received.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = _build_parser().parse_args()

    if args.approve:
        result = post_approved_file(args.approve, headless=args.headless)
        sys.exit(0 if result["status"] == "posted" else 1)

    elif args.preview:
        run_post_cycle(dry_run=True, force_format=args.format)

    elif args.schedule:
        run_scheduler(headless=args.headless, force_format=args.format)

    elif args.now:
        result = run_post_cycle(headless=args.headless, force_format=args.format)
        sys.exit(0 if result["status"] in ("posted", "pending_approval") else 1)

    else:
        _build_parser().print_help()
