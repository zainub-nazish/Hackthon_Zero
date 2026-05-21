"""
GmailWatcher — Silver-tier Gmail inbox monitor.

Behavior:
  - Authenticates via OAuth2 using credentials.json (Google Cloud project).
  - Polls Gmail API every 60 seconds for UNREAD messages in INBOX.
  - For each unread email: creates EMAIL_<id>.md in Needs_Action/.
  - Marks processed emails with a local seen-set (token file) to avoid duplicates.
  - All activity logged to console + Logs/gmail_watcher.log

Setup:
  1. Place credentials.json (OAuth2 Desktop app) in project root.
  2. First run will open browser for Google auth consent.
  3. token.json will be saved for subsequent runs.

Usage (Agent Skill):
    python watchers/gmail_watcher.py
    python watchers/gmail_watcher.py --once        # single poll, then exit
    python watchers/gmail_watcher.py --max-results 20
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from base64 import urlsafe_b64decode
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — works when run from project root or from watchers/
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_VAULT_ROOT = _HERE.parent

sys.path.insert(0, str(_HERE))
from base_watcher import BaseWatcher  # noqa: E402

# ---------------------------------------------------------------------------
# Google API imports (installed via pyproject.toml)
# ---------------------------------------------------------------------------
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as _err:
    print(
        f"[GmailWatcher] Missing Google API libraries: {_err}\n"
        "Run: uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

VAULT_ROOT       = _VAULT_ROOT
NEEDS_ACTION_DIR = VAULT_ROOT / "Needs_Action"
LOG_DIR          = VAULT_ROOT / "Logs"
CREDENTIALS_FILE = VAULT_ROOT / "credentials.json"
TOKEN_FILE       = VAULT_ROOT / "token.json"
SEEN_IDS_FILE    = VAULT_ROOT / "Logs" / "gmail_seen_ids.json"
POLL_INTERVAL    = 60  # seconds
MAX_RESULTS      = 10  # emails per poll cycle


# ---------------------------------------------------------------------------
# GmailWatcher
# ---------------------------------------------------------------------------

class GmailWatcher(BaseWatcher):
    """
    Polls Gmail INBOX for unread emails and routes them to Needs_Action/.

    Each new email creates:
        Needs_Action/EMAIL_<message-id-short>.md
    """

    def __init__(self, poll_interval: int = POLL_INTERVAL, max_results: int = MAX_RESULTS) -> None:
        super().__init__(
            watch_dir=NEEDS_ACTION_DIR,
            interval=poll_interval,
            log_dir=LOG_DIR,
        )
        self.max_results = max_results
        NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self._seen_ids: set[str] = self._load_seen_ids()
        self._service = self._authenticate()

        self.logger.info("Vault root   : %s", VAULT_ROOT)
        self.logger.info("Destination  : %s", NEEDS_ACTION_DIR)
        self.logger.info("Poll interval: %ds", poll_interval)
        self.logger.info("Max results  : %d per cycle", max_results)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate(self):
        """Load or refresh OAuth2 credentials, opening browser on first run."""
        creds: Credentials | None = None

        if TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
                self.logger.info("Loaded existing token: %s", TOKEN_FILE)
            except Exception as exc:
                self.logger.warning("Failed to load token, re-authenticating: %s", exc)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self.logger.info("Token refreshed successfully.")
                except Exception as exc:
                    self.logger.warning("Token refresh failed, re-authenticating: %s", exc)
                    creds = None

            if not creds:
                if not CREDENTIALS_FILE.exists():
                    self.logger.error(
                        "credentials.json not found at %s. "
                        "Download from Google Cloud Console (OAuth2 Desktop app).",
                        CREDENTIALS_FILE,
                    )
                    sys.exit(1)

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), SCOPES
                )
                creds = flow.run_local_server(port=0)
                self.logger.info("New OAuth2 consent completed.")

            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            self.logger.info("Token saved: %s", TOKEN_FILE)

        try:
            service = build("gmail", "v1", credentials=creds)
            self.logger.info("Gmail API service ready.")
            return service
        except HttpError as exc:
            self.logger.error("Failed to build Gmail service: %s", exc)
            sys.exit(1)

    # ------------------------------------------------------------------
    # Seen-IDs persistence (prevents duplicates across restarts)
    # ------------------------------------------------------------------

    def _load_seen_ids(self) -> set[str]:
        if SEEN_IDS_FILE.exists():
            try:
                data = json.loads(SEEN_IDS_FILE.read_text(encoding="utf-8"))
                ids = set(data.get("seen_ids", []))
                self.logger.info("Loaded %d seen email IDs.", len(ids))
                return ids
            except Exception as exc:
                self.logger.warning("Could not load seen IDs: %s", exc)
        return set()

    def _save_seen_ids(self) -> None:
        try:
            SEEN_IDS_FILE.write_text(
                json.dumps({"seen_ids": list(self._seen_ids)}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.logger.warning("Could not save seen IDs: %s", exc)

    # ------------------------------------------------------------------
    # Gmail helpers
    # ------------------------------------------------------------------

    def _fetch_unread_message_ids(self) -> list[str]:
        """Return list of unread INBOX message IDs (up to max_results)."""
        try:
            response = (
                self._service.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=["INBOX", "UNREAD"],
                    maxResults=self.max_results,
                )
                .execute()
            )
            messages = response.get("messages", [])
            return [m["id"] for m in messages]
        except HttpError as exc:
            self.logger.error("Gmail API error fetching messages: %s", exc)
            return []

    def _get_message_details(self, msg_id: str) -> dict:
        """Fetch full message payload and extract key fields."""
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except HttpError as exc:
            self.logger.error("Failed to fetch message %s: %s", msg_id, exc)
            return {}

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = self._extract_body(msg.get("payload", {}))
        snippet = msg.get("snippet", "")

        return {
            "id":       msg_id,
            "thread":   msg.get("threadId", ""),
            "subject":  headers.get("subject", "(no subject)"),
            "sender":   headers.get("from", "(unknown)"),
            "to":       headers.get("to", ""),
            "date":     headers.get("date", ""),
            "labels":   ", ".join(msg.get("labelIds", [])),
            "snippet":  snippet,
            "body":     body[:3000] if body else snippet,  # cap at 3000 chars
        }

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain-text body from MIME payload."""
        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime == "text/plain" and body_data:
            try:
                return urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            except Exception:
                return ""

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text

        return ""

    # ------------------------------------------------------------------
    # process_file — not used for Gmail; required by BaseWatcher ABC
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used by GmailWatcher (polls API, not filesystem)."""

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_message(self, msg_id: str) -> None:
        """Fetch email details and write EMAIL_*.md to Needs_Action/."""
        details = self._get_message_details(msg_id)
        if not details:
            return

        short_id = msg_id[:12]
        dest_name = f"EMAIL_{short_id}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        if dest_path.exists():
            self.logger.debug("Already written, skipping: %s", dest_name)
            return

        now = datetime.now(timezone.utc)
        # Sanitize subject for safe display
        safe_subject = re.sub(r"[^\w\s\-.,!?@()]", "", details["subject"])[:100]

        content = f"""\
