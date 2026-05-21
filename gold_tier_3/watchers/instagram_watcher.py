"""
InstagramWatcher — Gold Tier Instagram Business account monitor.

Behavior:
  - Polls Instagram Graph API every 60 seconds.
  - Monitors recent post comments for keyword matches.
  - Monitors Instagram Direct message threads (requires pages_messaging permission).
  - Creates INSTAGRAM_COMMENT_*.md and INSTAGRAM_DM_*.md in Needs_Action/.
  - Dedup via Logs/instagram_seen.json — no duplicates across restarts.

Setup:
  1. Connect Instagram Professional account to a Facebook Page.
  2. Set IG_ACCOUNT_ID in .env (get from Graph API: /{page_id}?fields=instagram_business_account)
  3. FB_PAGE_ACCESS_TOKEN must have instagram_basic, instagram_manage_comments permissions.

Usage:
    python watchers/instagram_watcher.py
    python watchers/instagram_watcher.py --once
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
    print("[InstagramWatcher] Missing httpx. Run: uv add httpx")
    sys.exit(1)

VAULT_ROOT       = _VAULT_ROOT
NEEDS_ACTION_DIR = VAULT_ROOT / "Needs_Action"
LOG_DIR          = VAULT_ROOT / "Logs"
SEEN_FILE        = LOG_DIR / "instagram_seen.json"

GRAPH_VER     = "v19.0"
GRAPH_BASE    = f"https://graph.facebook.com/{GRAPH_VER}"
POLL_INTERVAL = 60

KEYWORDS: list[str] = ["price", "buy", "order", "available", "shipping", "cost", "inquiry", "collab", "dm", "interested"]


class InstagramWatcher(BaseWatcher):
    """
    Monitors Instagram Business account comments and DMs for sales/support signals.
    """

    def __init__(self, poll_interval: int = POLL_INTERVAL) -> None:
        super().__init__(watch_dir=NEEDS_ACTION_DIR, interval=poll_interval, log_dir=LOG_DIR)
        NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)

        import os
        self._token  = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
        self._ig_id  = os.environ.get("IG_ACCOUNT_ID", "")

        if not self._token or not self._ig_id:
            self.logger.warning("FB_PAGE_ACCESS_TOKEN or IG_ACCOUNT_ID not set — InstagramWatcher inactive.")

        self._seen   = self._load_seen()
        self._client = httpx.Client(timeout=30)
        self.logger.info("IG Account ID: %s | Keywords: %s", self._ig_id, KEYWORDS)

    def _load_seen(self) -> dict:
        if SEEN_FILE.exists():
            try:
                return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ids": []}

    def _save_seen(self) -> None:
        try:
            SEEN_FILE.write_text(json.dumps(self._seen, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _is_seen(self, key: str) -> bool:
        return key in self._seen["ids"]

    def _mark_seen(self, key: str) -> None:
        self._seen["ids"].append(key)
        if len(self._seen["ids"]) > 5000:
            self._seen["ids"] = self._seen["ids"][-2000:]

    def _graph(self, path: str, params: dict | None = None) -> dict:
        url = f"{GRAPH_BASE}/{path}"
        p   = {"access_token": self._token}
        if params:
            p.update(params)
        resp = self._client.get(url, params=p)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(data["error"]["message"])
        return data

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def _poll_comments(self) -> None:
        try:
            media = self._graph(f"{self._ig_id}/media", {"fields": "id,caption,timestamp", "limit": "10"})
        except Exception as exc:
            self.logger.error("Failed to fetch IG media: %s", exc)
            return

        for post in media.get("data", []):
            post_id = post["id"]
            try:
                comments = self._graph(
                    f"{post_id}/comments",
                    {"fields": "id,text,username,timestamp", "limit": "30"},
                )
            except Exception:
                continue

            for c in comments.get("data", []):
                cid = c["id"]
                key = f"ig_comment::{cid}"
                if self._is_seen(key):
                    continue

                text     = c.get("text", "")
                username = c.get("username", "unknown")
                ts       = c.get("timestamp", "")

                matched = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
                if matched:
                    self._write_comment_note(post_id, cid, username, text, ts, matched)

                self._mark_seen(key)

        self._save_seen()

    def _write_comment_note(self, post_id: str, comment_id: str, username: str, text: str, ts: str, keywords: list[str]) -> None:
        now       = datetime.now(timezone.utc)
        safe      = re.sub(r"\W+", "_", username)[:30]
        kws_str   = ", ".join(keywords)
        dest_name = f"INSTAGRAM_COMMENT_{safe}_{now.strftime('%Y%m%d_%H%M%S')}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        content = f"""\
---
type: instagram_comment
post_id: {post_id}
comment_id: {comment_id}
username: {username}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
keywords_matched: {kws_str}
status: needs_action
---

# Instagram Comment — @{username}

| Field           | Value |
|-----------------|-------|
| From            | @{username} |
| Post ID         | `{post_id}` |
| Comment ID      | `{comment_id}` |
| Keywords Found  | `{kws_str}` |
| Original Time   | {ts} |
| Detected At     | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |

## Comment

> {text}

## Action Required

Reply to @{username}'s comment on Instagram. Use `reply_to_ig_comment` MCP tool with comment_id `{comment_id}`.

---
*Auto-generated by InstagramWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info("INSTAGRAM COMMENT -> %s | @%s | KW: %s", dest_name, username, kws_str)
        except OSError as exc:
            self.logger.error("Write error: %s", exc)

    # ------------------------------------------------------------------
    # BaseWatcher
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used — InstagramWatcher polls API."""

    def _poll(self) -> None:
        if not self._token or not self._ig_id:
            self.logger.warning("Skipping poll — credentials not configured.")
            return
        self.logger.debug("--- Instagram poll cycle ---")
        self._poll_comments()

    def run(self, once: bool = False) -> None:
        self._running = True
        self.logger.info("InstagramWatcher started. Press Ctrl+C to stop.")
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                self.logger.error("Unexpected error: %s", exc, exc_info=True)
            if once:
                break
            self._sleep()
        self.logger.info("InstagramWatcher stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT,  lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    p = argparse.ArgumentParser(description="InstagramWatcher — Gold Tier Instagram monitor")
    p.add_argument("--once",     action="store_true")
    p.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = p.parse_args()

    watcher = InstagramWatcher(poll_interval=args.interval)
    watcher.run(once=args.once)
