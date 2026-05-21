"""
LinkedInWatcher — Silver-tier LinkedIn notifications & messages monitor.

Behavior:
  - Opens LinkedIn in Chromium with a persistent profile (session reuse).
  - Checks two sources every 60 seconds:
      1. Messaging inbox — unread threads
      2. Notifications panel — unread alerts
  - Keywords: sales, inquiry, proposal, pricing
  - On keyword match: creates LINKEDIN_<type>_<slug>_<ts>.md in Needs_Action/.
  - Seen-key dedup via Logs/linkedin_seen.txt — no duplicates across restarts.
  - All activity logged to console + Logs/linkedin_watcher.log

Setup:
  1. python watchers/linkedin_watcher.py --setup
     - Browser opens LinkedIn login page.
     - Log in manually (email + password, handle 2FA if needed).
     - Session saved to Logs/linkedin_profile/.
  2. All subsequent runs reuse the saved session — no login needed.

Usage (Agent Skill):
    python watchers/linkedin_watcher.py            # continuous watch
    python watchers/linkedin_watcher.py --once     # single scan, then exit
    python watchers/linkedin_watcher.py --setup    # open browser for manual login
    python watchers/linkedin_watcher.py --headless # run without visible window
    python watchers/linkedin_watcher.py --interval 120  # custom poll interval
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
# Path bootstrap — works from project root or watchers/ directly
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_VAULT_ROOT = _HERE.parent

sys.path.insert(0, str(_HERE))
from base_watcher import BaseWatcher  # noqa: E402

# ---------------------------------------------------------------------------
# Playwright import
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import (
        BrowserContext,
        Page,
        Playwright,
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
except ImportError as _err:
    print(
        f"[LinkedInWatcher] Missing Playwright: {_err}\n"
        "Run: uv add playwright && playwright install chromium"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VAULT_ROOT        = _VAULT_ROOT
NEEDS_ACTION_DIR  = VAULT_ROOT / "Needs_Action"
LOG_DIR           = VAULT_ROOT / "Logs"
PROFILE_DIR       = LOG_DIR / "linkedin_profile"
SEEN_FILE         = LOG_DIR / "linkedin_seen.txt"

POLL_INTERVAL     = 60   # seconds
PAGE_LOAD_TIMEOUT = 60_000  # ms
NAV_TIMEOUT       = 30_000  # ms

LINKEDIN_URL      = "https://www.linkedin.com"
MESSAGING_URL     = "https://www.linkedin.com/messaging/"
NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"

KEYWORDS: list[str] = ["sales", "inquiry", "proposal", "pricing"]


# ---------------------------------------------------------------------------
# LinkedInWatcher
# ---------------------------------------------------------------------------

class LinkedInWatcher(BaseWatcher):
    """
    Monitors LinkedIn messages and notifications for keyword-matching content
    and routes matches to Needs_Action/ as LINKEDIN_*.md files.
    """

    def __init__(
        self,
        poll_interval: int = POLL_INTERVAL,
        headless: bool = False,
    ) -> None:
        super().__init__(
            watch_dir=NEEDS_ACTION_DIR,
            interval=poll_interval,
            log_dir=LOG_DIR,
        )
        self.headless = headless
        NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        self._seen: set[str] = self._load_seen()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        self.logger.info("Vault root   : %s", VAULT_ROOT)
        self.logger.info("Destination  : %s", NEEDS_ACTION_DIR)
        self.logger.info("Profile dir  : %s", PROFILE_DIR)
        self.logger.info("Keywords     : %s", KEYWORDS)
        self.logger.info("Poll interval: %ds", poll_interval)
        self.logger.info("Headless     : %s", headless)

    # ------------------------------------------------------------------
    # Seen-key dedup
    # ------------------------------------------------------------------

    def _load_seen(self) -> set[str]:
        if SEEN_FILE.exists():
            try:
                ids = set(SEEN_FILE.read_text(encoding="utf-8").splitlines())
                self.logger.info("Loaded %d seen LinkedIn keys.", len(ids))
                return ids
            except Exception as exc:
                self.logger.warning("Could not load seen file: %s", exc)
        return set()

    def _save_seen(self) -> None:
        try:
            SEEN_FILE.write_text("\n".join(sorted(self._seen)), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Could not save seen file: %s", exc)

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def _start_browser(self) -> None:
        """Launch Chromium with persistent context (session reuse)."""
        self.logger.info("Launching Chromium (headless=%s)…", self.headless)
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
        self.logger.info("Browser started.")

    def _stop_browser(self) -> None:
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            self.logger.warning("Error stopping browser: %s", exc)
        finally:
            self._context = None
            self._page = None
            self._playwright = None
        self.logger.info("Browser stopped.")

    def _is_logged_in(self) -> bool:
        """Check if the current page shows a logged-in LinkedIn session."""
        if not self._page:
            return False
        try:
            self._page.wait_for_selector(
                "nav.global-nav, [data-test-global-nav-link]",
                timeout=8_000,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    def _navigate_to_linkedin(self) -> bool:
        """Go to LinkedIn home and verify we are logged in."""
        if not self._page:
            return False
        try:
            self.logger.info("Navigating to LinkedIn…")
            self._page.goto(LINKEDIN_URL, timeout=PAGE_LOAD_TIMEOUT)

            if self._is_logged_in():
                self.logger.info("LinkedIn session active — logged in.")
                return True

            self.logger.warning(
                "Not logged in. Run: python watchers/linkedin_watcher.py --setup"
            )
            return False
        except PlaywrightTimeoutError:
            self.logger.error("Timed out loading LinkedIn.")
            return False
        except Exception as exc:
            self.logger.error("Failed to load LinkedIn: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Keyword matching
    # ------------------------------------------------------------------

    def _matches_keywords(self, text: str) -> list[str]:
        """Return matched keywords found in text (case-insensitive, word boundary)."""
        text_lower = text.lower()
        return [kw for kw in KEYWORDS if re.search(r'\b' + re.escape(kw) + r'\b', text_lower)]

    def _make_key(self, source: str, identifier: str, snippet: str) -> str:
        """Build a dedup key."""
        clean = re.sub(r'\W+', '_', identifier.lower())
        snip  = snippet[:50].replace('\n', ' ').strip()
        return f"{source}::{clean}::{snip}"

    # ------------------------------------------------------------------
    # Messaging scan
    # ------------------------------------------------------------------

    def _scan_messages(self) -> list[dict]:
        """Open /messaging/ and collect unread threads with keyword matches."""
        results: list[dict] = []
        if not self._page:
            return results

        try:
            self.logger.debug("Navigating to Messaging…")
            self._page.goto(MESSAGING_URL, timeout=PAGE_LOAD_TIMEOUT)
            self._page.wait_for_selector(
                ".msg-conversations-container, .scaffold-layout__list",
                timeout=NAV_TIMEOUT,
            )
        except PlaywrightTimeoutError:
            self.logger.warning("Messaging inbox did not load in time.")
            return results
        except Exception as exc:
            self.logger.error("Error loading messaging: %s", exc)
            return results

        try:
            thread_els = self._page.query_selector_all(
                ".msg-conversation-listitem, "
                "[data-control-name='view_conversation']"
            )
            self.logger.debug("Found %d conversation items.", len(thread_els))

            for thread_el in thread_els[:20]:
                try:
                    is_unread = bool(
                        thread_el.query_selector(
                            ".msg-conversation-listitem__unread-count, "
                            ".notification-badge"
                        )
                    )
                    if not is_unread:
                        continue

                    name_el = thread_el.query_selector(
                        ".msg-conversation-listitem__participant-names, "
                        ".msg-conversation-card__participant-names"
                    )
                    sender = name_el.inner_text().strip() if name_el else "Unknown"

                    preview_el = thread_el.query_selector(
                        ".msg-conversation-card__message-snippet, "
                        ".msg-conversation-listitem__snippet"
                    )
                    preview = preview_el.inner_text().strip() if preview_el else ""

                    kws = self._matches_keywords(preview) or self._matches_keywords(sender)
                    if not kws:
                        continue

                    thread_el.click()
                    time.sleep(1.5)
                    full_text = self._extract_open_thread_text()

                    all_text = f"{sender} {preview} {full_text}"
                    kws = self._matches_keywords(all_text)
                    if not kws:
                        continue

                    results.append({
                        "source":   "message",
                        "sender":   sender,
                        "preview":  preview,
                        "body":     full_text[:2000],
                        "keywords": kws,
                    })

                except Exception as exc:
                    self.logger.debug("Error parsing thread: %s", exc)

        except Exception as exc:
            self.logger.error("Error scanning message threads: %s", exc)

        return results

    def _extract_open_thread_text(self) -> str:
        """Extract visible message text from the currently open chat thread."""
        if not self._page:
            return ""
        try:
            msgs = self._page.query_selector_all(
                ".msg-s-message-list__event .msg-s-event-listitem__body, "
                ".msg-s-message-group__meta ~ .msg-s-event-list"
            )
            return "\n".join(
                el.inner_text().strip() for el in msgs[-10:] if el.inner_text().strip()
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Notifications scan
    # ------------------------------------------------------------------

    def _scan_notifications(self) -> list[dict]:
        """Open /notifications/ and collect keyword-matching alerts."""
        results: list[dict] = []
        if not self._page:
            return results

        try:
            self.logger.debug("Navigating to Notifications…")
            self._page.goto(NOTIFICATIONS_URL, timeout=PAGE_LOAD_TIMEOUT)
            self._page.wait_for_selector(
                ".notification-list, .nt-card-list, [data-test-notification-list]",
                timeout=NAV_TIMEOUT,
            )
        except PlaywrightTimeoutError:
            self.logger.warning("Notifications page did not load in time.")
            return results
        except Exception as exc:
            self.logger.error("Error loading notifications: %s", exc)
            return results

        try:
            notif_els = self._page.query_selector_all(
                ".nt-card-list .nt-card, "
                ".notification-list li, "
                "[data-test-notification-list] > li"
            )
            self.logger.debug("Found %d notification items.", len(notif_els))

            for notif_el in notif_els[:30]:
                try:
                    text = notif_el.inner_text().strip()
                    if not text:
                        continue

                    kws = self._matches_keywords(text)
                    if not kws:
                        continue

                    results.append({
                        "source":   "notification",
                        "sender":   "",
                        "preview":  text[:300],
                        "body":     text[:1500],
                        "keywords": kws,
                    })

                except Exception as exc:
                    self.logger.debug("Error parsing notification: %s", exc)

        except Exception as exc:
            self.logger.error("Error scanning notifications: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Write Needs_Action note
    # ------------------------------------------------------------------

    def _write_note(self, item: dict) -> None:
        """Create LINKEDIN_<type>_<slug>_<ts>.md in Needs_Action/."""
        now      = datetime.now(timezone.utc)
        ts       = now.strftime("%Y%m%d_%H%M%S")
        src      = item["source"].upper()
        slug     = re.sub(r'\W+', '_', item["sender"] or item["preview"][:30])[:30]
        dest_name = f"LINKEDIN_{src}_{slug}_{ts}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        kws_str = ", ".join(item["keywords"])
        preview_safe = item["preview"].replace('`', "'")
        body_safe    = item["body"].replace('`', "'")

        content = f"""\
