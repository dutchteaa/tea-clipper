"""Cross-entrypoint single-instance lock (no Qt dependency).

A flock-based lock file in the runtime dir gives mutual exclusion across both the GUI
(`python -m tea_clipper.ui`) and the headless daemon (`python -m tea_clipper`). The OS
releases the lock automatically on process exit/crash, so there is no stale-PID cleanup.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK_NAME = "tea-clipper.lock"


def lock_path() -> Path:
    """Return the lock file path: $XDG_RUNTIME_DIR, else the system temp dir."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(tempfile.gettempdir())
    return base / _LOCK_NAME


class InstanceLock:
    """An exclusive, non-blocking flock held for the process lifetime."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else lock_path()
        self._fd: int | None = None

    def acquire(self) -> bool:
        """True if we hold the lock (or the lock is unusable); False on contention."""
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            logger.warning("single-instance lock unusable (%s); proceeding without it", exc)
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock and close the fd. Idempotent."""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(self._fd)
        self._fd = None
