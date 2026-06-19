"""Audio device discovery, selection resolution, and launch-fragment assembly.

Real audio devices are their own ``pipewiresrc`` nodes (NOT the ScreenCast portal).
Pure helpers (``resolve_audio_devices``, ``build_audio_fragment``, ``_parse_pactl_devices``)
are unit-tested; ``discover_audio_devices`` shells out to ``pactl`` and is probe-verified.

Desktop audio vs. mic — the PipeWire reality (learned during hardware verification):

* There is **no** ``.monitor`` *node* in PipeWire — the ``<sink>.monitor`` names ``pactl``
  reports are a PulseAudio-compatibility fiction. ``pipewiresrc target-object=<...monitor>``
  matches no real node and silently captures silence.
* To capture **desktop audio** you target the **sink** node itself and set the stream
  property ``stream.capture.sink=true`` (this taps the sink's monitor ports).
* To capture a **mic** you target a real **source** node normally.

So we enumerate sinks (desktop) and real (non-monitor) sources (mics) via ``pactl``; their
``Name`` is exactly the node name ``pipewiresrc target-object=`` accepts. (``Gst.DeviceMonitor``
is not used: on the target hardware it doesn't surface sink monitors at all.)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("tea_clipper")

DESKTOP_TOKEN = "@desktop@"
MIC_TOKEN = "@mic@"

# webrtcdsp's noise-suppression-level enum, weakest -> strongest.
NOISE_SUPPRESSION_LEVELS = ("low", "moderate", "high", "very-high")


@dataclass
class AudioDevice:
    node_name: str          # stable PipeWire node.name; the identifier stored in config
    display_name: str       # human-readable label for the probe / future UI
    is_monitor: bool        # True = a sink we capture as desktop audio; False = input (mic)
    is_default: bool        # True = system default for its kind


def _device_fragment(
    device: AudioDevice, noise_suppression_level: str | None = None
) -> str:
    """One ``pipewiresrc`` capture chain feeding the shared ``audiomixer``.

    Desktop (sink) devices need ``stream.capture.sink=true`` so pipewiresrc taps the sink's
    monitor ports rather than treating it as a (silent) regular source. Mic (source) chains
    get WebRTC noise suppression (``webrtcdsp``) when ``noise_suppression_level`` is set —
    an adaptive denoiser, not a hard gate, so above-threshold speech is preserved without the
    per-sample chatter a ``audiodynamic`` expander produced. ``webrtcdsp`` only accepts S16LE
    at 8/16/32/48 kHz, so the rate/format is pinned just upstream of it; AEC/AGC/VAD are off
    (there is no echo probe — noise suppression only).
    """
    props = ""
    if device.is_monitor:
        props = ' stream-properties="props,stream.capture.sink=true"'
    ns = ""
    if not device.is_monitor and noise_suppression_level is not None:
        ns = (
            "audioresample ! audio/x-raw,format=S16LE,rate=48000 ! "
            "webrtcdsp echo-cancel=false voice-detection=false gain-control=false "
            f"noise-suppression=true noise-suppression-level={noise_suppression_level} ! "
            "audioconvert ! "
        )
    return (
        f"pipewiresrc target-object={device.node_name}{props} ! "
        f"audioconvert ! {ns}audioresample ! queue ! amix."
    )


def build_audio_fragment(
    devices: list[AudioDevice], noise_suppression_level: str | None = None
) -> str | None:
    """Capture each device and mix them via ``audiomixer``; ``None`` if no devices.

    ``noise_suppression_level`` (a ``NOISE_SUPPRESSION_LEVELS`` value, or ``None`` = off)
    applies WebRTC noise suppression to mic chains only. The returned fragment ends in
    ``queue name=aenc_in`` so the pipeline can append ``! opusenc ! replaymux.audio_0``
    exactly as it does for the test source. The mixer output is pinned to stereo so a mono
    mic doesn't collapse desktop audio to mono.
    """
    if not devices:
        return None
    chains = [_device_fragment(d, noise_suppression_level) for d in devices]
    chains.append(
        "audiomixer name=amix ! audioconvert ! audioresample ! "
        "audio/x-raw,channels=2 ! queue name=aenc_in"
    )
    return " ".join(chains)


class _SettingsLike(Protocol):
    audio_devices: list[str]
    mic_noise_suppression_enabled: bool
    mic_noise_suppression_level: str


def resolve_noise_suppression(settings: _SettingsLike) -> str | None:
    """The mic noise-suppression level from settings, or ``None`` when off/invalid."""
    if not settings.mic_noise_suppression_enabled:
        return None
    if settings.mic_noise_suppression_level not in NOISE_SUPPRESSION_LEVELS:
        log.warning(
            "unknown noise-suppression level %r; disabling suppression",
            settings.mic_noise_suppression_level,
        )
        return None
    return settings.mic_noise_suppression_level


def resolve_audio_devices(
    settings: _SettingsLike, available: list[AudioDevice]
) -> list[AudioDevice]:
    """Expand settings.audio_devices into concrete devices, skipping unavailable ones.

    Returns ``AudioDevice`` objects (not just names) so the fragment builder knows whether
    each is a sink (desktop) or a source (mic). Order preserved; duplicates removed.
    """
    by_name = {d.node_name: d for d in available}
    default_monitor = next(
        (d for d in available if d.is_monitor and d.is_default), None
    )
    default_mic = next(
        (d for d in available if not d.is_monitor and d.is_default), None
    )

    resolved: list[AudioDevice] = []
    seen: set[str] = set()
    for entry in settings.audio_devices:
        if entry == DESKTOP_TOKEN:
            device = default_monitor
            if device is None:
                log.warning("no default desktop-audio (sink) device available; skipping")
                continue
        elif entry == MIC_TOKEN:
            device = default_mic
            if device is None:
                log.warning("no default microphone device available; skipping")
                continue
        elif entry in by_name:
            device = by_name[entry]
        else:
            log.warning("configured audio device %r not available; skipping", entry)
            continue
        if device.node_name not in seen:
            seen.add(device.node_name)
            resolved.append(device)
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


def _parse_pactl_blocks(list_output: str) -> list[tuple[str, str]]:
    """Extract ``(node_name, display_name)`` pairs from ``pactl list sinks|sources`` text.

    Each block has a ``Name:`` (the node name) followed by a ``Description:`` (human label);
    other interleaved fields are ignored.
    """
    pairs: list[tuple[str, str]] = []
    name: str | None = None
    for raw in list_output.splitlines():
        line = raw.strip()
        if line.startswith("Name:"):
            name = line[len("Name:"):].strip()
        elif line.startswith("Description:") and name is not None:
            description = line[len("Description:"):].strip()
            pairs.append((name, description or name))
            name = None
    return pairs


def _parse_pactl_devices(
    sinks_output: str,
    sources_output: str,
    default_sink: str | None,
    default_source: str | None,
) -> list[AudioDevice]:
    """Build the AudioDevice list from ``pactl list sinks`` + ``sources``. Pure; unit-tested.

    Sinks become desktop devices (``is_monitor=True``, captured via ``stream.capture.sink``);
    real sources become mics. Pulse-compat ``<sink>.monitor`` source names are dropped — they
    are not real PipeWire nodes (the sink itself is the capture target).
    """
    devices: list[AudioDevice] = []
    for node_name, display_name in _parse_pactl_blocks(sinks_output):
        devices.append(
            AudioDevice(
                node_name=node_name,
                display_name=display_name,
                is_monitor=True,
                is_default=node_name == default_sink,
            )
        )
    for node_name, display_name in _parse_pactl_blocks(sources_output):
        if node_name.endswith(".monitor"):
            continue  # pulse-compat fiction; capture the sink instead
        devices.append(
            AudioDevice(
                node_name=node_name,
                display_name=display_name,
                is_monitor=False,
                is_default=node_name == default_source,
            )
        )
    return devices


def discover_audio_devices() -> list[AudioDevice]:
    """Enumerate capturable audio nodes (sinks for desktop + real mics) via ``pactl``."""
    sinks_output = _run_pactl(["list", "sinks"])
    sources_output = _run_pactl(["list", "sources"])
    if not sinks_output and not sources_output:
        return []
    default_sink = (_run_pactl(["get-default-sink"]) or "").strip() or None
    default_source = (_run_pactl(["get-default-source"]) or "").strip() or None
    return _parse_pactl_devices(
        sinks_output or "", sources_output or "", default_sink, default_source
    )