---
type: email
message_id: {msg_id}
thread_id: {details['thread']}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
email_date: {details['date']}
status: needs_action
labels: {details['labels']}
---

# EMAIL — {safe_subject}

| Field    | Value |
|----------|-------|
| From     | {details['sender']} |
| To       | {details['to']} |
| Subject  | {details['subject']} |
| Date     | {details['date']} |
| Gmail ID | `{msg_id}` |
| Status   | needs_action |

## Snippet

> {details['snippet']}

## Body

```
{details['body']}
```

## Action Required

Review this email and decide: Reply / Archive / Delegate / Escalate.

---
*Auto-generated by GmailWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""

        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info(
                "EMAIL -> %s | From: %s | Subject: %s",
                dest_name,
                details["sender"][:50],
                details["subject"][:60],
            )
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", dest_name, exc)

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Single poll: fetch unread IDs, process new ones."""
        self.logger.debug("--- Gmail poll cycle ---")
        ids = self._fetch_unread_message_ids()

        if not ids:
            self.logger.debug("No unread messages found.")
            return

        new_ids = [i for i in ids if i not in self._seen_ids]
        if not new_ids:
            self.logger.debug("All %d unread message(s) already processed.", len(ids))
            return

        self.logger.info("Found %d new unread message(s).", len(new_ids))
        for msg_id in new_ids:
            self._process_message(msg_id)
            self._seen_ids.add(msg_id)

        self._save_seen_ids()

    def run(self, once: bool = False) -> None:
        """Start the polling loop. Pass once=True for a single-shot run."""
        self._running = True
        self.logger.info("GmailWatcher started. Press Ctrl+C to stop.")

        while self._running:
            try:
                self._poll()
            except Exception as exc:
                self.logger.error("Unexpected error in poll cycle: %s", exc, exc_info=True)

            if once:
                break
            self._sleep()

        self.logger.info("GmailWatcher stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GmailWatcher — Silver-tier Gmail inbox monitor")
    p.add_argument("--once", action="store_true", help="Run a single poll then exit")
    p.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds (default: 60)")
    p.add_argument("--max-results", type=int, default=MAX_RESULTS, help="Max emails per poll (default: 10)")
    return p


def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[GmailWatcher] Signal received, shutting down...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = _build_parser().parse_args()
    watcher = GmailWatcher(poll_interval=args.interval, max_results=args.max_results)
    watcher.run(once=args.once)
