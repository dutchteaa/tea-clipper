"""Audio device discovery, selection resolution, and launch-fragment assembly.

Real audio devices are their own ``pipewiresrc`` nodes (NOT the ScreenCast portal).
Pure helpers (``resolve_audio_devices``, ``build_audio_fragment``) are unit-tested;
``discover_audio_devices`` talks to live hardware and is probe-verified.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Protocol

from tea_clipper.gst_init import ensure_gst  # registers gi version first

from gi.repository import Gst

log = logging.getLogger("tea_clipper")

DESKTOP_TOKEN = "@desktop@"
MIC_TOKEN = "@mic@"


@dataclass
class AudioDevice:
    node_name: str          # stable PipeWire node.name; the identifier stored in config
    display_name: str       # human-readable label for the probe / future UI
    is_monitor: bool        # True = sink monitor (desktop audio); False = input (mic)
    is_default: bool        # True = system default for its kind


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


class _SettingsLike(Protocol):
    audio_devices: list[str]


def resolve_audio_devices(settings: _SettingsLike, available: list[AudioDevice]) -> list[str]:
    """Expand settings.audio_devices into concrete node names, skipping unavailable ones."""
    known_names = {d.node_name for d in available}
    default_monitor = next(
        (d.node_name for d in available if d.is_monitor and d.is_default), None
    )
    default_mic = next(
        (d.node_name for d in available if not d.is_monitor and d.is_default), None
    )

    resolved: list[str] = []
    for entry in settings.audio_devices:
        if entry == DESKTOP_TOKEN:
            name = default_monitor
            if name is None:
                log.warning("no default desktop-audio (monitor) device available; skipping")
                continue
        elif entry == MIC_TOKEN:
            name = default_mic
            if name is None:
                log.warning("no default microphone device available; skipping")
                continue
        elif entry in known_names:
            name = entry
        else:
            log.warning("configured audio device %r not available; skipping", entry)
            continue
        if name not in resolved:
            resolved.append(name)
    return resolved


def _default_node_names() -> tuple[str | None, str | None]:
    """(default_sink_monitor_node, default_source_node) via pactl; (None, None) on failure."""

    def query(kind: str) -> str | None:
        try:
            result = subprocess.run(
                ["pactl", "get-default-" + kind],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        name = result.stdout.strip()
        return name or None

    sink = query("sink")
    source = query("source")
    monitor = f"{sink}.monitor" if sink else None
    return monitor, source


def discover_audio_devices() -> list[AudioDevice]:
    """Enumerate capturable audio nodes via GStreamer's PipeWire device provider."""
    ensure_gst()
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Audio/Source", None)
    monitor.start()
    try:
        gst_devices = monitor.get_devices()
    finally:
        monitor.stop()

    default_monitor, default_source = _default_node_names()

    devices: list[AudioDevice] = []
    for dev in gst_devices:
        props = dev.get_properties()
        node_name = props.get_string("node.name") if props is not None else None
        if not node_name:
            continue
        media_class = (props.get_string("media.class") or "") if props is not None else ""
        is_monitor = node_name.endswith(".monitor") or "Monitor" in media_class
        is_default = node_name in (default_monitor, default_source)
        devices.append(
            AudioDevice(
                node_name=node_name,
                display_name=dev.get_display_name(),
                is_monitor=is_monitor,
                is_default=is_default,
            )
        )
    return devices
