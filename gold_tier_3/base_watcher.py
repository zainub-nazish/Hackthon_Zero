"""
Base Watcher — Abstract base class for all Silver-tier watchers.

All concrete watchers must inherit from BaseWatcher and implement
process_file() and run().

This file lives at project root as a convenience entry-point copy.
The canonical version used by the watchers/ package is watchers/base_watcher.py
"""

# Re-export everything from the watchers package version so this module
# can be used identically to the package-level one.
from watchers.base_watcher import BaseWatcher, setup_logging  # noqa: F401

__all__ = ["BaseWatcher", "setup_logging"]
