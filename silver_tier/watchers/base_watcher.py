"""
Base Watcher — Abstract base class for all Bronze-tier watchers.
All concrete watchers must inherit from BaseWatcher and implement
process_file() and run().
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path


def setup_logging(name: str, log_dir: Path | None = None) -> logging.Logger:
    """Configure a named logger with console + optional file handler."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (optional)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


class BaseWatcher(ABC):
    """
    Abstract base class for vault watchers.

    Subclasses must implement:
        - process_file(file_path): handle a single discovered file
        - run(): main entry point (start watching loop)
    """

    def __init__(
        self,
        watch_dir: Path,
        interval: int = 10,
        log_dir: Path | None = None,
    ) -> None:
        """
        Args:
            watch_dir: Directory to watch (must exist or will be created).
            interval:  Polling interval in seconds (default 10).
            log_dir:   Optional directory for log files.
        """
        self.watch_dir = Path(watch_dir)
        self.interval = interval
        self.logger = setup_logging(self.__class__.__name__, log_dir)
        self._running = False

        if not self.watch_dir.exists():
            self.watch_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Created watch directory: %s", self.watch_dir)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def process_file(self, file_path: Path) -> None:
        """Process a single file discovered in the watched directory."""

    @abstractmethod
    def run(self) -> None:
        """Start the watch loop. Should respect self._running flag."""

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the watcher to stop after the current cycle."""
        self.logger.info("Stop signal received.")
        self._running = False

    def _sleep(self) -> None:
        """Sleep for one interval, checking stop signal."""
        self.logger.debug("Sleeping %ds before next poll.", self.interval)
        time.sleep(self.interval)
