# Audio Capture Design — Desktop + Mic Mixing

**Date:** 2026-06-13 · **Status:** Approved

## Goal

Give saved clips a real audio track. Capture is currently video-only; this adds
multi-device audio capture — any mix of desktop output (sink monitors) and microphones —
selected by the user and mixed into a single Opus track via `audiomixer`. Real audio
devices are their own `pipewiresrc` nodes (NOT routed through the ScreenCast portal).

The pipeline already accepts an optional audio fragment, so this milestone is mostly:
discover devices, resolve the user's selection into concrete nodes, assemble the mixed
audio fragment, and have `build_controller` pass it instead of `None`.

## Components

**`audio.py` — new single-purpose module (mirrors `encoders.py`).**

- `AudioDevice` dataclass — describes one capturable node:
  - `node_name: str` — stable PipeWire `node.name`; this is the identifier stored in config.
  - `display_name: str` — human-readable label for the discovery CLI / future UI.
  - `is_monitor: bool` — True for a sink monitor (desktop audio), False for an input (mic).
  - `is_default: bool` — True if this is the system default for its kind.

- `discover_audio_devices() -> list[AudioDevice]` — **probe-verified, NOT unit-tested.**
  Uses `Gst.DeviceMonitor` filtered to the `Audio/Source` class (PipeWire exposes sink
  monitors there alongside real inputs). Reads `node.name`, a display name, and the
  monitor/default flags from each device's properties. Talks to live hardware, so it is
  verified by the probe and `python -m tea_clipper`, not by unit tests (same split as the
  portal/hotkey D-Bus wrappers).

- `resolve_audio_devices(settings, available) -> list[str]` — **pure, unit-tested.**
  Expands `settings.audio_devices` into a list of concrete `node.name`s to capture:
  - `@desktop@` → the `node.name` of the default sink's monitor (`is_monitor and is_default`).
  - `@mic@` → the `node.name` of the default input (`not is_monitor and is_default`).
  - any other entry → treated as a literal `node.name`.
  Entries that don't resolve to an available device are skipped with a logged warning.
  Order is preserved; duplicates are de-duped. Returns `[]` when nothing resolves.

- `build_audio_fragment(device_names) -> str | None` — **pure, unit-tested.**
  Returns the GStreamer launch fragment that captures every name and mixes them, or
  `None` when `device_names` is empty (→ the pipeline stays video-only).

**Settings change (`settings.py`).**
Replace the two booleans `desktop_audio` / `microphone` with a single list:

```python
audio_devices: list[str] = field(default_factory=lambda: ["@desktop@", "@mic@"])
```

- First-run default `["@desktop@", "@mic@"]` reproduces the old "desktop + mic" behaviour.
- `audio_devices = []` is an explicit "no audio" (video-only) choice.
- Extra entries are literal `node.name`s (from the discovery CLI), so users can add more
  mics/app outputs. TOML-serializable list of strings — no `None` sentinel needed.

**Discovery CLI `audio_probe.py` (`python -m tea_clipper.audio_probe`).**
Calls `discover_audio_devices()` and prints each device's `node.name`, display name, and
monitor/default flags, so users know what to put in `audio_devices`. Doubles as the
hardware-verification probe for `discover_audio_devices`.

**Wiring (`controller.py`, `build_controller`).**
Replace `source_desc=(video, None)` with:

```python
available = discover_audio_devices()
audio = build_audio_fragment(resolve_audio_devices(settings, available))
... CapturePipeline(source_desc=(video, audio), ...)
```

`pipeline.py` is unchanged — it already appends `! opusenc ! replaymux.audio_0` to a
non-`None` audio fragment.

## Fragment shape

Always routed through `audiomixer`, uniform for 1..N devices (a one-input mixer is fine and
keeps timestamps live-synced). For devices A, B:

```
pipewiresrc target-object=<A> ! audioconvert ! audioresample ! queue ! amix.
pipewiresrc target-object=<B> ! audioconvert ! audioresample ! queue ! amix.
audiomixer name=amix ! audioconvert ! audioresample ! queue name=aenc_in
```

The fragment ends in `queue name=aenc_in`, so the pipeline's existing
`{audio_src} ! opusenc ! replaymux.audio_0` links onto it exactly as it does for the
test source. `target-object` selects the node by `node.name`.

## Decisions

- **Multi-device, user-selected.** `audio_devices` is an ordered list; all selected devices
  are mixed into one track. `@desktop@`/`@mic@` are convenience tokens for the system
  defaults; everything else is a literal `node.name`.
- **GstDeviceMonitor for discovery** — GStreamer-native, no new dependency; `Audio/Source`
  surfaces both inputs and sink monitors.
- **Pure builders, probe-only discovery.** `resolve_audio_devices` + `build_audio_fragment`
  are pure and unit-tested; `discover_audio_devices` needs real hardware and is probe-verified.
- **Graceful degradation** (per project convention): a configured device that isn't available
  is skipped with a warning; if nothing resolves, audio is `None` and capture is video-only —
  never a crash.
- **Always mix.** Even a single device goes through `audiomixer` to keep the code path uniform.

## Testing

**Unit (`tests/test_audio.py`, CI, no hardware):**
- `resolve_audio_devices`: `@desktop@`/`@mic@` expand to the right default node names from a
  fake `available` list; literal names pass through; unavailable entries are dropped (warned);
  order preserved and duplicates removed; empty/all-missing input → `[]`.
- `build_audio_fragment`: `None` for `[]`; single device produces one `pipewiresrc` +
  `audiomixer` chain ending in `queue name=aenc_in`; multiple devices produce one
  `! amix.` chain per device plus the mixer; each name appears as `target-object=<name>`.

**Engine (optional, `@pytest.mark.engine`):** the existing test source already covers the
real tee → splitmux → concat path with audio; no new engine test is required, but the
`build_audio_fragment` output can be smoke-parsed via `Gst.parse_launch` if cheap.

**Manual / hardware:**
- `python -m tea_clipper.audio_probe` lists devices on the KDE/Wayland target.
- `python -m tea_clipper` — a saved clip now has a playable audio track mixing the selected
  devices (verify with `ffprobe`/playback).

## Files

```
src/tea_clipper/audio.py          # AudioDevice + discover/resolve/build
src/tea_clipper/audio_probe.py    # python -m tea_clipper.audio_probe (device list + probe)
src/tea_clipper/settings.py       # audio_devices list replaces the two booleans
src/tea_clipper/controller.py     # build_controller passes the real audio fragment
tests/test_audio.py               # unit tests for resolve + build with fakes
```

## Deferred

The PySide6 settings/status UI (the device picker that will drive `audio_devices`),
per-device volume/gain control, and any audio level metering.
