"""Audio device discovery, selection resolution, and launch-fragment assembly.

Real audio devices are their own ``pipewiresrc`` nodes (NOT the ScreenCast portal).
Pure helpers (``resolve_audio_devices``, ``build_audio_fragment``) are unit-tested;
``discover_audio_devices`` talks to live hardware and is probe-verified.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from tea_clipper.gst_init import ensure_gst  # registers gi version first

from gi.repository import Gst

log = logging.getLogger("tea_clipper")

DESKTOP_TOKEN = "@desktop@"
MIC_TOKEN = "@mic@"


def build_audio_fragment(device_names: list[str]) -> str | None:
    """Capture each node and mix them via ``audiomixer``; ``None`` if no devices.

    The returned fragment ends in ``queue name=aenc_in`` so the pipeline can append
    ``! opusenc ! replaymux.audio_0`` exactly as it does for the test source.
    """
    if not device_names:
        return None
    chains = [
        f"pipewiresrc target-object={name} ! audioconvert ! audioresample ! queue ! amix."
        for name in device_names
    ]
    chains.append(
        "audiomixer name=amix ! audioconvert ! audioresample ! queue name=aenc_in"
    )
    return " ".join(chains)
