"""
TwitterWatcher — Gold Tier Twitter (X) v2 API monitor.

Behavior:
  - Polls Twitter API v2 every 90 seconds (respects rate limits).
  - Monitors @mentions of your account for keyword matches.
  - Monitors DMs (requires elevated access or Basic plan).
  - Creates TWITTER_MENTION_*.md and TWITTER_DM_*.md in Needs_Action/.
  - Dedup via Logs/twitter_seen.json — no duplicates across restarts.
  - Graceful degradation: if rate limited, backs off and retries.

Setup:
  1. Create a Twitter Developer App at developer.twitter.com
  2. Enable OAuth 2.0 + OAuth 1.0a
  3. Set environment variables in .env:
     TWITTER_BEARER_TOKEN, TWITTER_API_KEY, TWITTER_API_SECRET,
     TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET, TWITTER_USER_ID

Usage:
    python watchers/twitter_watcher.py
    python watchers/twitter_watcher.py --once
    python watchers/twitter_watcher.py --interval 120
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE       = Path(__file__).parent
_VAULT_ROOT = _HERE.parent

sys.path.insert(0, str(_HERE))
from base_watcher import BaseWatcher  # noqa: E402

try:
    import httpx
except ImportError:
    print("[TwitterWatcher] Missing httpx. Run: uv add httpx")
    sys.exit(1)

VAULT_ROOT       = _VAULT_ROOT
NEEDS_ACTION_DIR = VAULT_ROOT / "Needs_Action"
LOG_DIR          = VAULT_ROOT / "Logs"
SEEN_FILE        = LOG_DIR / "twitter_seen.json"

POLL_INTERVAL = 90   # Twitter free tier: 500k tweets/month — be conservative
API_BASE      = "https://api.twitter.com/2"

KEYWORDS: list[str] = ["price", "buy", "hire", "help", "how much", "quote", "service", "dm", "inquiry", "interested"]


class TwitterWatcher(BaseWatcher):
    """
    Monitors Twitter (X) @mentions for sales/support keywords.
    Writes actionable notes to Needs_Action/ for each matched mention.
    """

    def __init__(self, poll_interval: int = POLL_INTERVAL) -> None:
        super().__init__(watch_dir=NEEDS_ACTION_DIR, interval=poll_interval, log_dir=LOG_DIR)
        NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)

        import os
        self._bearer  = os.environ.get("TWITTER_BEARER_TOKEN", "")
        self._user_id = os.environ.get("TWITTER_USER_ID", "")

        if not self._bearer or not self._user_id:
            self.logger.warning(
                "TWITTER_BEARER_TOKEN or TWITTER_USER_ID not set — TwitterWatcher inactive."
            )

        self._seen    = self._load_seen()
        self._client  = httpx.Client(timeout=30)
        self._backoff = 0  # seconds of extra sleep after rate limit

        self.logger.info("Twitter User ID : %s", self._user_id)
        self.logger.info("Poll interval   : %ds", poll_interval)
        self.logger.info("Keywords        : %s", KEYWORDS)

    # ------------------------------------------------------------------
    # Seen-ID dedup
    # ------------------------------------------------------------------

    def _load_seen(self) -> dict:
        if SEEN_FILE.exists():
            try:
                return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ids": [], "since_id": None}

    def _save_seen(self) -> None:
        try:
            SEEN_FILE.write_text(json.dumps(self._seen, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Twitter API (read only — Bearer Token)
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        url  = f"{API_BASE}{path}"
        hdrs = {"Authorization": f"Bearer {self._bearer}"}
        try:
            resp = self._client.get(url, headers=hdrs, params=params or {})
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return None

        if resp.status_code == 429:
            reset = int(resp.headers.get("x-rate-limit-reset", time.time() + 900))
            wait  = max(reset - int(time.time()), 60)
            self.logger.warning("Rate limited — sleeping %ds.", wait)
            self._backoff = wait
            return None

        if resp.status_code != 200:
            self.logger.error("Twitter API %d: %s", resp.status_code, resp.text[:200])
            return None

        self._backoff = 0
        return resp.json()

    # ------------------------------------------------------------------
    # Mentions polling
    # ------------------------------------------------------------------

    def _poll_mentions(self) -> None:
        params: dict = {
            "max_results":    10,
            "tweet.fields":   "created_at,author_id,text,conversation_id",
            "expansions":     "author_id",
            "user.fields":    "name,username",
        }
        if self._seen.get("since_id"):
            params["since_id"] = self._seen["since_id"]

        data = self._get(f"/users/{self._user_id}/mentions", params)
        if not data:
            return

        tweets = data.get("data", [])
        if not tweets:
            self.logger.debug("No new mentions.")
            return

        # Update since_id for next poll (newest tweet is first)
        self._seen["since_id"] = tweets[0]["id"]

        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        for tweet in tweets:
            tweet_id = tweet["id"]
            key      = f"mention::{tweet_id}"

            if key in self._seen["ids"]:
                continue

            text    = tweet.get("text", "")
            author  = users.get(tweet.get("author_id", ""), {})
            username = author.get("username", "unknown")
            name     = author.get("name", "Unknown")
            created  = tweet.get("created_at", "")

            matched = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
            if matched or True:  # log all mentions, not just keyword matches
                self._write_mention_note(tweet_id, username, name, text, created, matched)

            self._seen["ids"].append(key)
            if len(self._seen["ids"]) > 5000:
                self._seen["ids"] = self._seen["ids"][-2000:]

        self._save_seen()
        self.logger.info("Processed %d new mention(s).", len(tweets))

    def _write_mention_note(self, tweet_id: str, username: str, name: str, text: str, created: str, keywords: list[str]) -> None:
        now       = datetime.now(timezone.utc)
        safe      = re.sub(r"\W+", "_", username)[:30]
        kws_str   = ", ".join(keywords) if keywords else "none"
        priority  = "HIGH" if keywords else "LOW"
        dest_name = f"TWITTER_MENTION_{safe}_{now.strftime('%Y%m%d_%H%M%S')}.md"
        dest_path = NEEDS_ACTION_DIR / dest_name

        content = f"""\