---
type: linkedin_{item['source']}
source: {item['source']}
sender: {item['sender'] or 'N/A'}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
keywords_matched: {kws_str}
status: needs_action
---

# LinkedIn {src} — {item['sender'] or 'Notification'}

| Field          | Value |
|----------------|-------|
| Source         | {item['source'].title()} |
| From           | {item['sender'] or 'N/A'} |
| Keywords Found | `{kws_str}` |
| Detected At    | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| Status         | needs_action |

## Preview

> {preview_safe}

## Full Content

```
{body_safe}
```

## Action Required

Review this LinkedIn {item['source']} and respond: Reply / Connect / Archive / Escalate.

---
*Auto-generated by LinkedInWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info(
                "LINKEDIN -> %s | From: %s | Keywords: %s",
                dest_name,
                (item["sender"] or "notification")[:40],
                kws_str,
            )
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", dest_name, exc)

    # ------------------------------------------------------------------
    # process_file — ABC requirement (not used for LinkedIn)
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used by LinkedInWatcher (polls browser, not filesystem)."""

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Single poll: scan messages + notifications for keyword matches."""
        self.logger.debug("--- LinkedIn poll cycle ---")
        new_items: list[dict] = []

        for item in self._scan_messages():
            key = self._make_key("msg", item["sender"], item["preview"])
            if key in self._seen:
                self.logger.debug("Already seen (msg): %s", key[:60])
                continue
            new_items.append(item)
            self._seen.add(key)

        for item in self._scan_notifications():
            key = self._make_key("notif", "", item["preview"])
            if key in self._seen:
                self.logger.debug("Already seen (notif): %s", key[:60])
                continue
            new_items.append(item)
            self._seen.add(key)

        if not new_items:
            self.logger.debug("No new keyword matches this cycle.")
            return

        self.logger.info("Found %d new keyword match(es).", len(new_items))
        for item in new_items:
            self._write_note(item)
        self._save_seen()

    # ------------------------------------------------------------------
    # Setup mode (manual login helper)
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Open browser for manual LinkedIn login, save session, then wait."""
        self.logger.info("SETUP MODE — Please log in to LinkedIn in the browser.")
        self._start_browser()
        try:
            self._page.goto(
                "https://www.linkedin.com/login",
                timeout=PAGE_LOAD_TIMEOUT,
            )
            self.logger.info(
                "Browser open. Log in manually (handle 2FA if prompted).\n"
                "Session will be saved to: %s\n"
                "Press Ctrl+C when done.",
                PROFILE_DIR,
            )
            while True:
                time.sleep(5)
                if self._is_logged_in():
                    self.logger.info("Login detected! Session saved.")
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            self.logger.error("Setup error: %s", exc)
        finally:
            self._stop_browser()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, once: bool = False) -> None:
        """Start the LinkedIn polling loop."""
        self._running = True
        self._start_browser()

        if not self._navigate_to_linkedin():
            self.logger.error(
                "LinkedIn session not found. Run --setup first to log in."
            )
            self._stop_browser()
            return

        self.logger.info("LinkedInWatcher started. Press Ctrl+C to stop.")

        try:
            while self._running:
                try:
                    self._poll()
                except Exception as exc:
                    self.logger.error(
                        "Unexpected error in poll cycle: %s", exc, exc_info=True
                    )

                if once:
                    break
                self._sleep()
        finally:
            self._stop_browser()

        self.logger.info("LinkedInWatcher stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LinkedInWatcher — Silver-tier LinkedIn messages & notifications monitor"
    )
    p.add_argument("--once",     action="store_true", help="Single scan then exit")
    p.add_argument("--setup",    action="store_true", help="Open browser for manual login")
    p.add_argument("--headless", action="store_true", help="Run browser headless (no window)")
    p.add_argument(
        "--interval", type=int, default=POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL})",
    )
    return p


def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[LinkedInWatcher] Signal received, shutting down…")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = _build_parser().parse_args()
    watcher = LinkedInWatcher(poll_interval=args.interval, headless=args.headless)

    if args.setup:
        watcher.setup()
    else:
        watcher.run(once=args.once)
