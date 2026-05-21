"""
WhatsAppWatcher — Silver-tier WhatsApp Web monitor via Playwright.

Behavior:
  - Opens WhatsApp Web in a Chromium browser (persistent profile).
  - Scans all chats with unread messages every 30 seconds.
  - Filters messages containing keywords: urgent, invoice, payment, pricing, asap
  - Creates WHATSAPP_<chat>_<ts>.md in Needs_Action/ for each match.
  - Uses a persistent browser profile to avoid scanning QR code every run.
  - All activity logged to console + Logs/whatsapp_watcher.log

Setup:
  1. Run once: python watchers/whatsapp_watcher.py --setup
     - Browser opens, scan QR code with your phone.
     - Session is saved in Logs/whatsapp_profile/.
  2. Subsequent runs reuse saved session (no QR needed).

Usage (Agent Skill):
    python watchers/whatsapp_watcher.py           # continuous watch
    python watchers/whatsapp_watcher.py --once    # single scan, then exit
    python watchers/whatsapp_watcher.py --setup   # open browser for QR login
    python watchers/whatsapp_watcher.py --headless  # run without visible window
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
_HERE = Path(__file__).parent
_VAULT_ROOT = _HERE.parent

sys.path.insert(0, str(_HERE))
from base_watcher import BaseWatcher  # noqa: E402

# ---------------------------------------------------------------------------
# Playwright import
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
except ImportError as _err:
    print(
        f"[WhatsAppWatcher] Missing Playwright: {_err}\n"
        "Run: uv add playwright && playwright install chromium"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VAULT_ROOT        = _VAULT_ROOT
NEEDS_ACTION_DIR  = VAULT_ROOT / "Needs_Action"
LOG_DIR           = VAULT_ROOT / "Logs"
PROFILE_DIR       = LOG_DIR / "whatsapp_profile"
SEEN_FILE         = LOG_DIR / "whatsapp_seen.txt"

POLL_INTERVAL     = 30   # seconds
WHATSAPP_URL      = "https://web.whatsapp.com"
PAGE_LOAD_TIMEOUT = 60_000  # ms

KEYWORDS: list[str] = ["urgent", "invoice", "payment", "pricing", "asap"]


# ---------------------------------------------------------------------------
# WhatsAppWatcher
# ---------------------------------------------------------------------------

class WhatsAppWatcher(BaseWatcher):
    """
    Monitors WhatsApp Web for keyword-matching messages and routes
    matches to Needs_Action/ as WHATSAPP_*.md files.
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
    # Seen-message dedup
    # ------------------------------------------------------------------

    def _load_seen(self) -> set[str]:
        if SEEN_FILE.exists():
            try:
                ids = set(SEEN_FILE.read_text(encoding="utf-8").splitlines())
                self.logger.info("Loaded %d seen WhatsApp message keys.", len(ids))
                return ids
            except Exception as exc:
                self.logger.warning("Could not load seen file: %s", exc)
        return set()

    def _save_seen(self) -> None:
        try:
            SEEN_FILE.write_text("\n".join(self._seen), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Could not save seen file: %s", exc)

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def _start_browser(self) -> None:
        """Launch Chromium with a persistent context (saves session)."""
        self.logger.info("Launching Chromium (headless=%s)…", self.headless)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            args=["--no-sandbox"],
            viewport={"width": 1280, "height": 900},
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.logger.info("Browser started.")

    def _stop_browser(self) -> None:
        """Close browser and Playwright gracefully."""
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

    def _navigate_to_whatsapp(self) -> bool:
        """Navigate to WhatsApp Web and wait for chat list to load."""
        if not self._page:
            return False
        try:
            self.logger.info("Navigating to WhatsApp Web…")
            self._page.goto(WHATSAPP_URL, timeout=PAGE_LOAD_TIMEOUT)
            # Wait for either the chat list (logged in) or QR code (logged out)
            self._page.wait_for_selector(
                '[data-testid="chat-list"], canvas[aria-label="Scan me!"]',
                timeout=PAGE_LOAD_TIMEOUT,
            )
            # Detect QR code scenario
            if self._page.query_selector('canvas[aria-label="Scan me!"]'):
                self.logger.warning(
                    "WhatsApp QR code detected — please scan with your phone. "
                    "Waiting up to 120s for login…"
                )
                self._page.wait_for_selector(
                    '[data-testid="chat-list"]',
                    timeout=120_000,
                )
            self.logger.info("WhatsApp Web loaded and logged in.")
            return True
        except PlaywrightTimeoutError:
            self.logger.error(
                "Timed out waiting for WhatsApp Web. "
                "If not logged in, run: python watchers/whatsapp_watcher.py --setup"
            )
            return False
        except Exception as exc:
            self.logger.error("Failed to load WhatsApp Web: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Scanning logic
    # ------------------------------------------------------------------

    def _get_unread_chats(self) -> list[dict]:
        """Return list of chats that have unread messages."""
        if not self._page:
            return []

        unread_chats: list[dict] = []
        try:
            # WhatsApp Web: unread badge selector
            badges = self._page.query_selector_all('[data-testid="icon-unread-count"]')
            if not badges:
                self.logger.debug("No unread chats found.")
                return []

            self.logger.info("Found %d chat(s) with unread messages.", len(badges))
            for badge in badges:
                try:
                    # Navigate up to the chat row
                    chat_row = badge.evaluate_handle(
                        "el => el.closest('[data-testid=\"cell-frame-container\"]')"
                    )
                    if not chat_row:
                        continue
                    chat_title_el = chat_row.query_selector('[data-testid="cell-frame-title"]')
                    chat_title = chat_title_el.inner_text() if chat_title_el else "Unknown"
                    unread_chats.append({
                        "name": chat_title.strip(),
                        "element": chat_row,
                    })
                except Exception as exc:
                    self.logger.debug("Could not parse chat row: %s", exc)
        except Exception as exc:
            self.logger.error("Error scanning chat list: %s", exc)

        return unread_chats

    def _open_chat_and_get_messages(self, chat: dict) -> list[str]:
        """Click into a chat and collect recent message texts."""
        messages: list[str] = []
        if not self._page:
            return messages

        try:
            chat["element"].click()
            time.sleep(1.5)  # let messages render

            msg_elements = self._page.query_selector_all(
                '[data-testid="msg-container"] [data-testid="conversation-compose-box-input"],'
                '[data-testid="msg-container"] .copyable-text'
            )
            for el in msg_elements[-20:]:  # last 20 messages
                try:
                    text = el.inner_text().strip()
                    if text:
                        messages.append(text)
                except Exception:
                    pass

            if not messages:
                # Fallback: grab all text in conversation panel
                panel = self._page.query_selector('[data-testid="conversation-panel-messages"]')
                if panel:
                    raw = panel.inner_text()
                    messages = [line.strip() for line in raw.splitlines() if line.strip()]

        except Exception as exc:
            self.logger.error("Error opening chat '%s': %s", chat["name"], exc)

        return messages

    def _matches_keywords(self, text: str) -> list[str]:
        """Return list of matched keywords found in text (case-insensitive)."""
        text_lower = text.lower()
        return [kw for kw in KEYWORDS if re.search(r'\b' + re.escape(kw) + r'\b', text_lower)]

    def _build_message_key(self, chat_name: str, matched_text: str) -> str:
        """Build a dedup key from chat name + truncated text."""
        safe = re.sub(r'\W+', '_', chat_name.lower())
        snippet = matched_text[:60].replace('\n', ' ')
        return f"{safe}::{snippet}"

    # ------------------------------------------------------------------
    # process_file — ABC requirement (not used for WhatsApp)
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used by WhatsAppWatcher (scans browser, not filesystem)."""

    # ------------------------------------------------------------------
    # Writing Needs_Action note
    # ------------------------------------------------------------------

    def _write_note(self, chat_name: str, matched_msgs: list[tuple[str, list[str]]]) -> None:
        """Create WHATSAPP_<chat>_<ts>.md in Needs_Action/."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'\W+', '_', chat_name)[:40]
        dest_name = f"WHATSAPP_{safe_name}_{ts}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        all_keywords = sorted({kw for _, kws in matched_msgs for kw in kws})
        messages_section = ""
        for msg_text, kws in matched_msgs:
            safe_msg = msg_text.replace('`', "'")[:500]
            messages_section += f"### Keywords: `{', '.join(kws)}`\n\n> {safe_msg}\n\n"

        content = f"""\
---
type: whatsapp
chat: {chat_name}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
keywords_matched: {', '.join(all_keywords)}
message_count: {len(matched_msgs)}
status: needs_action
---

# WhatsApp — {chat_name}

| Field           | Value |
|-----------------|-------|
| Chat            | {chat_name} |
| Detected At     | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| Keywords Found  | `{', '.join(all_keywords)}` |
| Matched Messages| {len(matched_msgs)} |
| Status          | needs_action |

## Matched Messages

{messages_section}

## Action Required

Review the WhatsApp conversation with **{chat_name}** and respond appropriately.

---
*Auto-generated by WhatsAppWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info(
                "WHATSAPP -> %s | Chat: %s | Keywords: %s",
                dest_name, chat_name, all_keywords,
            )
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", dest_name, exc)

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Single poll: scan unread chats for keyword matches."""
        self.logger.debug("--- WhatsApp poll cycle ---")

        unread_chats = self._get_unread_chats()
        if not unread_chats:
            return

        for chat in unread_chats:
            chat_name = chat["name"]
            messages = self._open_chat_and_get_messages(chat)

            matched: list[tuple[str, list[str]]] = []
            for msg_text in messages:
                kws = self._matches_keywords(msg_text)
                if not kws:
                    continue
                key = self._build_message_key(chat_name, msg_text)
                if key in self._seen:
                    self.logger.debug("Already seen, skipping: %s", key[:60])
                    continue
                matched.append((msg_text, kws))
                self._seen.add(key)

            if matched:
                self._write_note(chat_name, matched)
                self._save_seen()
            else:
                self.logger.debug(
                    "Chat '%s': %d message(s), no keyword matches.", chat_name, len(messages)
                )

    # ------------------------------------------------------------------
    # Setup mode (QR login helper)
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Open browser for QR scan, wait for login, then close."""
        self.logger.info("SETUP MODE — Please scan the QR code in the browser.")
        self._start_browser()
        ok = self._navigate_to_whatsapp()
        if ok:
            self.logger.info("Login successful! Session saved to %s", PROFILE_DIR)
            self.logger.info("Press Ctrl+C to exit setup mode.")
            try:
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                pass
        self._stop_browser()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, once: bool = False) -> None:
        """Start the WhatsApp polling loop."""
        self._running = True
        self._start_browser()

        ok = self._navigate_to_whatsapp()
        if not ok:
            self.logger.error("Could not load WhatsApp Web. Exiting.")
            self._stop_browser()
            return

        self.logger.info("WhatsAppWatcher started. Press Ctrl+C to stop.")

        try:
            while self._running:
                try:
                    self._poll()
                except Exception as exc:
                    self.logger.error("Unexpected error in poll cycle: %s", exc, exc_info=True)

                if once:
                    break
                self._sleep()
        finally:
            self._stop_browser()

        self.logger.info("WhatsAppWatcher stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="WhatsAppWatcher — Silver-tier WhatsApp Web keyword monitor"
    )
    p.add_argument("--once",     action="store_true", help="Single scan then exit")
    p.add_argument("--setup",    action="store_true", help="Open browser for QR login")
    p.add_argument("--headless", action="store_true", help="Run browser headless (no window)")
    p.add_argument(
        "--interval", type=int, default=POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL})"
    )
    return p


def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[WhatsAppWatcher] Signal received, shutting down...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = _build_parser().parse_args()
    watcher = WhatsAppWatcher(poll_interval=args.interval, headless=args.headless)

    if args.setup:
        watcher.setup()
    else:
        watcher.run(once=args.once)
