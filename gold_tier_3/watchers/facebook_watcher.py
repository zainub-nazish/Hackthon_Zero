"""
FacebookWatcher — Gold Tier Facebook Page messages & comments monitor.

Behavior:
  - Polls Facebook Graph API every 60 seconds.
  - Checks Page inbox (conversations) for unread messages.
  - Checks recent Page posts for new comments with keywords.
  - Creates FACEBOOK_MSG_*.md and FACEBOOK_COMMENT_*.md in Needs_Action/.
  - Dedup via Logs/facebook_seen.json — no duplicates across restarts.
  - All activity logged to console + Logs/facebook_watcher.log

Setup:
  1. Create a Facebook App at developers.facebook.com
  2. Add Facebook Login + Pages API permissions
  3. Get a long-lived Page Access Token (valid 60 days)
  4. Set FB_PAGE_ACCESS_TOKEN and FB_PAGE_ID in .env

Usage:
    python watchers/facebook_watcher.py
    python watchers/facebook_watcher.py --once
    python watchers/facebook_watcher.py --interval 120
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE       = Path(__file__).parent
_VAULT_ROOT = _HERE.parent

sys.path.insert(0, str(_HERE))
from base_watcher import BaseWatcher  # noqa: E402

try:
    import httpx
except ImportError:
    print("[FacebookWatcher] Missing httpx. Run: uv add httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
VAULT_ROOT       = _VAULT_ROOT
NEEDS_ACTION_DIR = VAULT_ROOT / "Needs_Action"
LOG_DIR          = VAULT_ROOT / "Logs"
SEEN_FILE        = LOG_DIR / "facebook_seen.json"

GRAPH_VER   = "v19.0"
GRAPH_BASE  = f"https://graph.facebook.com/{GRAPH_VER}"
POLL_INTERVAL = 60

KEYWORDS: list[str] = ["order", "price", "invoice", "payment", "inquiry", "help", "support", "buy", "quote"]


# ---------------------------------------------------------------------------
# FacebookWatcher
# ---------------------------------------------------------------------------

class FacebookWatcher(BaseWatcher):
    """
    Monitors Facebook Page inbox and post comments for business-relevant messages.
    """

    def __init__(self, poll_interval: int = POLL_INTERVAL) -> None:
        super().__init__(watch_dir=NEEDS_ACTION_DIR, interval=poll_interval, log_dir=LOG_DIR)
        NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)

        import os
        self._token   = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
        self._page_id = os.environ.get("FB_PAGE_ID", "")

        if not self._token or not self._page_id:
            self.logger.warning(
                "FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID not set. "
                "FacebookWatcher will not connect. Set them in .env"
            )

        self._seen: dict = self._load_seen()
        self._client = httpx.Client(timeout=30)

        self.logger.info("Vault root   : %s", VAULT_ROOT)
        self.logger.info("Destination  : %s", NEEDS_ACTION_DIR)
        self.logger.info("Keywords     : %s", KEYWORDS)
        self.logger.info("Poll interval: %ds", poll_interval)

    # ------------------------------------------------------------------
    # Seen-ID dedup
    # ------------------------------------------------------------------

    def _load_seen(self) -> dict:
        if SEEN_FILE.exists():
            try:
                data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
                self.logger.info("Loaded %d seen Facebook IDs.", len(data.get("ids", [])))
                return data
            except Exception as exc:
                self.logger.warning("Could not load seen file: %s", exc)
        return {"ids": []}

    def _save_seen(self) -> None:
        try:
            SEEN_FILE.write_text(json.dumps(self._seen, indent=2), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Could not save seen file: %s", exc)

    def _is_seen(self, key: str) -> bool:
        return key in self._seen["ids"]

    def _mark_seen(self, key: str) -> None:
        self._seen["ids"].append(key)
        if len(self._seen["ids"]) > 5000:
            self._seen["ids"] = self._seen["ids"][-2000:]

    # ------------------------------------------------------------------
    # Graph API
    # ------------------------------------------------------------------

    def _graph(self, path: str, params: dict | None = None) -> dict:
        url = f"{GRAPH_BASE}/{path}"
        p = {"access_token": self._token}
        if params:
            p.update(params)
        resp = self._client.get(url, params=p)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Graph API error: {data['error']['message']}")
        return data

    # ------------------------------------------------------------------
    # Inbox messages
    # ------------------------------------------------------------------

    def _poll_messages(self) -> None:
        try:
            data = self._graph(
                f"{self._page_id}/conversations",
                {"fields": "participants,messages{message,created_time,from}", "limit": "20"},
            )
        except Exception as exc:
            self.logger.error("Failed to fetch conversations: %s", exc)
            return

        for conv in data.get("data", []):
            conv_id = conv["id"]
            messages = conv.get("messages", {}).get("data", [])
            if not messages:
                continue

            latest = messages[0]
            msg_id = latest.get("id", "")
            key    = f"msg::{msg_id}"

            if self._is_seen(key):
                continue

            sender  = latest.get("from", {}).get("name", "Unknown")
            text    = latest.get("message", "")
            created = latest.get("created_time", "")

            self._write_message_note(conv_id, msg_id, sender, text, created)
            self._mark_seen(key)

        self._save_seen()

    def _write_message_note(self, conv_id: str, msg_id: str, sender: str, text: str, created: str) -> None:
        now       = datetime.now(timezone.utc)
        ts        = now.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"\W+", "_", sender)[:30]
        dest_name = f"FACEBOOK_MSG_{safe_name}_{ts}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        content = f"""\