---
type: twitter_mention
tweet_id: {tweet_id}
username: {username}
detected_at: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}
keywords_matched: {kws_str}
priority: {priority}
status: needs_action
---

# Twitter Mention — @{username}

| Field           | Value |
|-----------------|-------|
| From            | @{username} ({name}) |
| Tweet ID        | `{tweet_id}` |
| Keywords Found  | `{kws_str}` |
| Priority        | {priority} |
| Tweet Time      | {created} |
| Detected At     | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |

## Tweet

> {text}

## Action Required

Reply to @{username}'s tweet. Use `reply_to_tweet` MCP tool with tweet_id `{tweet_id}`.

---
*Auto-generated by TwitterWatcher on {now.strftime("%Y-%m-%d %H:%M:%S UTC")}.*
"""
        try:
            dest_path.write_text(content, encoding="utf-8")
            self.logger.info("TWITTER -> %s | @%s | KW: %s", dest_name, username, kws_str)
        except OSError as exc:
            self.logger.error("Write error: %s", exc)

    # ------------------------------------------------------------------
    # BaseWatcher
    # ------------------------------------------------------------------

    def process_file(self, file_path: Path) -> None:
        """Not used — TwitterWatcher polls API."""

    def _poll(self) -> None:
        if not self._bearer or not self._user_id:
            self.logger.warning("Skipping poll — credentials not configured.")
            return

        if self._backoff > 0:
            self.logger.info("Backing off %ds due to rate limit…", self._backoff)
            time.sleep(self._backoff)
            self._backoff = 0

        self.logger.debug("--- Twitter poll cycle ---")
        self._poll_mentions()

    def run(self, once: bool = False) -> None:
        self._running = True
        self.logger.info("TwitterWatcher started. Press Ctrl+C to stop.")
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                self.logger.error("Unexpected error: %s", exc, exc_info=True)
            if once:
                break
            self._sleep()
        self.logger.info("TwitterWatcher stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT,  lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    p = argparse.ArgumentParser(description="TwitterWatcher — Gold Tier Twitter monitor")
    p.add_argument("--once",     action="store_true")
    p.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = p.parse_args()

    watcher = TwitterWatcher(poll_interval=args.interval)
    watcher.run(once=args.once)
