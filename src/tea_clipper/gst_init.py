"""One-time GStreamer initialization with a version guard."""

from __future__ import annotations

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

_initialized = False

MIN_VERSION = (1, 22, 0)


def ensure_gst() -> None:
    """Initialize GStreamer once. Idempotent. Raises if the version is too old."""
    global _initialized
    if _initialized:
        return
    Gst.init(None)
    major, minor, micro, _ = Gst.version()
    if (major, minor, micro) < MIN_VERSION:
        raise RuntimeError(
            f"GStreamer {MIN_VERSION} required, found {major}.{minor}.{micro}"
        )
    _initialized = True