---
type: facebook_message
conversation_id: {conv_id}
message_id: {msg_id}
sender: {sender}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
original_time: {created}
status: needs_action
---

# Facebook Message — {sender}

| Field           | Value |
|-----------------|-------|
| From            | {sender} |
| Conversation ID | `{conv_id}` |
| Received At     | {created} |
| Detected At     | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| Status          | needs_action |

## Message

> {text}

## Action Required

Review and reply to this Facebook message. Use `reply_to_message` MCP tool with conversation_id `{conv_id}`.

---
*Auto-generated by FacebookWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info("FACEBOOK MSG -> %s | From: %s", dest_name, sender[:40])
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", dest_name, exc)

    # ------------------------------------------------------------------
    # Post comments
    # ------------------------------------------------------------------

    def _poll_comments(self) -> None:
        try:
            posts = self._graph(
                f"{self._page_id}/posts",
                {"fields": "id,message,created_time", "limit": "5"},
            )
        except Exception as exc:
            self.logger.error("Failed to fetch posts: %s", exc)
            return

        for post in posts.get("data", []):
            post_id = post["id"]
            try:
                comments = self._graph(
                    f"{post_id}/comments",
                    {"fields": "id,message,from,created_time", "limit": "20"},
                )
            except Exception as exc:
                self.logger.debug("Comments error for post %s: %s", post_id, exc)
                continue

            for comment in comments.get("data", []):
                comment_id = comment["id"]
                key        = f"comment::{comment_id}"
                if self._is_seen(key):
                    continue

                text    = comment.get("message", "")
                sender  = comment.get("from", {}).get("name", "Unknown")
                created = comment.get("created_time", "")

                matched = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
                if not matched:
                    self._mark_seen(key)
                    continue

                self._write_comment_note(post_id, comment_id, sender, text, created, matched)
                self._mark_seen(key)

        self._save_seen()

    def _write_comment_note(self, post_id: str, comment_id: str, sender: str, text: str, created: str, keywords: list[str]) -> None:
        now       = datetime.now(timezone.utc)
        ts        = now.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"\W+", "_", sender)[:30]
        kws_str   = ", ".join(keywords)
        dest_name = f"FACEBOOK_COMMENT_{safe_name}_{ts}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        content = f"""\
---
type: facebook_comment
post_id: {post_id}
comment_id: {comment_id}
sender: {sender}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
keywords_matched: {kws_str}
status: needs_action
---

# Facebook Comment — {sender}

| Field           | Value |
|-----------------|-------|
| From            | {sender} |
| Post ID         | `{post_id}` |
| Comment ID      | `{comment_id}` |
| Keywords Found  | `{kws_str}` |
| Detected At     | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| Status          | needs_action |

## Comment

> {text}

## Action Required

Respond to this comment. Use `reply_to_ig_comment` or Facebook MCP `reply_to_message` tool.

---
*Auto-generated by FacebookWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info("FACEBOOK COMMENT -> %s | From: %s | KW: %s", dest_name, sender[:30], kws_str)
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", dest_name, exc)

    # ------------------------------------------------------------------
    # BaseWatcher interface
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used — FacebookWatcher polls API, not filesystem."""

    def _poll(self) -> None:
        if not self._token or not self._page_id:
            self.logger.warning("Skipping poll — credentials not configured.")
            return
        self.logger.debug("--- Facebook poll cycle ---")
        self._poll_messages()
        self._poll_comments()

    def run(self, once: bool = False) -> None:
        self._running = True
        self.logger.info("FacebookWatcher started. Press Ctrl+C to stop.")
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                self.logger.error("Unexpected error: %s", exc, exc_info=True)
            if once:
                break
            self._sleep()
        self.logger.info("FacebookWatcher stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _handle_signal(signum, frame):  # noqa: ANN001
    print("\n[FacebookWatcher] Shutting down…")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    p = argparse.ArgumentParser(description="FacebookWatcher — Gold Tier Facebook monitor")
    p.add_argument("--once",     action="store_true")
    p.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = p.parse_args()

    watcher = FacebookWatcher(poll_interval=args.interval)
    watcher.run(once=args.once)
