"""Audio device discovery, selection resolution, and launch-fragment assembly.

Real audio devices are their own ``pipewiresrc`` nodes (NOT the ScreenCast portal).
Pure helpers (``resolve_audio_devices``, ``build_audio_fragment``, ``_parse_pactl_sources``)
are unit-tested; ``discover_audio_devices`` shells out to ``pactl`` and is probe-verified.

We enumerate via ``pactl`` rather than ``Gst.DeviceMonitor`` because the latter does not
surface sink *monitor* sources (desktop audio) on PipeWire — only hardware inputs — which
would make desktop-audio capture impossible. ``pactl list sources`` lists both, and the
node names it reports are exactly what ``pipewiresrc target-object=`` accepts.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Protocol

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


def _run_pactl(args: list[str]) -> str | None:
    """Run ``pactl <args>`` and return stdout; ``None`` if pactl is missing/fails."""
    try:
        result = subprocess.run(
            ["pactl", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _parse_pactl_sources(
    list_output: str, default_sink: str | None, default_source: str | None
) -> list[AudioDevice]:
    """Parse ``pactl list sources`` into AudioDevices. Pure; unit-tested.

    Each source block contains a ``Name:`` (the node name, what ``pipewiresrc
    target-object=`` wants) followed by a ``Description:`` (human-readable). A sink's
    monitor is named ``<sink>.monitor``, so the default sink's monitor is the default
    desktop-audio device.
    """
    default_monitor = f"{default_sink}.monitor" if default_sink else None
    devices: list[AudioDevice] = []
    name: str | None = None
    for raw in list_output.splitlines():
        line = raw.strip()
        if line.startswith("Name:"):
            name = line[len("Name:"):].strip()
        elif line.startswith("Description:") and name is not None:
            description = line[len("Description:"):].strip()
            devices.append(
                AudioDevice(
                    node_name=name,
                    display_name=description or name,
                    is_monitor=name.endswith(".monitor"),
                    is_default=name in (default_monitor, default_source),
                )
            )
            name = None
    return devices


def discover_audio_devices() -> list[AudioDevice]:
    """Enumerate capturable audio nodes (mics + sink monitors) via ``pactl``."""
    list_output = _run_pactl(["list", "sources"])
    if not list_output:
        return []
    default_sink = (_run_pactl(["get-default-sink"]) or "").strip() or None
    default_source = (_run_pactl(["get-default-source"]) or "").strip() or None
    return _parse_pactl_sources(list_output, default_sink, default_source)
