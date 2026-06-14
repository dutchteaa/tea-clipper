"""Shared test fixtures and helpers."""

from __future__ import annotations

import os

# Qt unit tests run without a display; must be set before any QApplication import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

try:
    from tea_clipper.gst_init import ensure_gst

    ensure_gst()
    HAVE_GST = True
except Exception:
    HAVE_GST = False

requires_engine = pytest.mark.skipif(
    not (HAVE_FFMPEG and HAVE_GST),
    reason="needs gstreamer + ffmpeg",
)


def ffprobe_duration(path: Path) -> float:
    """Return container duration in seconds via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def ffprobe_codecs(path: Path) -> set[str]:
    """Return the set of codec_type values (e.g. {'video', 'audio'}) in the file."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return {s["codec_type"] for s in json.loads(out.stdout)["streams"]}


def make_segment(path: Path, seconds: float = 2.0) -> Path:
    """Write a tiny real MKV (h264 + opus) test segment with ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "libopus",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="session")
def qapp():
    """A single offscreen QApplication for all widget/QObject tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
